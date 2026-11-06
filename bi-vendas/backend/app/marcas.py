"""Marcas do grupo Beira Rio: vendas (faturamento e unidades) e compras (notas) por marca.

A marca vem da descrição do produto nas vendas (ex.: "Sandália Vizzano ..."). As compras não
têm descrição, então herdam a marca do modelo. Modelos sem marca na descrição podem ser
marcados à mão (Compras › Marcas). Molekinho e Molekinha podem ser somadas.
"""
from __future__ import annotations

import json
import re

import pandas as pd
from sqlalchemy import delete, insert, select

from . import db
from . import indicadores as ind

# ordem importa: a primeira que aparecer na descrição vence ("Beira Rio" por último)
MARCAS = [("Vizzano", r"vizzano"), ("Modare", r"modare"), ("Moleca", r"moleca"), ("Molekinha", r"molekinha"),
          ("Molekinho", r"molekinho"), ("Actvitta", r"activ?tta|actvitta"), ("Beira Rio", r"beira\s*-?\s*rio")]
NOMES = [m for m, _ in MARCAS]
OUTRAS = "Sem marca identificada"
# Último recurso: o 1º dígito do código do modelo, conferido contra todas as marcas tiradas das descrições
# (1/3/6 Vizzano, 2 Molekinho ou Molekinha, 4/8/9 Beira Rio, 5 Moleca, 7 Modare)
PREFIXO = {"1": "Vizzano", "3": "Vizzano", "6": "Vizzano", "4": "Beira Rio", "8": "Beira Rio", "9": "Beira Rio",
           "5": "Moleca", "7": "Modare", "2": "__molek"}
MOLEK = "Molekinho/Molekinha"


def marca_do_texto(t) -> str | None:
    t = str(t or "").lower()
    for nome, pad in MARCAS:
        if re.search(pad, t):
            return nome
    return None


def manuais() -> dict:
    with db.engine.connect() as c:
        v = c.execute(select(db.configuracoes.c.valor).where(db.configuracoes.c.chave == "marcas_manual")).scalar()
    return json.loads(v) if v else {}


def definir_manual(modelo: str, marca: str | None) -> dict:
    m = manuais()
    if marca:
        if marca not in NOMES:
            raise ValueError(f"Marca inválida. Use: {', '.join(NOMES)}.")
        m[modelo] = marca
    else:
        m.pop(modelo, None)
    with db.engine.begin() as c:
        c.execute(delete(db.configuracoes).where(db.configuracoes.c.chave == "marcas_manual"))
        c.execute(insert(db.configuracoes).values(chave="marcas_manual", valor=json.dumps(m)))
    return m


def mapa(d) -> dict:
    """modelo -> marca (descrição das vendas e do cadastro; correções manuais por cima)."""
    out = {}
    V = d.V[d.V["categoria"] == "calcado"] if not d.V.empty else d.V
    if not V.empty:
        desc = V.dropna(subset=["descricao"]).groupby("k_modelo")["descricao"].agg(lambda x: x.mode().iat[0])
        out.update({k: m for k, m in desc.map(marca_do_texto).items() if m})
    if not d.produtos.empty:
        for sku, t in zip(d.produtos["sku"], d.produtos["descricao"]):
            p = ind.interpretar(str(sku), com_tamanho=False)
            if p.categoria == "calcado" and p.modelo not in out:
                m = marca_do_texto(t)
                if m:
                    out[p.modelo] = m
    # modelos ainda sem venda (recém-comprados): descrição dos itens dos pedidos de compra do Omie
    try:
        from . import pedidos as _ped
        _, I = _ped.carregar(None)
        if not I.empty and "descricao" in I:
            for mod, t in I.dropna(subset=["modelo"]).groupby("modelo")["descricao"].agg(lambda x: x.mode().iat[0] if x.notna().any() else "").items():
                if mod not in out:
                    mk = marca_do_texto(t)
                    if mk:
                        out[mod] = mk
    except Exception:  # noqa: BLE001
        pass
    out.update(manuais())
    return out


def marca_de(mp: dict, modelo, agrupar=False, deduzidas: set | None = None) -> str:
    m = mp.get(modelo)
    if m is None and modelo:
        # modelo comprado sem cabedal (ex.: 7208.101) herda a marca dos cabedais
        filhos = {v for k, v in mp.items() if str(k).startswith(str(modelo) + "-")}
        m = filhos.pop() if len(filhos) == 1 else None
    if m is None and modelo and re.match(r"^\d{4}\.", str(modelo)):
        p = PREFIXO.get(str(modelo)[0])
        if p == "__molek":
            p = MOLEK if agrupar else None
        if p and deduzidas is not None:
            deduzidas.add(modelo)
        m = p
    m = m or OUTRAS
    return MOLEK if agrupar and m in ("Molekinho", "Molekinha") else m


def relatorio(d, meses, agrupar=False, a_receber=None) -> dict:
    mp = mapa(d)
    deduzidas = set()
    ant = ind.periodo_anterior(d, meses)
    usa_dia = any(m in d.parciais for m in meses) or any(m in d.parciais for m in (ant or []))
    dias_p, dias_a = ind.dias_periodo(d, meses), (ind.dias_periodo(d, ant) if ant else 0)

    V = d.V[d.V["categoria"] == "calcado"].copy()
    V["marca"] = [marca_de(mp, k, agrupar, deduzidas) for k in V["k_modelo"]]
    Vp, Va = V[V["mes"].isin(meses)], (V[V["mes"].isin(ant)] if ant else V.iloc[0:0])
    C = d.C[d.C["modelo"].notna()].copy() if d.C is not None and not d.C.empty else pd.DataFrame(columns=["modelo", "data"])
    ini, fim = pd.Timestamp(meses[0]), pd.Timestamp(meses[-1]) + pd.offsets.MonthEnd(0)
    if not C.empty:
        C["marca"] = [marca_de(mp, k, agrupar, deduzidas) for k in C["modelo"]]
        C["qtd"] = pd.to_numeric(C["quantidade"], errors="coerce")
        C["valor"] = C["qtd"] * pd.to_numeric(C["preco_desconto"], errors="coerce").fillna(pd.to_numeric(C["valor_unitario"], errors="coerce"))
    Cp = C[(C["data"] >= ini) & (C["data"] <= fim)] if not C.empty else C
    E = ind._filtrar_cat(ind.estoque_em(d), "calcado")
    if not E.empty:
        E = E.assign(marca=[marca_de(mp, k, agrupar, deduzidas) for k in E["k_modelo"]])
    rec = {}
    for k, v in (a_receber or {}).items():
        mk = marca_de(mp, k, agrupar, deduzidas)
        rec[mk] = rec.get(mk, 0) + float(v or 0)

    def var(a, b):
        if usa_dia:
            a, b = (a / dias_p if dias_p else 0), (b / dias_a if dias_a else 0)
        return ind._pct(a, b) if b else None

    ordem = [m for m in NOMES if not (agrupar and m in ("Molekinho", "Molekinha"))]
    if agrupar:
        ordem.insert(ordem.index("Actvitta"), MOLEK)
    ordem.append(OUTRAS)
    tot_fat = float(Vp["fat"].sum()) or 1
    tot_un = float(Vp["un"].sum()) or 1
    tot_comp = float(Cp["qtd"].sum()) if not Cp.empty else 0
    linhas = []
    for m in ordem:
        v, va = Vp[Vp["marca"] == m], Va[Va["marca"] == m]
        c = Cp[Cp["marca"] == m] if not Cp.empty else Cp
        fat, un = float(v["fat"].sum()), float(v["un"].sum())
        cp = float(c["qtd"].sum()) if not c.empty else 0.0
        cv = float(c["valor"].sum()) if not c.empty else 0.0
        est = float(E.loc[E["marca"] == m, "qtd"].sum()) if not E.empty else 0.0
        if not (fat or un or cp or est or rec.get(m)):
            continue
        linhas.append({
            "marca": m, "faturamento": ind._f(fat), "unidades": ind._f(un, 0),
            "pct_faturamento": ind._f(fat / tot_fat * 100, 1), "pct_unidades": ind._f(un / tot_un * 100, 1),
            "preco_medio": ind._f(fat / un) if un else None,
            "var_faturamento": var(fat, float(va["fat"].sum())), "var_unidades": var(un, float(va["un"].sum())),
            "modelos_vendidos": int(v.loc[v["un"] > 0, "k_modelo"].nunique()),
            "comprado_pares": ind._f(cp, 0), "comprado_valor": ind._f(cv),
            "pct_comprado": ind._f(cp / tot_comp * 100, 1) if tot_comp else None,
            "custo_medio": ind._f(cv / cp) if cp else None,
            "notas": int(c["nota_chave"].nunique()) if not c.empty else 0,
            "pe_pct": ind._f(float(c.loc[c["modalidade"] == "PE", "qtd"].sum()) / cp * 100, 0) if cp else None,
            "vendido_sobre_comprado": ind._f(un / cp * 100, 0) if cp else None,
            "estoque": ind._f(est, 0), "a_receber": ind._f(rec.get(m, 0), 0),
            "cobertura": ind._f(est / (un / dias_p), 0) if un and dias_p else None,
        })
    # série mensal (12 meses): vendas e compras por marca
    ms = d.meses[-12:]
    serie = []
    for mm in ms:
        x = V[V["mes"] == mm]
        y = C[(C["data"] >= mm) & (C["data"] <= mm + pd.offsets.MonthEnd(0))] if not C.empty else C
        linha = {"mes": mm.strftime("%Y-%m"), "rotulo": ind.mes_label(mm), "parcial": mm in d.parciais}
        for m in ordem:
            linha[f"v_{m}"] = ind._f(x.loc[x["marca"] == m, "un"].sum(), 0)
            linha[f"c_{m}"] = ind._f(y.loc[y["marca"] == m, "qtd"].sum(), 0) if not y.empty else 0
        serie.append(linha)
    # top modelos por marca no período
    rot = ind._rotulos(d, "modelo")
    top = {}
    g = Vp.groupby(["marca", "k_modelo"]).agg(fat=("fat", "sum"), un=("un", "sum")).reset_index()
    for m, h in g.groupby("marca"):
        top[m] = [{"modelo": r.k_modelo, "descricao": rot.get(r.k_modelo, ""), "faturamento": ind._f(r.fat), "unidades": ind._f(r.un, 0)}
                  for r in h.sort_values("fat", ascending=False).head(10).itertuples()]
    # modelos sem marca (vendidos ou comprados), para corrigir à mão
    sem = sorted({k for k in V.loc[V["marca"] == OUTRAS, "k_modelo"]} | ({k for k in C.loc[C["marca"] == OUTRAS, "modelo"]} if not C.empty else set()))
    rotulo_p = ind.mes_label(meses[0]) + ("" if len(meses) == 1 else f" a {ind.mes_label(meses[-1])}")
    rotulo_a = (ind.mes_label(ant[0]) + ("" if len(ant) == 1 else f" a {ind.mes_label(ant[-1])}")) if ant else None
    return {"periodo": rotulo_p, "anterior": rotulo_a, "base_comparacao": "média por dia" if usa_dia else "total",
            "agrupado": agrupar, "marcas": linhas, "ordem": [l["marca"] for l in linhas], "serie": serie, "top": top,
            "sem_marca": [{"modelo": k, "descricao": rot.get(k, "")} for k in sem][:200], "nomes": NOMES,
            "deduzidas": sorted(deduzidas)[:300], "n_deduzidas": len(deduzidas),
            "totais": {"faturamento": ind._f(float(Vp["fat"].sum())), "unidades": ind._f(float(Vp["un"].sum()), 0),
                       "comprado_pares": ind._f(tot_comp, 0), "comprado_valor": ind._f(float(Cp["valor"].sum()) if not Cp.empty else 0)},
            "nota": "Marca pela descrição do produto nas vendas; compras herdam a marca do modelo. Compras = notas de entrada "
                    "(planilhas e Qive) emitidas no período; pares sem quantidade na nota não entram."}
