"""Orquestração das importações: detecção, prévia (dry-run), confirmação e desfazer."""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, delete, insert, select, update

from .. import db
from . import compras, estoque, itens_compra, vendas, vendas_dia
from .comum import ErroImportacao, assinatura, ler_arquivo

MODULOS = {"vendas": vendas, "estoque": estoque, "compras": compras, "vendas_dia": vendas_dia, "itens_compra": itens_compra}
TMP = db.STORAGE / "tmp"
TMP.mkdir(exist_ok=True)


def detectar_tipo(abas, nome: str) -> str | None:
    n = nome.lower()
    if vendas.parece_vendas(abas):
        return "vendas"
    if itens_compra.parece_itens_compra(abas, nome):
        return "itens_compra"
    if compras.parece_compras(abas) or "compra" in n:
        return "compras"
    if vendas_dia.parece_vendas_dia(abas, nome):
        return "vendas_dia"
    if estoque.parece_estoque(abas):
        return "estoque"
    return None


def sugerir_deposito(nome: str) -> str:
    base = nome.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    base = base.split("-", 1)[-1] if len(base.split("-", 1)[0]) == 8 else base
    return base.replace("_", " ").strip().title()


def _assinatura_abas(abas):
    cols = []
    for k, df in abas.items():
        cols += [f"{k}:{c}" for c in df.columns] if len(abas) > 1 else list(df.columns)
    return assinatura(cols)


def mapeamento_salvo(conn, tipo, assin):
    r = conn.execute(select(db.mapeamentos).where((db.mapeamentos.c.tipo == tipo) &
                                                  (db.mapeamentos.c.assinatura == assin))).first()
    return json.loads(r.mapeamento) if r else None


def preparar(nome: str, conteudo: bytes) -> dict:
    token = uuid.uuid4().hex
    caminho = TMP / f"{token}__{nome.replace('/', '_')}"
    caminho.write_bytes(conteudo)
    abas = ler_arquivo(nome, conteudo)
    tipo = detectar_tipo(abas, nome)
    return {"token": token, "arquivo": nome, "tipo": tipo, "abas": abas, "caminho": str(caminho)}


def _carregar(token: str):
    achados = list(TMP.glob(f"{token}__*"))
    if not achados:
        raise ErroImportacao("Arquivo da prévia expirou. Envie novamente.")
    caminho = achados[0]
    nome = caminho.name.split("__", 1)[1]
    return nome, caminho, ler_arquivo(nome, caminho.read_bytes())


def executar(token: str, tipo: str, mapeamento: dict | None, params: dict, confirmar: bool) -> dict:
    if tipo not in MODULOS:
        raise ErroImportacao("Tipo de arquivo não reconhecido. Escolha vendas, estoque ou compras.")
    nome, caminho, abas = _carregar(token)
    mod = MODULOS[tipo]
    assin = _assinatura_abas(abas)
    params = dict(params)
    params["data_referencia"] = params.get("data_referencia") or date.today()
    if isinstance(params["data_referencia"], str):
        params["data_referencia"] = date.fromisoformat(params["data_referencia"])
    if tipo == "estoque" and not params.get("deposito"):
        params["deposito"] = sugerir_deposito(nome)
    if tipo == "vendas_dia":
        params["canal"] = params.get("canal") or "nao_informado"
        ini, fim = vendas_dia.periodo(params)
        params["periodo_inicio"], params["periodo_fim"] = ini, fim
        params["data_referencia"] = fim
        # guarda canal + período no histórico (e para saber o que desfazer)
        params["conta"] = (params.get("conta") or "").strip()[:60]
        params["deposito"] = vendas_dia.rotulo(params["canal"], ini, fim, params["conta"])

    with db.engine.connect() as conn:
        trans = conn.begin()
        try:
            mapa = mapeamento or mapeamento_salvo(conn, tipo, assin) or mod.sugerir_mapeamento(abas)
            mapa = _ajustar_mapa(mapa, abas, mod)
            imp_id = conn.execute(insert(db.importacoes).values(
                tipo=tipo, arquivo=nome, criado_em=datetime.utcnow(),
                data_referencia=params["data_referencia"], deposito=params.get("deposito"),
                modo=params.get("modo"), status="ok", mapeamento=db.dumps(mapa))).inserted_primary_key[0]
            res = mod.importar(conn, abas, mapa, params, imp_id)
            resumo = res.dict()
            if not confirmar:
                trans.rollback()
            else:
                destino = db.STORAGE / "uploads" / f"{imp_id:05d}_{nome}"
                shutil.copyfile(caminho, destino)
                conn.execute(update(db.importacoes).where(db.importacoes.c.id == imp_id).values(
                    resumo=db.dumps(resumo), armazenado_em=str(destino)))
                _salvar_mapeamento(conn, tipo, assin, abas, mapa)
                trans.commit()
                caminho.unlink(missing_ok=True)
        except Exception:
            trans.rollback()
            raise
    colunas = {k: list(df.columns) for k, df in abas.items()}
    return {"token": token, "arquivo": nome, "tipo": tipo, "mapeamento": mapa, "colunas": colunas,
            "resumo": resumo, "confirmado": confirmar, "importacao_id": imp_id if confirmar else None,
            "parametros": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in params.items()}}


def _ajustar_mapa(mapa, abas, mod):
    """Um mapeamento salvo (ou vindo de outro arquivo parecido) pode citar a aba ou as colunas com
    outra grafia ("SKU" x "Sku", "Preço com Desconto" x "Preço Com Desconto"). Ajusta para os nomes
    reais do arquivo; o que não for encontrado volta para a sugestão automática."""
    from .comum import normalizar_texto
    if not isinstance(mapa, dict) or "colunas" not in mapa:
        return mapa
    mapa = {**mapa, "colunas": dict(mapa.get("colunas") or {})}
    aba = mapa.get("aba")
    if aba not in abas:
        alvo = normalizar_texto(aba or "")
        aba = next((k for k in abas if normalizar_texto(k) == alvo), next(iter(abas)))
        mapa["aba"] = aba
    cols = list(abas[aba].columns)
    norm = {normalizar_texto(c): c for c in cols}
    sug = None
    for campo, col in list(mapa["colunas"].items()):
        if col is None or col in cols:
            continue
        achada = norm.get(normalizar_texto(col))
        if achada is None:
            if sug is None:
                sug = (mod.sugerir_mapeamento({aba: abas[aba]}) or {}).get("colunas", {})
            achada = sug.get(campo)
        mapa["colunas"][campo] = achada
    return mapa


def _salvar_mapeamento(conn, tipo, assin, abas, mapa):
    ex = conn.execute(select(db.mapeamentos.c.id).where((db.mapeamentos.c.tipo == tipo) &
                                                        (db.mapeamentos.c.assinatura == assin))).first()
    vals = dict(mapeamento=db.dumps(mapa), atualizado_em=datetime.utcnow(),
                colunas=db.dumps({k: list(df.columns) for k, df in abas.items()}))
    if ex:
        conn.execute(update(db.mapeamentos).where(db.mapeamentos.c.id == ex.id).values(**vals))
    else:
        conn.execute(insert(db.mapeamentos).values(tipo=tipo, assinatura=assin, **vals))


def _converter(tabela, linha: dict) -> dict:
    out = {}
    for c in tabela.columns:
        if c.name not in linha:
            continue
        v = linha[c.name]
        if v is not None and isinstance(c.type, Date) and isinstance(v, str):
            v = date.fromisoformat(v[:10])
        elif v is not None and isinstance(c.type, DateTime) and isinstance(v, str):
            v = datetime.fromisoformat(v)
        out[c.name] = v
    return out


def desfazer(importacao_id: int) -> dict:
    with db.engine.begin() as conn:
        imp = conn.execute(select(db.importacoes).where(db.importacoes.c.id == importacao_id)).first()
        if not imp:
            raise ErroImportacao("Importação não encontrada.")
        if imp.status != "ok":
            raise ErroImportacao("Esta importação já foi desfeita.")
        cond = ((db.importacoes.c.tipo == imp.tipo) & (db.importacoes.c.id > imp.id) &
                (db.importacoes.c.status == "ok"))
        if imp.tipo == "estoque":
            cond = (cond & (db.importacoes.c.deposito == imp.deposito) &
                    (db.importacoes.c.data_referencia == imp.data_referencia))
        if imp.tipo == "vendas_dia":
            cond = cond & (db.importacoes.c.deposito == imp.deposito)
        posterior = conn.execute(select(db.importacoes.c.id).where(cond)).first()
        if posterior:
            raise ErroImportacao(f"Existe uma importação posterior do mesmo tipo (#{posterior.id}). "
                                 "Desfaça primeiro as mais recentes.")
        alts = list(conn.execute(select(db.alteracoes).where(db.alteracoes.c.importacao_id == importacao_id)
                                 .order_by(db.alteracoes.c.id.desc())))
        tabelas = {t.name: t for t in db.meta.sorted_tables}
        n = 0
        for a in alts:
            if a.tabela == "estoque_snapshots":
                if a.antes is None:
                    conn.execute(delete(db.estoque_itens).where(db.estoque_itens.c.snapshot_id == a.registro_id))
                    conn.execute(delete(db.estoque_snapshots).where(db.estoque_snapshots.c.id == a.registro_id))
                else:
                    ant = json.loads(a.antes)
                    conn.execute(insert(db.estoque_snapshots).values(**_converter(db.estoque_snapshots, ant["snapshot"])))
                    if ant["itens"]:
                        conn.execute(insert(db.estoque_itens), [_converter(db.estoque_itens, i) for i in ant["itens"]])
                n += 1
                continue
            t = tabelas[a.tabela]
            if a.antes is None:
                conn.execute(delete(t).where(t.c.id == a.registro_id))
            else:
                linha = _converter(t, json.loads(a.antes))
                existe = conn.execute(select(t.c.id).where(t.c.id == linha["id"])).first()
                if existe:
                    conn.execute(update(t).where(t.c.id == linha["id"]).values(**linha))
                else:
                    conn.execute(insert(t).values(**linha))
            n += 1
        conn.execute(delete(db.alteracoes).where(db.alteracoes.c.importacao_id == importacao_id))
        conn.execute(update(db.importacoes).where(db.importacoes.c.id == importacao_id).values(status="desfeita"))
    return {"importacao_id": importacao_id, "registros_revertidos": n}


def revincular_estoque() -> dict:
    """Recalcula o vínculo de todos os itens de estoque (após nova importação de vendas ou vínculo manual)."""
    with db.engine.begin() as conn:
        manuais = {r.codigo: (r.sku, r.tamanho) for r in conn.execute(select(db.vinculos))}
        conhecidos = estoque.skus_conhecidos(conn)
        cache = {}
        n = 0
        for r in conn.execute(select(db.estoque_itens.c.id, db.estoque_itens.c.codigo,
                                     db.estoque_itens.c.sku, db.estoque_itens.c.vinculo)).all():
            if r.codigo not in cache:
                cache[r.codigo] = estoque.vincular(r.codigo, manuais, conhecidos)
            sku, tam, origem = cache[r.codigo]
            if sku != r.sku or origem != r.vinculo:
                conn.execute(update(db.estoque_itens).where(db.estoque_itens.c.id == r.id)
                             .values(sku=sku, tamanho=tam, vinculo=origem))
                n += 1
        # vendas lançadas por período usam o mesmo vínculo de códigos
        for r in conn.execute(select(db.vendas_lancamentos.c.id, db.vendas_lancamentos.c.codigo,
                                     db.vendas_lancamentos.c.sku)).all():
            if r.codigo not in cache:
                cache[r.codigo] = estoque.vincular(r.codigo, manuais, conhecidos)
            sku, tam, _ = cache[r.codigo]
            if sku != r.sku:
                conn.execute(update(db.vendas_lancamentos).where(db.vendas_lancamentos.c.id == r.id)
                             .values(sku=sku, tamanho=tam))
                n += 1
    return {"itens_atualizados": n}
