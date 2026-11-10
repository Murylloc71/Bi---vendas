"""Indicadores dos pedidos de compra (Omie) e cruzamento com estoque e vendas."""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd

from . import db
from . import indicadores as ind
from .omie import ABERTOS
from .produto import interpretar

ROTULO_STATUS = {"pendente": "Pendente", "faturado_parcial": "Faturado parcial", "faturado": "Faturado",
                 "recebido_parcial": "Recebido parcial", "recebido": "Recebido", "encerrado": "Encerrado",
                 "cancelado": "Cancelado"}
f = ind._f


def carregar(fornecedor: str | None = None):
    P = pd.read_sql("select * from omie_pedidos", db.engine)
    I = pd.read_sql("select * from omie_itens", db.engine)
    if P.empty:
        return P, I
    for c in ("data_inclusao", "previsao"):
        P[c] = pd.to_datetime(P[c])
    if fornecedor:
        P = P[P["fornecedor"] == fornecedor]
        I = I[I["pedido_id"].isin(P["id"])]
    if not I.empty:   # modelo pela regra atual (ex.: modelos separados por cabedal)
        _m = {s_: interpretar(s_, com_tamanho=False).modelo for s_ in I["sku"].dropna().unique()}
        I["modelo"] = I["sku"].map(_m).where(I["sku"].notna(), I["modelo"])
    from . import linha as _linha
    from . import abc as _abc
    if _linha.MODO.get() and not I.empty:   # filtro global de produtos em linha
        I = I[_linha.mascara(I["modelo"].fillna(""), _linha.MODO.get())]
        P = P[P["id"].isin(I["pedido_id"])]
    if _abc.MODO.get() and not I.empty:     # filtro global de curva ABC
        from .indicadores import dados_base
        I = I[_abc.mascara(I["modelo"].fillna(""), _abc.MODO.get(), _abc.classificar(dados_base())["classes"])]
        P = P[P["id"].isin(I["pedido_id"])]
    I = I.merge(P[["id", "status", "previsao", "numero", "fornecedor"]], left_on="pedido_id", right_on="id",
                suffixes=("", "_ped"))
    I["a_receber"] = np.where(I["status"].isin(ABERTOS), (I["quantidade"] - I["quantidade_recebida"]).clip(lower=0), 0.0)
    I["valor_a_receber"] = np.where(I["quantidade"] > 0, I["valor_total"] * I["a_receber"] / I["quantidade"], 0.0)
    return P, I


def fornecedores():
    P = pd.read_sql("select fornecedor, count(*) as n, sum(pares) as pares from omie_pedidos group by fornecedor", db.engine)
    return [{"fornecedor": r.fornecedor, "pedidos": int(r.n), "pares": f(r.pares, 0)} for r in P.sort_values("pares", ascending=False).itertuples()]


def fornecedor_padrao():
    lst = fornecedores()
    beira = next((x["fornecedor"] for x in lst if "BEIRA RIO" in (x["fornecedor"] or "").upper()), None)
    return beira or (lst[0]["fornecedor"] if lst else None)


def resumo(fornecedor: str | None = None, hoje: date | None = None) -> dict:
    hoje = pd.Timestamp(hoje or date.today())
    P, I = carregar(fornecedor)
    if P.empty:
        return {"status": "sem_dados", "motivo": "Nenhum pedido do Omie. Configure a integração e sincronize em Dados › Omie."}
    ab = P[P["status"].isin(ABERTOS)].copy()
    ab_i = I[I["a_receber"] > 0]
    ab["a_receber"] = ab["id"].map(ab_i.groupby("pedido_id")["a_receber"].sum()).fillna(0)
    ab["valor_a_receber"] = ab["id"].map(ab_i.groupby("pedido_id")["valor_a_receber"].sum()).fillna(0)
    vencidos = ab[ab["previsao"] < hoje]
    prox7 = ab[(ab["previsao"] >= hoje) & (ab["previsao"] <= hoje + pd.Timedelta(days=7))]
    prox30 = ab[(ab["previsao"] >= hoje) & (ab["previsao"] <= hoje + pd.Timedelta(days=30))]

    # entregas previstas por semana (pedidos em aberto)
    sem = ab.copy()
    sem["semana"] = sem["previsao"].dt.to_period("W-SUN").dt.start_time
    g = sem.groupby("semana").agg(pares=("a_receber", "sum"), valor=("valor_a_receber", "sum"), pedidos=("id", "count")).reset_index()
    entregas = [{"semana": r.semana.strftime("%Y-%m-%d"), "rotulo": r.semana.strftime("%d/%m"),
                 "vencida": bool(r.semana + pd.Timedelta(days=6) < hoje),
                 "pares": f(r.pares, 0), "valor": f(r.valor), "pedidos": int(r.pedidos)} for r in g.itertuples()]

    # vencimentos das parcelas (todos os pedidos não cancelados)
    parc = []
    for r in P[~P["status"].isin(["cancelado", "encerrado"])].itertuples():
        for pc in json.loads(r.parcelas or "[]"):
            if pc.get("vencimento"):
                parc.append({"venc": pd.Timestamp(pc["vencimento"]), "valor": float(pc.get("valor") or 0)})
    Pc = pd.DataFrame(parc)
    fluxo = []
    if not Pc.empty:
        Pc = Pc[Pc["venc"] >= hoje.to_period("M").to_timestamp()]
        gm = Pc.groupby(Pc["venc"].dt.to_period("M"))["valor"].sum()
        fluxo = [{"mes": str(m), "rotulo": ind.mes_label(m.to_timestamp()), "valor": f(v)} for m, v in gm.items()]

    status = P.groupby("status").agg(pedidos=("id", "count"), pares=("pares", "sum"), valor=("valor_total", "sum"))
    preco_par = float(ab_i["valor_a_receber"].sum() / ab_i["a_receber"].sum()) if ab_i["a_receber"].sum() else None
    return {
        "status": "ok", "fornecedor": fornecedor, "hoje": hoje.strftime("%Y-%m-%d"),
        "abertos": {"pedidos": int(len(ab)), "pares": f(ab["a_receber"].sum(), 0), "valor": f(ab["valor_a_receber"].sum()),
                    "preco_medio_par": f(preco_par), "modelos": int(ab_i["modelo"].nunique()), "skus": int(ab_i["sku"].nunique())},
        "previsao_vencida": {"pedidos": int(len(vencidos)), "pares": f(vencidos["a_receber"].sum(), 0)},
        "proximos_7": {"pedidos": int(len(prox7)), "pares": f(prox7["a_receber"].sum(), 0)},
        "proximos_30": {"pedidos": int(len(prox30)), "pares": f(prox30["a_receber"].sum(), 0), "valor": f(prox30["valor_a_receber"].sum())},
        "por_status": [{"status": s, "rotulo": ROTULO_STATUS.get(s, s), "pedidos": int(r.pedidos), "pares": f(r.pares, 0),
                        "valor": f(r.valor)} for s, r in status.iterrows()],
        "entregas": entregas, "vencimentos": fluxo,
        "nota": "Status vem do filtro do Omie em que o pedido aparece. 'A receber' = quantidade pedida − recebida nos pedidos em aberto.",
    }


def lista(fornecedor=None, hoje=None) -> list:
    hoje = pd.Timestamp(hoje or date.today())
    P, I = carregar(fornecedor)
    if P.empty:
        return []
    ar = I.groupby("pedido_id").agg(a_receber=("a_receber", "sum"), modelos=("modelo", "nunique"))
    out = []
    for r in P.sort_values("previsao").itertuples():
        a = ar.loc[r.id] if r.id in ar.index else None
        out.append({
            "id": str(r.id), "numero": r.numero, "numero_fornecedor": r.numero_fornecedor, "fornecedor": r.fornecedor,
            "status": r.status, "status_rotulo": ROTULO_STATUS.get(r.status, r.status),
            "data_inclusao": r.data_inclusao.strftime("%Y-%m-%d") if pd.notna(r.data_inclusao) else None,
            "previsao": r.previsao.strftime("%Y-%m-%d") if pd.notna(r.previsao) else None,
            "previsao_vencida": bool(r.status in ABERTOS and pd.notna(r.previsao) and r.previsao < hoje),
            "pares": f(r.pares, 0), "pares_recebidos": f(r.pares_recebidos, 0),
            "a_receber": f(a["a_receber"], 0) if a is not None else 0, "modelos": int(a["modelos"]) if a is not None else 0,
            "valor_total": f(r.valor_total), "condicao": r.condicao,
        })
    return out


def detalhe(pedido_id: int) -> dict:
    P = pd.read_sql(f"select * from omie_pedidos where id = {int(pedido_id)}", db.engine)
    if P.empty:
        return {}
    r = P.iloc[0]
    I = pd.read_sql(f"select * from omie_itens where pedido_id = {int(pedido_id)}", db.engine)
    if not I.empty:
        I["modelo"] = [interpretar(s_, com_tamanho=False).modelo if s_ else m_ for s_, m_ in zip(I["sku"], I["modelo"])]
    grade = []
    for sku, g in I.groupby("sku"):
        tam = {str(t): f(q, 0) for t, q in zip(g["tamanho"], g["quantidade"])}
        grade.append({"sku": sku, "modelo": g["modelo"].iloc[0], "descricao": g["descricao"].iloc[0],
                      "tamanhos": tam, "pares": f(g["quantidade"].sum(), 0), "recebidos": f(g["quantidade_recebida"].sum(), 0),
                      "valor_unitario": f(g["valor_unitario"].median()), "valor_total": f(g["valor_total"].sum())})
    tams = sorted({t for x in grade for t in x["tamanhos"]}, key=lambda t: int(t) if str(t).isdigit() else 99)
    return {"id": str(r.id), "numero": r.numero, "numero_fornecedor": r.numero_fornecedor, "fornecedor": r.fornecedor,
            "status": r.status, "status_rotulo": ROTULO_STATUS.get(r.status, r.status), "etapa": r.etapa,
            "data_inclusao": str(r.data_inclusao), "previsao": str(r.previsao), "pares": f(r.pares, 0),
            "valor_total": f(r.valor_total), "frete": f(r.frete), "condicao": r.condicao, "observacao": r.observacao,
            "parcelas": json.loads(r.parcelas or "[]"), "tamanhos": tams,
            "grade": sorted(grade, key=lambda x: -x["pares"])}


def a_caminho_por_sku(fornecedor=None) -> pd.DataFrame:
    """Pares a receber por SKU (sem tamanho) e por SKU+tamanho, com a previsão mais próxima."""
    _, I = carregar(fornecedor)
    if I.empty:
        return pd.DataFrame(columns=["sku", "tamanho", "a_receber", "previsao"])
    I = I[I["a_receber"] > 0]
    return I.groupby(["sku", "tamanho"], dropna=False).agg(a_receber=("a_receber", "sum"), previsao=("previsao", "min")).reset_index()


def reposicao(d: ind.Dados, categoria="calcado", nivel="sku", fornecedor=None, hoje=None) -> dict:
    """Cruza estoque, demanda (3 meses) e pedidos em aberto.
    Cobertura com pedidos = (estoque + a receber) ÷ demanda diária."""
    hoje = pd.Timestamp(hoje or date.today())
    E = ind._filtrar_cat(ind.estoque_em(d), categoria)
    base = ind.meses_base_demanda(d)
    dem = ind.demanda_diaria(d, base, categoria)
    est = E.groupby("sku")["qtd"].sum() if not E.empty else pd.Series(dtype=float)
    ac = a_caminho_por_sku(fornecedor)
    acs = ac.groupby("sku").agg(a_receber=("a_receber", "sum"), previsao=("previsao", "min")) if not ac.empty else pd.DataFrame(columns=["a_receber", "previsao"])
    df = pd.concat([est.rename("estoque"), dem.rename("dem")], axis=1).join(acs, how="outer")
    df = df.fillna({"estoque": 0, "dem": 0, "a_receber": 0})
    df = df[(df["dem"] > 0) | (df["a_receber"] > 0)]
    df = df[~df.index.isin(d.externos)]
    if df.empty:
        return {"status": "sem_dados", "motivo": "Sem estoque, demanda ou pedidos para cruzar."}
    df.index.name = "sku"
    df = ind._chaves(df.reset_index())
    df = ind._filtrar_cat(df, categoria)
    k = f"k_{nivel}"
    g = df.groupby(k).agg(estoque=("estoque", "sum"), dem=("dem", "sum"), a_receber=("a_receber", "sum"),
                          previsao=("previsao", "min"), skus=("sku", "nunique"))
    g["cob"] = np.where(g["dem"] > 0, g["estoque"].clip(lower=0) / g["dem"], np.nan)
    g["cob_ped"] = np.where(g["dem"] > 0, (g["estoque"].clip(lower=0) + g["a_receber"]) / g["dem"], np.nan)
    # sem nenhum pedido com previsão a coluna vem sem tipo de data: converte antes de subtrair
    g["dias_ate"] = (pd.to_datetime(g["previsao"], errors="coerce") - hoje).dt.days

    def situacao(r):
        if r.dem <= 0:
            return "sem_demanda"           # comprando item sem venda recente
        if r.estoque <= 0:
            return "ruptura_com_pedido" if r.a_receber > 0 else "ruptura_sem_pedido"
        if r.cob < ind.COBERTURA_CRITICA:
            if r.a_receber <= 0:
                return "critico_sem_pedido"
            if pd.notna(r.dias_ate) and r.dias_ate > r.cob:
                return "pedido_chega_tarde"
            return "coberto"
        return "excesso" if r.cob_ped > 180 else "ok"
    g["situacao"] = [situacao(r) for r in g.itertuples()]
    rot = ind._rotulos(d, nivel)
    itens = [{"chave": i, "descricao": rot.get(i, ""), "estoque": f(r.estoque, 0), "demanda_mes": f(r.dem * 30, 0),
              "a_receber": f(r.a_receber, 0), "previsao": r.previsao.strftime("%Y-%m-%d") if pd.notna(r.previsao) else None,
              "cobertura": f(r.cob, 0), "cobertura_com_pedidos": f(r.cob_ped, 0), "situacao": r.situacao, "skus": int(r.skus)}
             for i, r in g.sort_values("dem", ascending=False).iterrows()]
    cont = g.groupby("situacao").agg(n=("dem", "size"), dem=("dem", "sum"), a_receber=("a_receber", "sum"))
    return {"status": "ok", "base": [ind.mes_label(base[0]), ind.mes_label(base[-1])],
            "contagem": {s: {"itens": int(r.n), "demanda_mes": f(r.dem * 30, 0), "a_receber": f(r.a_receber, 0)} for s, r in cont.iterrows()},
            "itens": itens,
            "nota": "Demanda = vendas em peças dos últimos 3 meses. Cobertura com pedidos = (estoque + pares a receber) ÷ demanda diária. "
                    "'Pedido chega tarde' = a previsão de entrega é posterior ao fim do estoque atual."}


def grade_com_pedidos(d: ind.Dados, fornecedor=None, limite=60) -> dict:
    """Grade quebrada + quantos pares dos tamanhos faltantes estão a caminho."""
    gq = ind.grade_quebrada(d, limite=1000)
    if gq.get("status") != "ok":
        return gq
    ac = a_caminho_por_sku(fornecedor)
    mapa = {(r.sku, str(r.tamanho)): (r.a_receber, r.previsao) for r in ac.itertuples()} if not ac.empty else {}
    for it in gq["itens"]:
        cam = [(t, mapa.get((it["sku"], t))) for t in it["tamanhos_zerados"]]
        it["a_caminho"] = {t: f(v[0], 0) for t, v in cam if v}
        it["tamanhos_sem_pedido"] = [t for t, v in cam if not v]
    gq["sem_reposicao"] = sum(1 for it in gq["itens"] if it["tamanhos_sem_pedido"])
    gq["itens"] = gq["itens"][:limite]
    return gq


def busca_sku(termo: str, fornecedor=None, hoje=None, limite: int = 300) -> dict:
    """Pedidos de compra que contêm SKUs com o termo buscado (trecho do código, sem diferenciar maiúsculas)."""
    hoje = pd.Timestamp(hoje or date.today())
    t = (termo or "").strip().upper()
    if len(t) < 2:
        return {"termo": termo, "itens": [], "total": 0, "skus": 0, "pedidos": 0, "a_receber": 0}
    _, I = carregar(fornecedor)
    if I.empty:
        return {"termo": termo, "itens": [], "total": 0, "skus": 0, "pedidos": 0, "a_receber": 0}
    I = I[I["sku"].astype(str).str.upper().str.contains(t, regex=False, na=False)]
    if I.empty:
        return {"termo": termo, "itens": [], "total": 0, "skus": 0, "pedidos": 0, "a_receber": 0}
    P = pd.read_sql("select id, numero_fornecedor, data_inclusao from omie_pedidos", db.engine).set_index("id")
    itens = []
    for (pid, sku), g in I.groupby(["pedido_id", "sku"]):
        r = g.iloc[0]
        tam = {str(tt): f(q, 0) for tt, q in zip(g["tamanho"], g["quantidade"]) if q}
        tams = sorted(tam, key=lambda x: int(x) if str(x).isdigit() else 99)
        prev = r["previsao"]
        pinfo = P.loc[pid] if pid in P.index else None
        itens.append({
            "pedido_id": str(pid), "numero": r["numero"], "fornecedor": r["fornecedor"],
            "numero_fornecedor": pinfo["numero_fornecedor"] if pinfo is not None else None,
            "data_inclusao": str(pinfo["data_inclusao"])[:10] if pinfo is not None and pinfo["data_inclusao"] else None,
            "status": r["status"], "status_rotulo": ROTULO_STATUS.get(r["status"], r["status"]),
            "previsao": prev.strftime("%Y-%m-%d") if pd.notna(prev) else None,
            "previsao_vencida": bool(r["status"] in ABERTOS and pd.notna(prev) and prev < hoje),
            "sku": sku, "modelo": r["modelo"], "descricao": r["descricao"],
            "pares": f(g["quantidade"].sum(), 0), "recebidos": f(g["quantidade_recebida"].sum(), 0),
            "a_receber": f(g["a_receber"].sum(), 0),
            "valor_unitario": f(g["valor_unitario"].median()), "valor_total": f(g["valor_total"].sum()),
            "grade": ", ".join(f"{x}: {int(tam[x])}" for x in tams),
        })
    itens.sort(key=lambda x: (x["previsao"] or "9999"), reverse=True)
    return {"termo": termo, "total": len(itens), "skus": int(I["sku"].nunique()), "pedidos": int(I["pedido_id"].nunique()),
            "a_receber": f(I["a_receber"].sum(), 0), "itens": itens[:limite]}
