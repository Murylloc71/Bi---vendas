"""Calendário de compras: qual modelo foi comprado em cada mês (sem preço).

Junta as planilhas de compras (e o Qive) com os itens do relatório de notas (compras_itens);
a mesma nota vinda das duas fontes conta uma vez (mesma data e mesmo valor total).
Medida: em quantas notas o modelo apareceu no mês (o relatório não traz quantidade).
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import select

from . import db
from . import indicadores as ind
from .importadores.itens_compra import traducao_ean
from .produto import interpretar

SEM_SKU = "EAN não identificado"


def _base(d) -> pd.DataFrame:
    """Linhas de compra (data, nota, ean, sku_original, modelo) das duas fontes, sem duplicar nota."""
    cols = ["data", "nota", "fornecedor", "ean", "sku_original", "valor_nota", "origem"]
    C = d.C if d.C is not None and not d.C.empty else pd.DataFrame(columns=["data", "nota_chave", "numero_nota", "fornecedor", "ean", "sku_original", "valor_nota"])
    a = pd.DataFrame({"data": pd.to_datetime(C["data"]), "nota": C["numero_nota"].fillna(C["nota_chave"]) if "numero_nota" in C else C["nota_chave"],
                      "fornecedor": C["fornecedor"], "ean": C["ean"], "sku_original": C["sku_original"],
                      "valor_nota": C["valor_nota"], "origem": "compras"}) if not C.empty else pd.DataFrame(columns=cols)
    I = pd.read_sql(select(db.compras_itens), db.engine)
    if not I.empty:
        with db.engine.connect() as c:
            tr = traducao_ean(c)
        Cb = ind.dados_base().C
        ja = set(pd.to_datetime(Cb["data"]).dt.strftime("%Y-%m-%d") + "|" + Cb["valor_nota"].round(2).astype(str)) if Cb is not None and not Cb.empty else set()
        I["data"] = pd.to_datetime(I["data"])
        k = I["data"].dt.strftime("%Y-%m-%d") + "|" + I["valor_nota"].round(2).astype(str)
        I = I[~k.isin(ja)]
        b = pd.DataFrame({"data": I["data"], "nota": I["numero_nota"], "fornecedor": I["fornecedor"], "ean": I["ean"],
                          "sku_original": I["ean"].map(tr), "valor_nota": I["valor_nota"], "origem": "itens"})
        a = pd.concat([a, b], ignore_index=True)
    if a.empty:
        return a
    cache = {}

    def mod(s):
        if not isinstance(s, str) or not s or s == "0":
            return (SEM_SKU, None)
        if s not in cache:
            p = interpretar(s, com_tamanho="auto")
            cache[s] = (p.modelo, p.sku) if p.categoria == "calcado" else (s, s)
        return cache[s]
    ms = [mod(s) for s in a["sku_original"]]
    a["modelo"] = [m for m, _ in ms]
    a["sku"] = [x for _, x in ms]
    # filtros globais (produtos em linha, curva ABC, SKUs excluídos)
    from . import abc as _abc
    from . import linha as _linha
    if _linha.MODO.get():
        a = a[_linha.mascara(a["modelo"], _linha.MODO.get()) | (a["modelo"] == SEM_SKU)]
    if _abc.MODO.get():
        a = a[_abc.mascara(a["modelo"], _abc.MODO.get(), _abc.classificar(ind.dados_base())["classes"])]
    if d.excluidos:
        a = a[~a["sku"].isin(d.excluidos)]
    return a


def calendario(d, inicio=None, fim=None, agrupar=False) -> dict:
    from . import marcas as _marcas
    a = _base(d)
    if a.empty:
        return {"status": "sem_dados", "motivo": "Nenhuma compra importada. Importe o relatório de notas em Dados › Importar arquivos."}
    a["mes"] = a["data"].dt.to_period("M").astype(str)
    meses_disp = sorted(a["mes"].unique())
    ini = inicio if inicio in meses_disp else meses_disp[max(0, len(meses_disp) - 12)]
    fim_ = fim if fim in meses_disp else meses_disp[-1]
    if ini > fim_:
        ini, fim_ = fim_, ini
    meses = [m for m in meses_disp if ini <= m <= fim_]
    primeira_geral = a.groupby("modelo")["data"].min()
    p = a[a["mes"].isin(meses)].copy()
    mp = _marcas.mapa(d)
    p["marca"] = [_marcas.marca_de(mp, k, agrupar) if k != SEM_SKU else SEM_SKU for k in p["modelo"]]
    p["nota_id"] = p["nota"].astype(str) + "|" + p["data"].dt.strftime("%Y-%m-%d")
    # resumo por mês
    resumo = []
    for m in meses:
        x = p[p["mes"] == m]
        # no 1º mês com dados não dá para saber o que é novo (não há histórico antes)
        novos = [] if m == meses_disp[0] else [k for k in x["modelo"].unique() if k != SEM_SKU and primeira_geral.get(k) is not None and primeira_geral[k].strftime("%Y-%m") == m]
        marcas = x[x["modelo"] != SEM_SKU].groupby("marca")["modelo"].nunique().to_dict()
        resumo.append({"mes": m, "rotulo": ind.mes_label(pd.Timestamp(m + "-01")), "notas": int(x["nota_id"].nunique()),
                       "modelos": int(x.loc[x["modelo"] != SEM_SKU, "modelo"].nunique()), "skus": int(x["sku"].nunique()),
                       "itens": len(x), "modelos_novos": None if m == meses_disp[0] else len(novos), "modelos_por_marca": {k: int(v) for k, v in marcas.items()}})
    # por modelo
    hoje = pd.Timestamp(date.today())
    est = ind._estoque_por_chave(d, "todos", "modelo")
    est = est["est"] if "est" in est else pd.Series(dtype=float)
    base3 = ind.meses_base_demanda(d)
    vend = d.V[d.V["mes"].isin(base3)].groupby("k_modelo")["un"].sum() if base3 else pd.Series(dtype=float)
    try:
        from . import pedidos as _ped
        _, Ip = _ped.carregar(None)
        rec = Ip.groupby("modelo")["a_receber"].sum() if not Ip.empty else pd.Series(dtype=float)
    except Exception:  # noqa: BLE001
        rec = pd.Series(dtype=float)
    rot = ind._rotulos(d, "modelo")
    ult_geral = a.groupby("modelo")["data"].max()
    itens = []
    for k, g in p.groupby("modelo"):
        por_mes = g.groupby("mes")["nota_id"].nunique().to_dict()
        ult = ult_geral.get(k)
        prim = primeira_geral.get(k)
        dias = int((hoje - ult).days) if ult is not None else None
        ve = float(vend.get(k, 0) or 0)
        pm = prim.strftime("%Y-%m") if prim is not None else None
        status = ("novo" if pm and pm >= meses[0] and pm > meses_disp[0] else
                  "sem_recompra" if dias is not None and dias > 60 and ve > 0 else "recorrente")
        itens.append({"modelo": k, "descricao": rot.get(k, "") if k != SEM_SKU else "", "marca": g["marca"].iat[0],
                      "meses": {m: int(v) for m, v in por_mes.items()}, "notas": int(g["nota_id"].nunique()),
                      "meses_com_compra": len(por_mes), "skus": int(g["sku"].nunique()),
                      "primeira_compra": prim.strftime("%Y-%m-%d") if prim is not None else None,
                      "ultima_compra": ult.strftime("%Y-%m-%d") if ult is not None else None, "dias_desde_ultima": dias,
                      "vendas_3m": ind._f(ve, 0), "estoque": ind._f(est.get(k, 0), 0), "a_receber": ind._f(rec.get(k, 0), 0),
                      "status": status})
    itens.sort(key=lambda x: (x["modelo"] == SEM_SKU, -x["notas"], x["modelo"]))
    sem = p[p["modelo"] == SEM_SKU]
    return {"status": "ok", "meses_disponiveis": meses_disp, "meses": meses,
            "rotulos": {m: ind.mes_label(pd.Timestamp(m + "-01")) for m in meses}, "resumo": resumo, "itens": itens,
            "marcas": sorted({i["marca"] for i in itens if i["marca"] != SEM_SKU}),
            "totais": {"notas": int(p["nota_id"].nunique()), "modelos": int(p.loc[p["modelo"] != SEM_SKU, "modelo"].nunique()),
                       "skus": int(p["sku"].nunique()), "itens": len(p),
                       "novos": sum(1 for i in itens if i["status"] == "novo"),
                       "sem_recompra": sum(1 for i in itens if i["status"] == "sem_recompra")},
            "sem_sku": {"itens": len(sem), "eans": sorted(sem["ean"].dropna().unique().tolist())[:40]},
            "desde": meses_disp[0],
            "nota": "Cada número é em quantas notas o modelo apareceu no mês (o relatório não traz quantidade). "
                    "“Novo”: primeira compra dentro do período (a partir do 2º mês com dados). "
                    "“Sem recompra”: vendeu nos últimos 3 meses e não é comprado há mais de 60 dias."}
