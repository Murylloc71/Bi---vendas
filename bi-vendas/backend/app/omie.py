"""Integração com a API do Omie: pedidos de compra.

Credenciais: variáveis de ambiente OMIE_APP_KEY e OMIE_APP_SECRET (no Replit, em Secrets).
Como alternativa, podem ser salvas pela tela Dados › Omie (ficam no banco).

Documentação do serviço: https://app.omie.com.br/api/v1/produtos/pedidocompra/
    PesquisarPedCompra -> pedidos_pesquisa[] com cabecalho_consulta, produtos_consulta[],
    parcelas_consulta[], frete_consulta.
O status do pedido é o filtro da pesquisa em que ele aparece (Pendentes, Faturados, ...),
porque a API devolve apenas o código da etapa (cEtapa) sem descrição.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from sqlalchemy import delete, insert, select, update

from . import db
from .produto import interpretar

BASE = "https://app.omie.com.br/api/v1/"
STATUS = {  # filtro da API -> rótulo
    "Pendentes": "pendente", "FatParciais": "faturado_parcial", "Faturados": "faturado",
    "RecParciais": "recebido_parcial", "Recebidos": "recebido", "Encerrados": "encerrado",
    "Cancelados": "cancelado",
}
ABERTOS = ("pendente", "faturado_parcial", "faturado", "recebido_parcial")
FLAGS = list(STATUS)


class ErroOmie(Exception):
    pass


def credenciais() -> tuple[str, str, str]:
    k, s = os.environ.get("OMIE_APP_KEY", "").strip(), os.environ.get("OMIE_APP_SECRET", "").strip()
    if k and s:
        return k, s, "ambiente"
    with db.engine.connect() as c:
        v = c.execute(select(db.configuracoes.c.valor).where(db.configuracoes.c.chave == "omie")).scalar()
    if v:
        d = json.loads(v)
        if d.get("app_key") and d.get("app_secret"):
            return d["app_key"], d["app_secret"], "banco"
    return "", "", ""


def salvar_credenciais(app_key: str, app_secret: str):
    with db.engine.begin() as c:
        c.execute(delete(db.configuracoes).where(db.configuracoes.c.chave == "omie"))
        if app_key and app_secret:
            c.execute(insert(db.configuracoes).values(
                chave="omie", valor=json.dumps({"app_key": app_key.strip(), "app_secret": app_secret.strip()})))


def chamar(servico: str, metodo: str, param: dict, tentativas: int = 4, cred: tuple | None = None) -> dict:
    """`cred` = (app_key, app_secret) de outra empresa; sem ele, usa as credenciais dos pedidos."""
    key, secret = cred if cred else credenciais()[:2]
    if not key:
        raise ErroOmie("Credenciais do Omie não configuradas.")
    corpo = json.dumps({"call": metodo, "app_key": key, "app_secret": secret, "param": [param]}).encode()
    espera = 2.0
    for i in range(tentativas):
        req = urllib.request.Request(BASE + servico, data=corpo,
                                     headers={"Content-Type": "application/json", "User-Agent": "bi-vendas/2.0"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                dados = json.loads(r.read().decode("utf-8"))
            if isinstance(dados, dict) and dados.get("faultstring"):
                if "Não existem registros" in dados["faultstring"]:
                    return {"pedidos_pesquisa": [], "produtos": [], "nTotalPaginas": 0, "nTotPaginas": 0, "nTotalRegistros": 0}
                raise ErroOmie(dados["faultstring"])
            return dados
        except urllib.error.HTTPError as e:
            try:
                det = json.loads(e.read().decode("utf-8"))
            except Exception:  # noqa: BLE001
                det = {"faultstring": f"HTTP {e.code}"}
            msg = det.get("faultstring", "")
            if "Não existem registros" in msg:
                return {"pedidos_pesquisa": [], "produtos": [], "nTotalPaginas": 0, "nTotPaginas": 0, "nTotalRegistros": 0}
            if "chave de acesso" in msg.lower() or "app_key" in msg.lower() or e.code in (401, 403):
                raise ErroOmie(f"Omie recusou as credenciais: {msg}") from e
            # consumo redundante / limite / instabilidade: tenta de novo
            if i < tentativas - 1 and (e.code in (425, 429, 500, 502, 503, 504) or "REDUNDANT" in msg.upper()):
                time.sleep(espera)
                espera *= 2
                continue
            raise ErroOmie(msg or f"HTTP {e.code}") from e
        except urllib.error.URLError as e:
            if i < tentativas - 1:
                time.sleep(espera)
                espera *= 2
                continue
            raise ErroOmie(f"Sem conexão com o Omie: {e.reason}") from e
    raise ErroOmie("Falha ao consultar o Omie.")


def _data(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except ValueError:
        return None


def _fornecedor(cod: int, cache: dict) -> dict:
    if cod in cache:
        return cache[cod]
    try:
        r = chamar("geral/clientes/", "ConsultarCliente", {"codigo_cliente_omie": cod})
        info = {"nome": r.get("razao_social") or r.get("nome_fantasia") or str(cod),
                "fantasia": r.get("nome_fantasia") or "", "cnpj": r.get("cnpj_cpf") or ""}
    except ErroOmie:
        info = {"nome": str(cod), "fantasia": "", "cnpj": ""}
    cache[cod] = info
    return info


def pesquisar(flag: str, pagina: int, por_pagina: int = 50) -> dict:
    p = {"nPagina": pagina, "nRegsPorPagina": por_pagina, "lApenasImportadoApi": "F"}
    for f in FLAGS:
        p[f"lExibirPedidos{f}"] = "T" if f == flag else "F"
    return chamar("produtos/pedidocompra/", "PesquisarPedCompra", p)


def normalizar_pedido(x: dict, status: str, fornecedor: dict) -> tuple[dict, list[dict]]:
    c = x.get("cabecalho_consulta", {})
    itens = []
    for it in x.get("produtos_consulta", []) or []:
        p = interpretar(it.get("cProduto") or "", com_tamanho=True)
        itens.append({
            "id": int(it["nCodItem"]), "pedido_id": int(c["nCodPed"]),
            "codigo": (it.get("cProduto") or "")[:160],
            "sku": p.sku if p.categoria == "calcado" else (it.get("cProduto") or "").upper()[:120],
            "modelo": p.modelo if p.categoria == "calcado" else None,
            "tamanho": p.tamanho, "ean": (it.get("cEAN") or "")[:20],
            "descricao": (it.get("cDescricao") or "")[:200],
            "quantidade": float(it.get("nQtde") or 0), "quantidade_recebida": float(it.get("nQtdeRec") or 0),
            "valor_unitario": float(it.get("nValUnit") or 0), "valor_mercadoria": float(it.get("nValMerc") or 0),
            "desconto": float(it.get("nDesconto") or 0), "valor_total": float(it.get("nValTot") or 0),
        })
    parcelas = [{"parcela": pc.get("nParcela"), "vencimento": (_data(pc.get("dVencto")) or "").__str__(),
                 "valor": pc.get("nValor"), "dias": pc.get("nDias")} for pc in x.get("parcelas_consulta", []) or []]
    frete = x.get("frete_consulta") or {}
    ped = {
        "id": int(c["nCodPed"]), "numero": str(c.get("cNumero") or ""), "numero_fornecedor": str(c.get("cNumPedido") or ""),
        "fornecedor_id": int(c.get("nCodFor") or 0), "fornecedor": fornecedor["nome"][:200],
        "fornecedor_cnpj": fornecedor["cnpj"][:20], "status": status, "etapa": str(c.get("cEtapa") or ""),
        "data_inclusao": _data(c.get("dIncData")), "previsao": _data(c.get("dDtPrevisao")),
        "pares": sum(i["quantidade"] for i in itens), "pares_recebidos": sum(i["quantidade_recebida"] for i in itens),
        "valor_mercadoria": sum(i["valor_mercadoria"] for i in itens),
        "valor_total": sum(i["valor_total"] for i in itens) + float(frete.get("nValFrete") or 0),
        "frete": float(frete.get("nValFrete") or 0), "parcelas": json.dumps(parcelas),
        "condicao": str(c.get("cCodParc") or ""), "observacao": (c.get("cObs") or "")[:2000],
        "atualizado_em": datetime.utcnow(),
    }
    return ped, itens


_estado = {"rodando": False, "inicio": None, "fim": None, "erro": None, "progresso": "", "resumo": None}
_lock = threading.Lock()


def estado() -> dict:
    key, _, origem = credenciais()
    with db.engine.connect() as c:
        ult = c.execute(select(db.configuracoes.c.valor).where(db.configuracoes.c.chave == "omie_ultima_sync")).scalar()
    return {**{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in _estado.items()},
            "configurado": bool(key), "origem_credenciais": origem,
            "app_key_final": key[-4:] if key else None, "ultima_sync": json.loads(ult) if ult else None}


def sincronizar() -> dict:
    """Baixa todos os pedidos de compra (todos os status) e substitui a cópia local."""
    with _lock:
        if _estado["rodando"]:
            raise ErroOmie("Uma sincronização já está em andamento.")
        _estado.update(rodando=True, inicio=datetime.utcnow(), fim=None, erro=None, progresso="iniciando")
    try:
        pedidos, itens, cache_forn = {}, {}, {}
        for flag, status in STATUS.items():
            pag, total = 1, 1
            while pag <= total:
                _estado["progresso"] = f"{flag}: página {pag}/{total}"
                r = pesquisar(flag, pag)
                total = int(r.get("nTotalPaginas") or 0)
                for x in r.get("pedidos_pesquisa", []) or []:
                    forn = _fornecedor(int(x["cabecalho_consulta"].get("nCodFor") or 0), cache_forn)
                    ped, its = normalizar_pedido(x, status, forn)
                    pedidos[ped["id"]] = ped
                    for it in its:
                        itens[it["id"]] = it
                pag += 1
        with db.engine.begin() as c:
            c.execute(delete(db.omie_itens))
            c.execute(delete(db.omie_pedidos))
            if pedidos:
                c.execute(insert(db.omie_pedidos), list(pedidos.values()))
            if itens:
                lst = list(itens.values())
                for i in range(0, len(lst), 1000):
                    c.execute(insert(db.omie_itens), lst[i:i + 1000])
            resumo = {"pedidos": len(pedidos), "itens": len(itens), "quando": datetime.utcnow().isoformat(),
                      "por_status": {s: sum(1 for p in pedidos.values() if p["status"] == s) for s in STATUS.values()}}
            c.execute(delete(db.configuracoes).where(db.configuracoes.c.chave == "omie_ultima_sync"))
            c.execute(insert(db.configuracoes).values(chave="omie_ultima_sync", valor=json.dumps(resumo)))
        _estado.update(resumo=resumo, progresso="concluída")
        return resumo
    except Exception as e:  # noqa: BLE001
        _estado.update(erro=str(e), progresso="falhou")
        raise
    finally:
        _estado.update(rodando=False, fim=datetime.utcnow())


def sincronizar_em_segundo_plano():
    def run():
        try:
            sincronizar()
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=run, daemon=True).start()


def agendar(horas: float):
    """Sincroniza ao iniciar e a cada `horas` horas (enquanto o servidor estiver no ar)."""
    def loop():
        time.sleep(10)
        while True:
            if credenciais()[0]:
                try:
                    sincronizar()
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(max(0.25, horas) * 3600)
    threading.Thread(target=loop, daemon=True).start()


def importar_json(pedidos_brutos: list[dict]) -> dict:
    """Grava pedidos já baixados (mesmo formato de PesquisarPedCompra + campo __filtro)."""
    pedidos, itens = {}, {}
    for x in pedidos_brutos:
        status = STATUS.get(x.get("__filtro"), "pendente")
        forn = x.get("__fornecedor") or {"nome": str(x["cabecalho_consulta"].get("nCodFor")), "cnpj": ""}
        ped, its = normalizar_pedido(x, status, forn)
        pedidos[ped["id"]] = ped
        for it in its:
            itens[it["id"]] = it
    with db.engine.begin() as c:
        c.execute(delete(db.omie_itens))
        c.execute(delete(db.omie_pedidos))
        if pedidos:
            c.execute(insert(db.omie_pedidos), list(pedidos.values()))
        if itens:
            c.execute(insert(db.omie_itens), list(itens.values()))
        resumo = {"pedidos": len(pedidos), "itens": len(itens), "quando": datetime.utcnow().isoformat(),
                  "por_status": {s: sum(1 for p in pedidos.values() if p["status"] == s) for s in STATUS.values()}}
        c.execute(delete(db.configuracoes).where(db.configuracoes.c.chave == "omie_ultima_sync"))
        c.execute(insert(db.configuracoes).values(chave="omie_ultima_sync", valor=json.dumps(resumo)))
    return resumo


def importar_snapshot(caminho) -> dict:
    """Carrega um instantâneo compacto de pedidos (dados_iniciais/omie_pedidos.json).
    Formato: {"C": [[filtro, nCodPed, cNumero, cNumPedido, nCodFor, cEtapa, dIncData, dDtPrevisao,
    cCodParc, cObs, nValFrete, parcelas[[n, venc, valor, dias]], itens["cProduto|q|qRec|vUnit|desc|vTot|nCodItem"]]],
    "D": {sku_base: descrição}, "F": {nCodFor: {nome, cnpj}}}"""
    d = json.load(open(caminho, encoding="utf-8"))
    forn = {int(k): v for k, v in (d.get("F") or {}).items()}
    brutos = []
    for r in d["C"]:
        filtro, cod, num, numf, codfor, etapa, dinc, dprev, parc, obs, frete, parcelas, itens = r
        prods = []
        for s in itens:
            cprod, q, qr, vu, desc, vt, cod_item = s.split("|")
            base = cprod.rsplit("-", 1)[0]
            prods.append({"nCodItem": int(cod_item), "cProduto": cprod, "cEAN": "",
                          "cDescricao": d["D"].get(base, ""), "nQtde": float(q), "nQtdeRec": float(qr),
                          "nValUnit": float(vu), "nValMerc": float(q) * float(vu), "nDesconto": float(desc),
                          "nValTot": float(vt)})
        brutos.append({
            "__filtro": filtro,
            "__fornecedor": forn.get(int(codfor), {"nome": "CALCADOS BEIRA RIO S/A", "cnpj": ""}),
            "cabecalho_consulta": {"nCodPed": cod, "cNumero": num, "cNumPedido": numf, "nCodFor": codfor,
                                   "cEtapa": etapa, "dIncData": dinc, "dDtPrevisao": dprev, "cCodParc": parc, "cObs": obs},
            "frete_consulta": {"nValFrete": frete},
            "parcelas_consulta": [{"nParcela": p[0], "dVencto": p[1], "nValor": p[2], "nDias": p[3]} for p in parcelas],
            "produtos_consulta": prods,
        })
    return importar_json(brutos)
