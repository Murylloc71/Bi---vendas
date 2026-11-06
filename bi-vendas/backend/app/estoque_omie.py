"""Estoque pela API do Omie, no lugar das planilhas de estoque.

Unlock  = local "Geral" do Omie 03 (UAI COMPREI 03, Extrema)
Juatuba = local "Geral" do Omie 04 (UAI COMPREI 04, Juatuba)

Credenciais (chave de aplicativo de cada empresa): Secrets OMIE03_APP_KEY / OMIE03_APP_SECRET e
OMIE04_APP_KEY / OMIE04_APP_SECRET, ou salvas na tela Dados › Omie.

Cada sincronização vira uma foto de estoque do dia, gravada pelo mesmo caminho da importação de
planilha (vínculo de códigos, histórico, desfazer, tendência). Sincronizar de novo no mesmo dia
substitui a foto do dia.

API: estoque/local ListarLocaisEstoque (acha o "Geral") e estoque/consulta ListarPosEstoque
(produtos[]: cCodigo, fisico, reservado, nSaldo), paginada com nPagina/nRegPorPagina, uma página
por vez (a API recusa chamadas simultâneas).
"""
from __future__ import annotations

import csv
import io
import json
import os
import threading
import time
from datetime import date, datetime

from sqlalchemy import delete, insert, select

from . import db
from . import importadores as imp
from .importadores.comum import normalizar_texto
from .omie import ErroOmie, chamar

CONTAS = [
    {"id": "03", "deposito": "Unlock", "empresa": "UAI COMPREI 03 (Extrema)", "env": "OMIE03"},
    {"id": "04", "deposito": "Juatuba", "empresa": "UAI COMPREI 04 (Juatuba)", "env": "OMIE04"},
]
CAMPOS = {"fisico": "Físico (o que está no depósito)", "disponivel": "Disponível (físico − reservado)"}
POR_PAGINA = 500

_lock = threading.Lock()
_estado = {"rodando": False, "progresso": None, "erro": None, "inicio": None, "fim": None}


def _conta(cid):
    c = next((x for x in CONTAS if x["id"] == cid), None)
    if not c:
        raise ErroOmie(f"Empresa {cid} não configurável para estoque.")
    return c


def _cfg(cid) -> dict:
    with db.engine.connect() as c:
        v = c.execute(select(db.configuracoes.c.valor).where(db.configuracoes.c.chave == f"omie_estoque_{cid}")).scalar()
    return json.loads(v) if v else {}


def _salvar_cfg(cid, dados: dict):
    with db.engine.begin() as c:
        c.execute(delete(db.configuracoes).where(db.configuracoes.c.chave == f"omie_estoque_{cid}"))
        c.execute(insert(db.configuracoes).values(chave=f"omie_estoque_{cid}", valor=json.dumps(dados, default=str)))


def credenciais(cid) -> tuple[str, str, str]:
    conta = _conta(cid)
    k = os.environ.get(f"{conta['env']}_APP_KEY", "").strip()
    s = os.environ.get(f"{conta['env']}_APP_SECRET", "").strip()
    if k and s:
        return k, s, "ambiente"
    cfg = _cfg(cid)
    if cfg.get("app_key") and cfg.get("app_secret"):
        return cfg["app_key"], cfg["app_secret"], "banco"
    return "", "", ""


def configurar(cid, app_key=None, app_secret=None, campo=None, ativo=None):
    cfg = _cfg(cid)
    if app_key is not None and app_secret is not None:
        if app_key.strip() and app_secret.strip():
            cfg.update(app_key=app_key.strip(), app_secret=app_secret.strip())
            cfg.pop("local", None)          # outra empresa/credencial: procura o Geral de novo
        else:
            cfg.pop("app_key", None); cfg.pop("app_secret", None)
    if campo in CAMPOS:
        cfg["campo"] = campo
    if ativo is not None:
        cfg["ativo"] = bool(ativo)
    _salvar_cfg(cid, cfg)
    return estado()


def achar_local_geral(cid) -> dict:
    """Procura o local de estoque "Geral" (ou o padrão) da empresa."""
    k, s, _ = credenciais(cid)
    if not k:
        raise ErroOmie(f"Credenciais do Omie {cid} não configuradas.")
    r = chamar("estoque/local/", "ListarLocaisEstoque", {"nPagina": 1, "nRegPorPagina": 100}, cred=(k, s))
    locais = [x for x in (r.get("locaisEncontrados") or []) if x.get("inativo") != "S"]
    if not locais:
        raise ErroOmie(f"Nenhum local de estoque encontrado no Omie {cid}.")
    geral = [x for x in locais if normalizar_texto(x.get("descricao")).startswith("geral")]
    escolhido = (geral or [x for x in locais if x.get("padrao") == "S"] or locais)[0]
    info = {"codigo": int(escolhido["codigo_local_estoque"]), "descricao": escolhido.get("descricao"),
            "locais": [x.get("descricao") for x in locais]}
    cfg = _cfg(cid); cfg["local"] = info; _salvar_cfg(cid, cfg)
    return info


def baixar_posicao(cid) -> tuple[list[dict], dict]:
    k, s, _ = credenciais(cid)
    if not k:
        raise ErroOmie(f"Credenciais do Omie {cid} não configuradas.")
    cfg = _cfg(cid)
    local = cfg.get("local") or achar_local_geral(cid)
    hoje = date.today().strftime("%d/%m/%Y")
    itens, pag, total = {}, 1, 1
    while pag <= total:
        _estado["progresso"] = f"Omie {cid}: página {pag}/{total}"
        r = chamar("estoque/consulta/", "ListarPosEstoque",
                   {"nPagina": pag, "nRegPorPagina": POR_PAGINA, "dDataPosicao": hoje, "cExibeTodos": "N",
                    "codigo_local_estoque": local["codigo"]}, cred=(k, s))
        total = int(r.get("nTotPaginas") or 0)
        for p in r.get("produtos") or []:
            cod = str(p.get("cCodigo") or "").strip()
            if not cod:
                continue
            fis = float(p.get("fisico") if p.get("fisico") is not None else (p.get("nSaldo") or 0))
            res = float(p.get("reservado") or 0)
            ant = itens.get(cod)
            itens[cod] = {"codigo": cod, "descricao": p.get("cDescricao") or "",
                          "fisico": fis + (ant["fisico"] if ant else 0), "reservado": res + (ant["reservado"] if ant else 0)}
        pag += 1
        if pag <= total:
            time.sleep(0.4)   # uma página por vez, sem atropelar o limite da API
    return list(itens.values()), local


def _apagar_sync_anterior_do_dia(conn, deposito, dia):
    """Uma sincronização substitui a do mesmo dia sem acumular histórico de desfazer."""
    ids = [r.id for r in conn.execute(select(db.importacoes.c.id).where(
        (db.importacoes.c.tipo == "estoque") & (db.importacoes.c.deposito == deposito)
        & (db.importacoes.c.data_referencia == dia) & (db.importacoes.c.modo == "api")))]
    if not ids:
        return
    snaps = [r.id for r in conn.execute(select(db.estoque_snapshots.c.id).where(
        (db.estoque_snapshots.c.deposito == deposito) & (db.estoque_snapshots.c.data == dia)
        & (db.estoque_snapshots.c.importacao_id.in_(ids))))]
    if snaps:
        conn.execute(delete(db.estoque_itens).where(db.estoque_itens.c.snapshot_id.in_(snaps)))
        conn.execute(delete(db.estoque_snapshots).where(db.estoque_snapshots.c.id.in_(snaps)))
    conn.execute(delete(db.alteracoes).where(db.alteracoes.c.importacao_id.in_(ids)))
    conn.execute(delete(db.importacoes).where(db.importacoes.c.id.in_(ids)))


def sincronizar_conta(cid) -> dict:
    conta = _conta(cid)
    itens, local = baixar_posicao(cid)
    campo = _cfg(cid).get("campo", "fisico")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Código do produto", "Quantidade"])
    for it in itens:
        q = it["fisico"] - (it["reservado"] if campo == "disponivel" else 0)
        w.writerow([it["codigo"], f"{q:g}"])
    hoje = date.today()
    with db.engine.begin() as c:
        _apagar_sync_anterior_do_dia(c, conta["deposito"], hoje)
    nome = f"Omie {cid} - {local['descricao']} (API).csv"
    prev = imp.preparar(nome, buf.getvalue().encode("utf-8"))
    r = imp.executar(prev["token"], "estoque",
                     {"aba": "csv", "colunas": {"codigo": "Código do produto", "quantidade": "Quantidade"}},
                     {"deposito": conta["deposito"], "data_referencia": hoje.isoformat(), "modo": "api"}, confirmar=True)
    det = r["resumo"].get("detalhes", {})
    out = {"empresa": f"Omie {cid}", "deposito": conta["deposito"], "local": local["descricao"], "codigos": len(itens),
           "unidades": det.get("quantidade_total"), "sem_vinculo": det.get("sem_vinculo"), "campo": campo,
           "quando": datetime.now().strftime("%Y-%m-%d %H:%M"), "importacao_id": r["importacao_id"]}
    cfg = _cfg(cid); cfg["ultima"] = out; cfg.pop("erro", None); _salvar_cfg(cid, cfg)
    return out


def sincronizar() -> dict:
    """Sincroniza todas as empresas configuradas; o erro de uma não impede a outra."""
    with _lock:
        if _estado["rodando"]:
            raise ErroOmie("Uma sincronização de estoque já está em andamento.")
        _estado.update(rodando=True, erro=None, inicio=datetime.now(), fim=None, progresso="iniciando")
    resultados, erros = [], []
    try:
        for conta in CONTAS:
            cid = conta["id"]
            if not credenciais(cid)[0] or _cfg(cid).get("ativo") is False:
                continue
            try:
                resultados.append(sincronizar_conta(cid))
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "acesso" in msg.lower() and "estoque" in msg.lower():
                    msg += " (no Omie, libere o acesso a estoque para o aplicativo/usuário da integração)"
                erros.append(f"Omie {cid}: {msg}")
                cfg = _cfg(cid); cfg["erro"] = {"msg": msg, "quando": datetime.now().strftime("%Y-%m-%d %H:%M")}; _salvar_cfg(cid, cfg)
        _estado.update(progresso="concluída" if not erros else "concluída com erro", erro="; ".join(erros) or None)
        return {"resultados": resultados, "erros": erros}
    finally:
        _estado.update(rodando=False, fim=datetime.now())


def sincronizar_em_segundo_plano():
    def run():
        try:
            sincronizar()
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=run, daemon=True).start()


def agendar(horas: float):
    """Sincroniza ao iniciar e a cada `horas` horas, enquanto o servidor estiver no ar."""
    def loop():
        time.sleep(20)
        while True:
            if any(credenciais(c["id"])[0] for c in CONTAS):
                try:
                    sincronizar()
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(max(0.5, horas) * 3600)
    threading.Thread(target=loop, daemon=True).start()


def estado() -> dict:
    contas = []
    for conta in CONTAS:
        k, _, origem = credenciais(conta["id"])
        cfg = _cfg(conta["id"])
        contas.append({**{x: conta[x] for x in ("id", "deposito", "empresa")}, "configurado": bool(k), "origem": origem,
                       "app_key_final": k[-4:] if k else None, "local": cfg.get("local"), "campo": cfg.get("campo", "fisico"),
                       "ativo": cfg.get("ativo", True), "ultima": cfg.get("ultima"), "erro": cfg.get("erro"),
                       "secrets": f"{conta['env']}_APP_KEY / {conta['env']}_APP_SECRET"})
    return {"contas": contas, "campos": CAMPOS, **{k: (v.strftime("%Y-%m-%d %H:%M") if isinstance(v, datetime) else v) for k, v in _estado.items()},
            "horas": float(os.environ.get("OMIE_ESTOQUE_HORAS", "6") or 0)}
