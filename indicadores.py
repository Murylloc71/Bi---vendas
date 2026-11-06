"""Motor de indicadores. Todas as fórmulas do BI ficam aqui.

Princípios
* Valores acumuláveis (unidades, faturamento, pares, estoque) são somados.
* Razões (preço médio, cobertura, participação) são SEMPRE recalculadas a partir das
  somas do nível escolhido — nunca média de médias.
* Quando um indicador não tem base de dados suficiente, retorna status 'sem_dados'
  com o motivo, em vez de um número.
"""
from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import func, select

from . import db
from . import produto as _produto
from .produto import SEM_CABEDAL, interpretar

NIVEIS = ("modelo", "cabedal", "sku")
CATEGORIAS = ("todos", "calcado", "outro")
COBERTURA_CRITICA = 15     # dias
COBERTURA_EXCESSO = 120    # dias
JANELA_DEMANDA_MESES = 3   # meses usados como base de demanda para estoque/perdas
CARRY_ESTOQUE_DIAS = 7     # validade de uma foto de estoque para dias sem importação


# --------------------------------------------------------------------------- carga
def _chaves(df: pd.DataFrame, col_sku="sku"):
    """Adiciona categoria, modelo, cabedal e chaves de nível a partir do SKU canônico."""
    cache = {}
    cats, mods, cabs, cors = [], [], [], []
    for s in df[col_sku].astype(str):
        if s not in cache:
            p = interpretar(s, com_tamanho=False)
            cache[s] = (p.categoria, p.modelo, p.chave_cabedal, p.cor)
        c = cache[s]
        cats.append(c[0]); mods.append(c[1]); cabs.append(c[2]); cors.append(c[3])
    df["categoria"] = cats
    df["k_modelo"] = mods
    df["k_cabedal"] = cabs
    df["k_sku"] = df[col_sku].astype(str)
    df["cor"] = cors
    return df


@dataclass
class Dados:
    versao: tuple
    V: pd.DataFrame        # vendas mensais por SKU de anúncio
    P: pd.DataFrame        # demanda em peças (visão compra)
    E: pd.DataFrame        # itens de estoque de todas as fotos
    C: pd.DataFrame        # compras
    produtos: pd.DataFrame
    meses: list            # meses disponíveis (Timestamp)
    dias_mes: dict         # mês -> dias cobertos
    parciais: set
    externos: set          # SKUs com estoque fora dos depósitos importados (ex.: Full)
    L: pd.DataFrame = None  # vendas lançadas por dia (sku, canal, dia, un, fat, fat_estimado)
    excluidos: set = None   # SKUs tirados do BI pelo usuário
    semanal_desde: object = None  # mês a partir do qual as vendas vêm só das planilhas semanais


_cache: dict = {}
_lock = threading.Lock()


def versao_atual():
    with db.engine.connect() as c:
        r = c.execute(select(func.count(db.importacoes.c.id), func.max(db.importacoes.c.id))).first()
        d = c.execute(select(func.count()).select_from(db.importacoes).where(db.importacoes.c.status != "ok")).scalar()
        v = c.execute(select(func.count()).select_from(db.vinculos)).scalar()
        cfg = c.execute(select(db.configuracoes.c.valor).where(db.configuracoes.c.chave == "estoque_externo")).scalar()
        mpc = c.execute(select(db.configuracoes.c.valor).where(db.configuracoes.c.chave == "modelos_por_cabedal")).scalar()
        sem = c.execute(select(db.configuracoes.c.valor).where(db.configuracoes.c.chave == "vendas_semanais_desde")).scalar()
        try:
            exc = tuple(c.execute(select(func.count(), func.max(db.skus_excluidos.c.excluido_em))).first())
        except Exception:  # noqa: BLE001 - tabela ainda não criada
            exc = (0, None)
    carregar_modelos_por_cabedal(mpc)
    return (r[0], r[1], d, v, cfg, mpc, sem, str(exc))


def carregar_modelos_por_cabedal(valor=None, ler=False):
    """Aplica a lista de modelos separados por cabedal salva no banco (ou o padrão)."""
    if ler:
        with db.engine.connect() as c:
            valor = c.execute(select(db.configuracoes.c.valor).where(db.configuracoes.c.chave == "modelos_por_cabedal")).scalar()
    _produto.definir_modelos_por_cabedal(json.loads(valor) if valor else _produto.MODELOS_POR_CABEDAL_PADRAO)


def dados_base() -> Dados:
    """Todos os dados, sem o filtro de produtos em linha."""
    ver = versao_atual()
    with _lock:
        if _cache.get("ver") == ver:
            return _cache["dados"]
        d = _carregar(ver)
        _cache["ver"], _cache["dados"] = ver, d
        return d


def dados() -> Dados:
    """Dados com os filtros globais da requisição atual: produtos em linha e curva ABC."""
    from . import abc as _abc
    from . import linha as _linha
    base = dados_base()
    modo, curva = _linha.MODO.get(), _abc.MODO.get()
    if not modo and not curva:
        return base
    chave = (base.versao, modo, _linha.versao() if modo else None, curva, json.dumps(_abc.config(), sort_keys=True) if curva else None)
    with _lock:
        if _cache.get("f_chave") == chave:
            return _cache["f_dados"]
    d = _linha.filtrar_dados(base, modo) if modo else base
    if curva:
        d = _abc.filtrar_dados(d, base, curva)
    with _lock:
        _cache["f_chave"], _cache["f_dados"] = chave, d
    return d


def _carregar(ver) -> Dados:
    eng = db.engine
    produtos = pd.read_sql(select(db.produtos), eng)
    V = pd.read_sql(
        select(db.vendas_mensais.c.mes, db.vendas_mensais.c.unidades.label("un"),
               db.vendas_mensais.c.unidades_ml.label("ml"), db.vendas_mensais.c.unidades_shopee.label("sh"),
               db.vendas_mensais.c.faturamento.label("fat"), db.vendas_mensais.c.parcial,
               db.vendas_mensais.c.dias_cobertos.label("dias"), db.vendas_mensais.c.curva,
               db.produtos.c.sku, db.produtos.c.descricao)
        .select_from(db.vendas_mensais.join(db.produtos)), eng)
    P = pd.read_sql(select(db.demanda_pecas.c.sku, db.demanda_pecas.c.mes, db.demanda_pecas.c.unidades.label("un"),
                           db.demanda_pecas.c.parcial, db.demanda_pecas.c.dias_cobertos.label("dias")), eng)
    E = pd.read_sql(
        select(db.estoque_snapshots.c.deposito, db.estoque_snapshots.c.data, db.estoque_itens.c.codigo,
               db.estoque_itens.c.sku, db.estoque_itens.c.tamanho, db.estoque_itens.c.quantidade.label("qtd"),
               db.estoque_itens.c.vinculo)
        .select_from(db.estoque_itens.join(db.estoque_snapshots)), eng)
    C = pd.read_sql(select(db.compras), eng)
    if not C.empty and C["linha_chave"].str.startswith("QIVE|").any():
        # a mesma nota vinda da API do Qive e de uma planilha: fica a da API (mesma data e valor total da nota)
        api = C["linha_chave"].str.startswith("QIVE|")
        k = C["data"].astype(str) + "|" + C["valor_nota"].round(2).astype(str)
        C = C[api | ~k.isin(set(k[api]))]

    for df in (V, P):
        df["mes"] = pd.to_datetime(df["mes"])
        for c in ("un", "fat", "ml", "sh"):
            if c in df:
                df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    V["fat"] = V["fat"].fillna(0.0)
    V["un"] = V["un"].fillna(0.0)
    # A partir do mês configurado, as vendas vêm só das planilhas semanais/diárias (o relatório
    # mensal desses meses é ignorado, sem ser apagado: desligando a opção ele volta a valer).
    semanal = pd.Timestamp(ver[6] + "-01") if len(ver) > 6 and ver[6] and ver[6] != "desligado" else None
    if semanal is not None:
        V = V[V["mes"] < semanal]
        P = P[P["mes"] < semanal]
    # SKUs excluídos pelo usuário
    try:
        excluidos = set(pd.read_sql(select(db.skus_excluidos.c.sku), eng)["sku"])
    except Exception:  # noqa: BLE001
        excluidos = set()
    if excluidos:
        V = V[~V["sku"].isin(excluidos)]
        P = P[~P["sku"].isin(excluidos)]
    V, P, L = _somar_lancamentos(eng, V, P, produtos, excluidos)
    if P.empty and not V.empty:      # sem visão compra: usa as unidades do anúncio
        P = V[["sku", "mes", "un", "parcial", "dias"]].copy()
    V = _chaves(V) if not V.empty else V.assign(categoria=[], k_modelo=[], k_cabedal=[], k_sku=[], cor=[])
    P = _chaves(P) if not P.empty else P.assign(categoria=[], k_modelo=[], k_cabedal=[], k_sku=[], cor=[])
    if not E.empty:
        E["data"] = pd.to_datetime(E["data"])
        E["sku"] = E["sku"].fillna(E["codigo"].str.upper())
        if excluidos:
            E = E[~E["sku"].isin(excluidos)]
        E = _chaves(E)
    else:
        E = E.assign(categoria=[], k_modelo=[], k_cabedal=[], k_sku=[], cor=[])
    if not C.empty:
        C["data"] = pd.to_datetime(C["data"])
        # modelo recalculado pela regra atual (ex.: modelos separados por cabedal)
        if "sku_original" in C:
            _m = {}
            for s_ in C["sku_original"].dropna().unique():
                p_ = interpretar(s_, com_tamanho=False)
                _m[s_] = p_.modelo if p_.categoria == "calcado" else None
            novo = C["sku_original"].map(_m)
            C["modelo"] = novo.where(C["sku_original"].notna(), C["modelo"])
        if excluidos and "sku" in C:
            C = C[~C["sku"].isin(excluidos)]
        C = _referencia_programado(C)

    meses = sorted(set(V["mes"]) | set(P["mes"]))
    dias_mes, parciais = {}, set()
    for m in meses:
        sub = V[V["mes"] == m]
        if sub.empty:
            sub = P[P["mes"] == m]
        parc = bool(sub["parcial"].fillna(False).any())
        d = int(sub["dias"].max()) if sub["dias"].notna().any() else pd.Timestamp(m).days_in_month
        dias_mes[m] = d
        if parc:
            parciais.add(m)
    externos = set(json.loads(ver[4])) if ver[4] else set()
    if L is not None and not L.empty:
        L = _chaves(L)
    return Dados(ver, V, P, E, C, produtos, meses, dias_mes, parciais, externos, L, excluidos, semanal)


def _somar_lancamentos(eng, V: pd.DataFrame, P: pd.DataFrame, produtos: pd.DataFrame, excluidos=frozenset()):
    """Soma as vendas lançadas por período (Importar › vendas por período) às vendas mensais.

    Só entram os dias que o relatório mensal ainda não cobre (o relatório cobre do dia 1 até
    `dias_cobertos` de cada mês). O período de cada lançamento é dividido igualmente pelos dias.
    O faturamento vem do ticket médio da planilha; sem ele, é estimado pelo preço médio histórico
    do SKU (ou do modelo)."""
    vazio = pd.DataFrame(columns=["sku", "canal", "conta", "dia", "un", "fat", "fat_estimado"])
    try:
        L = pd.read_sql(select(db.vendas_lancamentos), eng)
    except Exception:          # banco antigo sem a tabela
        return V, P, vazio
    if excluidos:
        L = L[~L["sku"].isin(excluidos)]
    if L.empty:
        return V, P, vazio
    # cada lançamento vira uma linha por dia do período (vetorizado)
    ini = pd.to_datetime(L["data_inicio"]).values.astype("datetime64[D]")
    fim = pd.to_datetime(L["data_fim"]).values.astype("datetime64[D]")
    nd = (fim - ini).astype(int) + 1
    rep = np.repeat(np.arange(len(L)), nd)
    desloc = np.arange(len(rep)) - np.repeat(np.cumsum(nd) - nd, nd)
    fat = pd.to_numeric(L["faturamento"], errors="coerce") if "faturamento" in L else pd.Series(np.nan, index=L.index)
    somar = L["somar_sempre"].fillna(False).astype(bool) if "somar_sempre" in L else pd.Series(False, index=L.index)
    conta = L["conta"].fillna("") if "conta" in L else pd.Series("", index=L.index)
    D = pd.DataFrame({
        "sku": L["sku"].values[rep], "canal": L["canal"].values[rep], "conta": conta.values[rep],
        "dia": pd.to_datetime(ini[rep] + desloc.astype("timedelta64[D]")),
        "un": (L["unidades"].astype(float).values / nd)[rep],
        "fat_inf": (fat.values / nd)[rep], "somar": somar.values[rep]})
    D["mes"] = D["dia"].dt.to_period("M").dt.to_timestamp()
    cob = {}
    if not V.empty:
        dm = V.copy()
        dm["dias"] = pd.to_numeric(dm["dias"], errors="coerce")
        cob = dm.groupby("mes")["dias"].max().to_dict()
        cob = {m: (int(v) if pd.notna(v) else pd.Timestamp(m).days_in_month) for m, v in cob.items()}
    lim = D["mes"].map(cob)
    D["coberto"] = lim.notna() & (D["dia"].dt.day <= lim.fillna(0))
    Dtodos = D
    D = D[~D["coberto"] | D["somar"]]

    # preço médio por SKU e por modelo, para estimar o faturamento dos dias lançados
    preco_sku, preco_mod = {}, {}
    if not V.empty:
        H = V[(V["fat"] > 0) & (V["un"] > 0)]
        g = H.groupby("sku")[["fat", "un"]].sum()
        preco_sku = (g["fat"] / g["un"]).to_dict()
        H = H.assign(_mod=[interpretar(x, com_tamanho=False).modelo for x in H["sku"]])
        g = H.groupby("_mod")[["fat", "un"]].sum()
        preco_mod = (g["fat"] / g["un"]).to_dict()

    # vendas por dia (todas as lançadas, com faturamento informado ou estimado) para os gráficos diários
    def _preco(sku):
        return preco_sku.get(sku) or preco_mod.get(interpretar(sku, com_tamanho=False).modelo)
    _pc = {s_: _preco(s_) for s_ in Dtodos["sku"].unique()}
    Ldia = Dtodos[["sku", "canal", "conta", "dia", "un"]].copy()
    est = Dtodos["un"] * Dtodos["sku"].map(_pc).astype(float)
    Ldia["fat"] = Dtodos["fat_inf"].where(Dtodos["fat_inf"].notna(), est).fillna(0.0)
    Ldia["fat_estimado"] = Dtodos["fat_inf"].isna()
    if D.empty:
        return V, P, Ldia
    extra_dias = D[~D["coberto"]].groupby("mes")["dia"].nunique()
    novos_dias = {m: cob.get(m, 0) + int(n) for m, n in extra_dias.items()}
    # faturamento informado (ticket médio) e unidades que ficaram sem ticket
    D = D.assign(ml=D["un"].where(D["canal"] == "ml", 0.0), sh=D["un"].where(D["canal"] == "shopee", 0.0),
                 un_sem=D["un"].where(D["fat_inf"].isna(), 0.0))
    A = D.groupby(["sku", "mes"]).agg(un=("un", "sum"), ml=("ml", "sum"), sh=("sh", "sum"),
                                      fat_inf=("fat_inf", lambda x: x.sum(min_count=1)), un_sem=("un_sem", "sum")).reset_index()
    desc = dict(zip(produtos["sku"], produtos["descricao"])) if not produtos.empty else {}

    V = V.copy()
    idx = {(s, m): i for i, (s, m) in enumerate(zip(V["sku"], V["mes"]))} if not V.empty else {}
    novas = []
    for r in A.itertuples():
        pr = preco_sku.get(r.sku) or preco_mod.get(interpretar(r.sku, com_tamanho=False).modelo)
        fat = (0.0 if pd.isna(r.fat_inf) else r.fat_inf) + (r.un_sem * pr if (pr and r.un_sem) else 0.0)
        i = idx.get((r.sku, r.mes))
        if i is not None:
            j = V.index[i]
            V.at[j, "un"] = (V.at[j, "un"] or 0) + r.un
            V.at[j, "fat"] = (V.at[j, "fat"] or 0) + fat
            if r.ml:
                V.at[j, "ml"] = (0 if pd.isna(V.at[j, "ml"]) else V.at[j, "ml"]) + r.ml
            if r.sh:
                V.at[j, "sh"] = (0 if pd.isna(V.at[j, "sh"]) else V.at[j, "sh"]) + r.sh
        else:
            novas.append({"mes": r.mes, "un": r.un, "ml": r.ml or None, "sh": r.sh or None, "fat": fat,
                          "parcial": True, "dias": None, "curva": None, "sku": r.sku, "descricao": desc.get(r.sku, "")})
    if novas:
        V = pd.concat([V, pd.DataFrame(novas)], ignore_index=True)
    for m, n in novos_dias.items():
        sel = V["mes"] == m
        V.loc[sel, "dias"] = n
        V.loc[sel, "parcial"] = n < pd.Timestamp(m).days_in_month

    if not P.empty:
        P = P.copy()
        pidx = {(s, m): i for i, (s, m) in enumerate(zip(P["sku"], P["mes"]))}
        novasp = []
        for r in A.itertuples():
            i = pidx.get((r.sku, r.mes))
            if i is not None:
                j = P.index[i]
                P.at[j, "un"] = (P.at[j, "un"] or 0) + r.un
            else:
                novasp.append({"sku": r.sku, "mes": r.mes, "un": r.un, "parcial": True, "dias": None})
        if novasp:
            P = pd.concat([P, pd.DataFrame(novasp)], ignore_index=True)
        for m, n in novos_dias.items():
            sel = P["mes"] == m
            P.loc[sel, "dias"] = n
            P.loc[sel, "parcial"] = n < pd.Timestamp(m).days_in_month
    return V, P, Ldia


def _referencia_programado(C: pd.DataFrame) -> pd.DataFrame:
    """Para cada linha PE, o preço líquido do programado do MESMO modelo na compra
    programada mais próxima no tempo (empate: a anterior). Sem programado -> sem referência."""
    C = C.copy()
    C["ref"] = np.nan
    C["ref_data"] = pd.NaT
    prog = (C[(C["modalidade"] == "PROG") & C["modelo"].notna()]
            .groupby(["modelo", "data"])["preco_desconto"].median().reset_index())
    por_modelo = {m: g.sort_values("data") for m, g in prog.groupby("modelo")}
    idx_pe = C.index[(C["modalidade"] == "PE") & C["modelo"].notna()]
    for i in idx_pe:
        g = por_modelo.get(C.at[i, "modelo"])
        if g is None or g.empty:
            continue
        dif = (g["data"] - C.at[i, "data"]).abs()
        j = dif.values.argmin()  # primeiro mínimo = mais antigo em empate
        C.at[i, "ref"] = g["preco_desconto"].iloc[j]
        C.at[i, "ref_data"] = g["data"].iloc[j]
    return C


# --------------------------------------------------------------------------- utilidades
def _f(x, nd=2):
    if x is None:
        return None
    try:
        if isinstance(x, (float, np.floating)) and (math.isnan(x) or math.isinf(x)):
            return None
    except TypeError:
        pass
    return round(float(x), nd)


def _pct(a, b):
    if a is None or b in (None, 0) or (isinstance(b, float) and math.isnan(b)):
        return None
    return _f((a - b) / b * 100, 1)


def _filtrar_cat(df, categoria):
    if categoria in (None, "todos") or df.empty:
        return df
    return df[df["categoria"] == categoria]


def mes_label(m) -> str:
    nomes = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    m = pd.Timestamp(m)
    return f"{nomes[m.month - 1]}/{str(m.year)[2:]}"


def resolver_periodo(d: Dados, inicio: str | None, fim: str | None) -> list:
    if not d.meses:
        return []
    ini = pd.Timestamp(inicio + "-01") if inicio else d.meses[0]
    fi = pd.Timestamp(fim + "-01") if fim else d.meses[-1]
    if ini > fi:
        ini, fi = fi, ini
    return [m for m in d.meses if ini <= m <= fi]


def periodo_anterior(d: Dados, meses: list) -> list | None:
    if not meses:
        return None
    n = len(meses)
    i0 = d.meses.index(meses[0])
    if i0 - n < 0:
        return None
    return d.meses[i0 - n:i0]


def dias_periodo(d: Dados, meses) -> int:
    return int(sum(d.dias_mes.get(m, pd.Timestamp(m).days_in_month) for m in meses))


def _rotulos(d: Dados, nivel: str) -> dict:
    """Descrição mais frequente por chave de nível."""
    V = d.V
    if V.empty:
        return {}
    k = f"k_{nivel}"
    g = V[V["descricao"].notna() & (V["descricao"] != "")].groupby([k, "descricao"])["un"].sum().reset_index()
    g = g.sort_values("un", ascending=False).drop_duplicates(k)
    return dict(zip(g[k], g["descricao"]))


def estoque_em(d: Dados, data: pd.Timestamp | None = None) -> pd.DataFrame:
    """Itens de estoque vigentes numa data: para cada depósito, a foto mais recente <= data
    (válida por até CARRY_ESTOQUE_DIAS dias). data=None -> última foto de cada depósito."""
    E = d.E
    if E.empty:
        return E
    fotos = E[["deposito", "data"]].drop_duplicates()
    if data is not None:
        fotos = fotos[(fotos["data"] <= data) & (fotos["data"] >= data - pd.Timedelta(days=CARRY_ESTOQUE_DIAS))]
    if fotos.empty:
        return E.iloc[0:0]
    ult = fotos.groupby("deposito")["data"].max().reset_index()
    return E.merge(ult, on=["deposito", "data"])


def demanda_diaria(d: Dados, meses, categoria="todos") -> pd.Series:
    """Unidades em peças por dia no conjunto de meses, por SKU de peça."""
    P = _filtrar_cat(d.P[d.P["mes"].isin(meses) & ~d.P["sku"].isin(d.externos)], categoria)
    dias = dias_periodo(d, meses)
    if P.empty or dias <= 0:
        return pd.Series(dtype=float)
    return P.groupby("sku")["un"].sum() / dias


def meses_base_demanda(d: Dados, ate=None) -> list:
    """Últimos JANELA_DEMANDA_MESES meses (inclui o mês parcial corrente)."""
    ms = [m for m in d.meses if ate is None or m <= ate]
    return ms[-JANELA_DEMANDA_MESES:]


# --------------------------------------------------------------------------- indicadores
def kpis_vendas(d: Dados, meses, categoria) -> dict:
    V = _filtrar_cat(d.V[d.V["mes"].isin(meses)], categoria)
    un, fat = float(V["un"].sum()), float(V["fat"].sum())
    ml = float(V["ml"].sum()) if V["ml"].notna().any() else None
    sh = float(V["sh"].sum()) if V["sh"].notna().any() else None
    dias = dias_periodo(d, meses)
    out = {
        "unidades": _f(un, 0), "faturamento": _f(fat), "preco_medio": _f(fat / un) if un else None,
        "skus_vendidos": int((V.groupby("sku")["un"].sum() > 0).sum()),
        "modelos_vendidos": int((V[V["categoria"] == "calcado"].groupby("k_modelo")["un"].sum() > 0).sum()),
        "unidades_ml": _f(ml, 0), "unidades_shopee": _f(sh, 0),
        "dias": dias, "unidades_dia": _f(un / dias, 1) if dias else None,
        "faturamento_dia": _f(fat / dias) if dias else None,
        "contem_parcial": any(m in d.parciais for m in meses),
    }
    ant = periodo_anterior(d, meses)
    if ant:
        Va = _filtrar_cat(d.V[d.V["mes"].isin(ant)], categoria)
        una, fata = float(Va["un"].sum()), float(Va["fat"].sum())
        diasa = dias_periodo(d, ant)
        # com mês parcial, compara médias diárias (totais não são comparáveis)
        base = "media_diaria" if out["contem_parcial"] else "total"
        if base == "media_diaria":
            out["comparacao"] = {
                "base": base, "periodo": [mes_label(ant[0]), mes_label(ant[-1])],
                "unidades": _pct(un / dias, una / diasa), "faturamento": _pct(fat / dias, fata / diasa),
                "preco_medio": _pct(fat / un if un else None, fata / una if una else None),
                "unidades_ant": _f(una, 0), "faturamento_ant": _f(fata)}
        else:
            out["comparacao"] = {
                "base": base, "periodo": [mes_label(ant[0]), mes_label(ant[-1])],
                "unidades": _pct(un, una), "faturamento": _pct(fat, fata),
                "preco_medio": _pct(fat / un if un else None, fata / una if una else None),
                "unidades_ant": _f(una, 0), "faturamento_ant": _f(fata)}
    return out


def serie_mensal(d: Dados, meses, categoria) -> list:
    V = _filtrar_cat(d.V[d.V["mes"].isin(meses)], categoria)
    g = V.groupby("mes").agg(un=("un", "sum"), fat=("fat", "sum"), ml=("ml", "sum"), sh=("sh", "sum"),
                             skus=("sku", lambda s: 0)).reindex(meses).fillna(0)
    ativos = V[V["un"] > 0].groupby("mes")["sku"].nunique().reindex(meses).fillna(0)
    out = []
    for m, r in g.iterrows():
        dias = d.dias_mes.get(m)
        out.append({"mes": m.strftime("%Y-%m"), "rotulo": mes_label(m), "parcial": m in d.parciais, "dias": dias,
                    "unidades": _f(r.un, 0), "faturamento": _f(r.fat), "preco_medio": _f(r.fat / r.un) if r.un else None,
                    "unidades_ml": _f(r.ml, 0), "unidades_shopee": _f(r.sh, 0), "skus_ativos": int(ativos.get(m, 0)),
                    "unidades_dia": _f(r.un / dias, 1) if dias else None, "faturamento_dia": _f(r.fat / dias) if dias else None})
    return out


def faixas_preco(d: Dados, meses, categoria, nivel=None, chave=None) -> dict:
    """Distribuição das unidades por faixa de preço.
    Base: preço médio de cada SKU em cada mês (faturamento ÷ unidades), pois o arquivo é mensal."""
    V = _filtrar_cat(d.V[d.V["mes"].isin(meses)], categoria)
    if nivel and chave:
        V = V[V[f"k_{nivel}"] == chave]
    V = V[(V["un"] > 0) & (V["fat"] > 0)]
    if V.empty:
        return {"status": "sem_dados", "motivo": "Sem vendas com faturamento no período."}
    preco = V["fat"] / V["un"]
    lo, hi = np.percentile(preco, 1), np.percentile(preco, 99)
    larg = next((w for w in (5, 10, 20, 25, 50, 100, 200, 500) if (hi - lo) / w <= 10), 1000)
    ini = math.floor(lo / larg) * larg
    bordas = np.arange(ini, hi + larg, larg)
    if len(bordas) < 2:
        bordas = np.array([ini, ini + larg])
    p_clip = preco.clip(bordas[0], bordas[-1] - 0.001)
    idx = np.digitize(p_clip, bordas) - 1
    df = pd.DataFrame({"i": idx, "un": V["un"].values, "fat": V["fat"].values, "sku": V["sku"].values})
    g = df.groupby("i").agg(un=("un", "sum"), fat=("fat", "sum"), skus=("sku", "nunique"))
    faixas = []
    for i in range(len(bordas) - 1):
        r = g.loc[i] if i in g.index else None
        a, b = bordas[i], bordas[i + 1]
        faixas.append({"de": _f(a), "ate": _f(b),
                       "rotulo": (f"até {b:.0f}" if i == 0 and lo < a else f"{a:.0f}–{b:.0f}") if i < len(bordas) - 2 else f"{a:.0f}+",
                       "unidades": _f(r.un, 0) if r is not None else 0, "faturamento": _f(r.fat) if r is not None else 0,
                       "skus": int(r.skus) if r is not None else 0})
    top = max(faixas, key=lambda x: x["unidades"])
    # preço (arredondado a R$1) com mais unidades
    pr = pd.DataFrame({"p": preco.round(0), "un": V["un"].values}).groupby("p")["un"].sum().sort_values(ascending=False)
    return {"status": "ok", "largura": larg, "faixas": faixas, "faixa_top": top,
            "precos_top": [{"preco": _f(p, 0), "unidades": _f(u, 0)} for p, u in pr.head(5).items()],
            "nota": "Calculado com o preço médio mensal de cada SKU (o arquivo de vendas não traz o preço de cada pedido)."}


def economia_pe(d: Dados, meses, categoria="todos", nivel=None, chave=None) -> dict:
    C = d.C
    if C.empty:
        return {"status": "sem_dados", "motivo": "Nenhuma compra importada."}
    if categoria == "outro":
        return {"status": "sem_dados", "motivo": "As compras importadas são apenas de calçados (padrão de modelo)."}
    ini = pd.Timestamp(meses[0]); fim = pd.Timestamp(meses[-1]) + pd.offsets.MonthEnd(0)
    c = C[(C["data"] >= ini) & (C["data"] <= fim)]
    if nivel == "modelo" and chave:
        c = c[c["modelo"] == chave]
    elif nivel in ("cabedal", "sku") and chave:
        mod = interpretar(chave).modelo
        c = c[c["modelo"] == mod]
    pe = c[c["modalidade"] == "PE"]
    prog = c[c["modalidade"] == "PROG"]
    if pe.empty:
        return {"status": "sem_dados" if c.empty else "ok", "motivo": "Sem compras pronta-entrega no período.",
                "pares_pe": 0, "economia": 0, "pares_prog": _f(prog["quantidade"].sum(), 0)}
    com_q = pe[pe["quantidade"].notna()]
    calc = com_q[com_q["ref"].notna()].copy()
    calc["economia"] = (calc["ref"] - calc["valor_unitario"]) * calc["quantidade"]
    calc["valor_ref"] = calc["ref"] * calc["quantidade"]
    sem_ref = com_q[com_q["ref"].isna()]
    sem_q = pe[pe["quantidade"].isna()]
    por_mes = (calc.groupby(calc["data"].dt.to_period("M"))
               .agg(economia=("economia", "sum"), pares=("quantidade", "sum")).reset_index())
    por_modelo = (calc.groupby("modelo").agg(economia=("economia", "sum"), pares=("quantidade", "sum"),
                                             preco_pe=("valor_unitario", "median"), preco_ref=("ref", "median"))
                  .sort_values("economia", ascending=False).reset_index())
    valor_ref = float(calc["valor_ref"].sum())
    eco = float(calc["economia"].sum())
    return {
        "status": "ok",
        "economia": _f(eco), "pares_calculados": _f(calc["quantidade"].sum(), 0),
        "valor_pago_calculado": _f((calc["valor_unitario"] * calc["quantidade"]).sum()),
        "valor_programado_equivalente": _f(valor_ref),
        "economia_pct": _f(eco / valor_ref * 100, 1) if valor_ref else None,
        "pares_pe": _f(com_q["quantidade"].sum(), 0),
        "pares_sem_referencia": _f(sem_ref["quantidade"].sum(), 0),
        "modelos_sem_referencia": sorted(sem_ref["modelo"].dropna().unique().tolist())[:50],
        "linhas_sem_quantidade": int(len(sem_q)),
        "notas_sem_quantidade": int(sem_q["nota_chave"].nunique()),
        "linhas_quantidade_inferida": int((pe["quantidade_origem"] == "inferida").sum()),
        "pares_prog": _f(prog["quantidade"].sum(), 0),
        "por_mes": [{"mes": str(r["data"]), "rotulo": mes_label(r["data"].to_timestamp()),
                     "economia": _f(r["economia"]), "pares": _f(r["pares"], 0)} for _, r in por_mes.iterrows()],
        "por_modelo": [{"modelo": r["modelo"], "economia": _f(r["economia"]), "pares": _f(r["pares"], 0),
                        "preco_pe": _f(r["preco_pe"]), "preco_ref": _f(r["preco_ref"])} for _, r in por_modelo.head(30).iterrows()],
        "nota": ("Economia = (preço líquido do programado do mesmo modelo na compra programada mais próxima "
                 "− preço pago no pronta-entrega) × pares. Itens sem programado do modelo ficam sem referência; "
                 "notas sem quantidade ficam de fora."),
    }


def _estoque_por_chave(d: Dados, categoria, nivel, data=None):
    E = _filtrar_cat(estoque_em(d, data), categoria)
    if E.empty:
        return pd.DataFrame(columns=["est"])
    k = f"k_{nivel}"
    tot = E.groupby(k)["qtd"].sum().rename("est")
    dep = E.pivot_table(index=k, columns="deposito", values="qtd", aggfunc="sum").fillna(0)
    dep.columns = [f"dep::{c}" for c in dep.columns]
    return pd.concat([tot, dep], axis=1)


def _demanda_por_chave(d: Dados, meses, categoria, nivel):
    P = _filtrar_cat(d.P[d.P["mes"].isin(meses) & ~d.P["sku"].isin(d.externos)], categoria)
    dias = dias_periodo(d, meses)
    if P.empty or not dias:
        return pd.Series(dtype=float, name="dem_dia")
    return (P.groupby(f"k_{nivel}")["un"].sum() / dias).rename("dem_dia")


def status_cobertura(est, dem):
    if dem is None or (isinstance(dem, float) and math.isnan(dem)) or dem <= 0:
        return "sem_giro" if est and est > 0 else "inativo"
    if est is None or est <= 0:
        return "ruptura"
    dias = est / dem
    if dias < COBERTURA_CRITICA:
        return "critico"
    if dias > COBERTURA_EXCESSO:
        return "excesso"
    return "ok"


def tempo_estoque(d: Dados, meses, categoria) -> dict:
    E = _filtrar_cat(estoque_em(d), categoria)
    if E.empty:
        return {"status": "sem_dados", "motivo": "Nenhum estoque importado."}
    est = E.groupby("sku")["qtd"].sum()
    dem = demanda_diaria(d, meses, categoria)
    df = pd.concat([est.rename("est"), dem.rename("dem")], axis=1).fillna(0)
    com_giro = df[df["dem"] > 0]
    est_giro = float(com_giro["est"].clip(lower=0).sum())
    dem_tot = float(com_giro["dem"].sum())
    df["status"] = [status_cobertura(e, m) for e, m in zip(df["est"], df["dem"])]
    faixas = []
    for st, rot in (("ruptura", "Ruptura"), ("critico", f"< {COBERTURA_CRITICA} dias"), ("ok", f"{COBERTURA_CRITICA}–{COBERTURA_EXCESSO} dias"),
                    ("excesso", f"> {COBERTURA_EXCESSO} dias"), ("sem_giro", "Sem giro no período")):
        s = df[df["status"] == st]
        faixas.append({"status": st, "rotulo": rot, "skus": int(len(s)), "unidades": _f(s["est"].sum(), 0)})
    return {
        "status": "ok",
        "dias": _f(est_giro / dem_tot, 0) if dem_tot else None,
        "estoque_com_giro": _f(est_giro, 0), "demanda_dia": _f(dem_tot, 1),
        "estoque_sem_giro": _f(df.loc[df["dem"] <= 0, "est"].clip(lower=0).sum(), 0),
        "faixas": faixas,
        "nota": "Estoque atual ÷ demanda diária média do período (em peças; kits convertidos). "
                "Estoque de itens sem venda no período aparece separado como 'sem giro'.",
    }


def resumo_estoque(d: Dados, categoria) -> dict:
    E = _filtrar_cat(estoque_em(d), categoria)
    if E.empty:
        return {"status": "sem_dados", "motivo": "Nenhum estoque importado."}
    dep = E.groupby("deposito").agg(unidades=("qtd", "sum"), data=("data", "max"),
                                    codigos=("codigo", "nunique"))
    dep["com_saldo"] = E[E["qtd"] > 0].groupby("deposito")["codigo"].nunique()
    cat = E.groupby("categoria")["qtd"].sum()
    return {
        "status": "ok", "total": _f(E["qtd"].sum(), 0),
        "depositos": [{"deposito": k, "unidades": _f(r.unidades, 0), "data": r.data.strftime("%Y-%m-%d"),
                       "codigos": int(r.codigos), "codigos_com_saldo": int(r.com_saldo or 0)} for k, r in dep.iterrows()],
        "por_categoria": {k: _f(v, 0) for k, v in cat.items()},
        "skus_com_saldo": int((E.groupby("sku")["qtd"].sum() > 0).sum()),
    }


def vendas_perdidas(d: Dados, meses, categoria, nivel="sku", chave=None, limite=50) -> dict:
    """Pares que deixaram de ser vendidos por falta de estoque.

    Para cada dia com foto de estoque no período e cada SKU zerado (soma dos depósitos):
        perda do dia = demanda diária do SKU
    Demanda diária = peças vendidas nos últimos 3 meses até o mês do dia ÷ dias desses meses
    em que o SKU tinha estoque (dias zerados conhecidos são descontados).
    Valor = pares perdidos × preço médio do SKU nesses meses.
    """
    E = d.E
    if E.empty:
        return {"status": "sem_dados", "motivo": "Nenhum estoque importado. Importe o estoque diariamente para medir vendas perdidas."}
    ini = pd.Timestamp(meses[0]); fim = pd.Timestamp(meses[-1]) + pd.offsets.MonthEnd(0)
    datas = sorted(x for x in E["data"].unique() if ini <= x <= fim)
    primeira = pd.Timestamp(E["data"].min())
    if not datas:
        return {"status": "sem_dados",
                "motivo": f"Não há fotos de estoque neste período. O monitoramento começou em {primeira:%d/%m/%Y}; "
                          "importe o estoque todos os dias para acumular o histórico."}
    k = f"k_{nivel}"
    registros = []
    zerados_por_sku: dict = {}
    for dt in datas:
        dt = pd.Timestamp(dt)
        Ed = _filtrar_cat(estoque_em(d, dt), categoria)
        if Ed.empty:
            continue
        est = Ed.groupby("sku")["qtd"].sum()
        zer = est[est <= 0].index
        for s in zer:
            zerados_por_sku.setdefault(s, []).append(dt)
        mes_dt = dt.to_period("M").to_timestamp()
        base = meses_base_demanda(d, ate=mes_dt)
        registros.append((dt, list(zer), base))
    if not registros:
        return {"status": "sem_dados", "motivo": "Sem estoque para a categoria escolhida."}

    preco = d.V.groupby("sku").apply(lambda g: g["fat"].sum() / g["un"].sum() if g["un"].sum() else np.nan,
                                     include_groups=False)
    linhas = []
    cache_dem = {}
    for dt, zer, base in registros:
        chave_b = tuple(base)
        if chave_b not in cache_dem:
            Pb = d.P[d.P["mes"].isin(base) & ~d.P["sku"].isin(d.externos)]
            cache_dem[chave_b] = (Pb.groupby("sku")["un"].sum(), dias_periodo(d, base),
                                  base[0], base[-1] + pd.offsets.MonthEnd(0))
        un_b, dias_b, b_ini, b_fim = cache_dem[chave_b]
        for s in zer:
            if s in d.externos:
                continue
            u = un_b.get(s, 0.0)
            if u <= 0:
                continue
            zerados = sum(1 for z in zerados_por_sku.get(s, []) if b_ini <= z <= b_fim)
            dias_ef = max(dias_b - zerados, 1)
            dem = u / dias_ef
            linhas.append({"data": dt, "sku": s, "pares": dem, "preco": preco.get(s, np.nan)})
    dias_mon = len(registros)
    if not linhas:
        return {"status": "ok", "dias_monitorados": dias_mon, "primeira_foto": primeira.strftime("%Y-%m-%d"),
                "pares": 0, "valor": 0, "itens": [], "por_dia": [], "skus": 0,
                "nota": "Nenhum SKU com demanda ficou zerado nos dias monitorados."}
    L = pd.DataFrame(linhas)
    L = _chaves(L)
    L = _filtrar_cat(L, categoria)
    if chave:
        L = L[L[k] == chave]
    L["valor"] = L["pares"] * L["preco"]
    por_item = (L.groupby(k).agg(pares=("pares", "sum"), valor=("valor", "sum"), dias=("data", "nunique"))
                .sort_values("pares", ascending=False))
    por_dia = L.groupby("data").agg(pares=("pares", "sum"), valor=("valor", "sum"), skus=("sku", "nunique"))
    sem_preco = float(L.loc[L["preco"].isna(), "pares"].sum())
    rot = _rotulos(d, nivel)
    return {
        "status": "ok", "dias_monitorados": dias_mon, "primeira_foto": primeira.strftime("%Y-%m-%d"),
        "ultima_foto": pd.Timestamp(datas[-1]).strftime("%Y-%m-%d"),
        "pares": _f(L["pares"].sum(), 1), "valor": _f(L["valor"].sum()), "skus": int(L["sku"].nunique()),
        "pares_sem_preco": _f(sem_preco, 1),
        "itens": [{"chave": i, "descricao": rot.get(i, ""), "pares": _f(r.pares, 1), "valor": _f(r.valor),
                   "dias": int(r.dias)} for i, r in (por_item.head(limite) if limite else por_item).iterrows()],
        "por_dia": [{"data": i.strftime("%Y-%m-%d"), "pares": _f(r.pares, 1), "valor": _f(r.valor), "skus": int(r.skus)}
                    for i, r in por_dia.iterrows()],
        "nota": (f"Medido em {dias_mon} dia(s) com foto de estoque. Demanda diária = vendas (em peças) dos últimos "
                 "3 meses ÷ dias com estoque. O valor usa o preço médio do SKU."),
    }


def rupturas_atuais(d: Dados, categoria, nivel="sku", limite=50) -> dict:
    E = _filtrar_cat(estoque_em(d), categoria)
    if E.empty:
        return {"status": "sem_dados", "motivo": "Nenhum estoque importado."}
    base = meses_base_demanda(d)
    dem = demanda_diaria(d, base, categoria)
    est = E.groupby("sku")["qtd"].sum()
    df = pd.concat([est.rename("est"), dem.rename("dem")], axis=1)
    df = df[(df["est"].fillna(0) <= 0) & (df["dem"] > 0)].reset_index().rename(columns={"index": "sku"})
    if df.empty:
        return {"status": "ok", "skus": 0, "pares_mes": 0, "itens": []}
    df = _chaves(df)
    k = f"k_{nivel}"
    g = df.groupby(k).agg(dem=("dem", "sum"), skus=("sku", "nunique")).sort_values("dem", ascending=False)
    rot = _rotulos(d, nivel)
    return {"status": "ok", "skus": int(len(df)), "pares_mes": _f(df["dem"].sum() * 30, 0),
            "base": [mes_label(base[0]), mes_label(base[-1])],
            "itens": [{"chave": i, "descricao": rot.get(i, ""), "demanda_dia": _f(r.dem, 2),
                       "pares_mes": _f(r.dem * 30, 0), "skus": int(r.skus)} for i, r in g.head(limite).iterrows()]}


def grade_quebrada(d: Dados, limite=50) -> dict:
    E = estoque_em(d)
    E = E[(E["categoria"] == "calcado") & E["tamanho"].notna() & ~E["sku"].isin(d.externos)]
    if E.empty:
        return {"status": "sem_dados", "motivo": "Sem estoque de calçados por tamanho."}
    base = meses_base_demanda(d)
    dem = demanda_diaria(d, base, "calcado")
    g = E.groupby(["sku", "tamanho"])["qtd"].sum().reset_index()
    out = []
    for sku, s in g.groupby("sku"):
        if dem.get(sku, 0) <= 0:
            continue
        zer = s[s["qtd"] <= 0]
        if 0 < len(zer) < len(s):
            out.append({"sku": sku, "tamanhos": int(len(s)), "zerados": int(len(zer)),
                        "tamanhos_zerados": sorted(zer["tamanho"].tolist(), key=lambda x: int(x) if x.isdigit() else 0),
                        "disponivel_pct": _f((len(s) - len(zer)) / len(s) * 100, 0),
                        "estoque": _f(s["qtd"].sum(), 0), "pares_mes": _f(dem.get(sku, 0) * 30, 0)})
    out.sort(key=lambda x: -x["pares_mes"])
    return {"status": "ok", "skus": len(out), "itens": out[:limite],
            "nota": "SKUs com venda nos últimos 3 meses, estoque positivo e pelo menos um tamanho zerado (soma dos depósitos)."}


def estoque_parado(d: Dados, categoria, nivel="sku", limite=50) -> dict:
    E = _filtrar_cat(estoque_em(d), categoria)
    if E.empty:
        return {"status": "sem_dados", "motivo": "Nenhum estoque importado."}
    base = meses_base_demanda(d)
    dem = demanda_diaria(d, base, categoria)
    est = E.groupby("sku")["qtd"].sum()
    par = est[(est > 0) & (dem.reindex(est.index).fillna(0) <= 0)]
    df = _chaves(par.rename("est").reset_index().rename(columns={"index": "sku"}))
    k = f"k_{nivel}"
    g = df.groupby(k)["est"].sum().sort_values(ascending=False)
    ultima = d.V[d.V["un"] > 0].groupby(f"k_{nivel}")["mes"].max()
    rot = _rotulos(d, nivel)
    return {"status": "ok", "skus": int(len(par)), "unidades": _f(par.sum(), 0),
            "base": [mes_label(base[0]), mes_label(base[-1])] if base else None,
            "itens": [{"chave": i, "descricao": rot.get(i, ""), "estoque": _f(v, 0),
                       "ultima_venda": mes_label(ultima[i]) if i in ultima.index else "sem venda no histórico"}
                      for i, v in g.head(limite).items()]}


def tabela(d: Dados, meses, categoria, nivel) -> list:
    k = f"k_{nivel}"
    V = _filtrar_cat(d.V[d.V["mes"].isin(meses)], categoria)
    g = V.groupby(k).agg(un=("un", "sum"), fat=("fat", "sum"), ml=("ml", "sum"), sh=("sh", "sum"),
                         skus=("sku", "nunique"), categoria=("categoria", "first"))
    ant = periodo_anterior(d, meses)
    contem_parcial = any(m in d.parciais for m in meses)
    if ant:
        Va = _filtrar_cat(d.V[d.V["mes"].isin(ant)], categoria)
        ga = Va.groupby(k).agg(un_ant=("un", "sum"), fat_ant=("fat", "sum"))
        g = g.join(ga, how="left")
    est = _estoque_por_chave(d, categoria, nivel)
    dem = _demanda_por_chave(d, meses, categoria, nivel)
    df = g.join(est, how="outer").join(dem, how="left")
    df = df[(df["un"].fillna(0) > 0) | (df["est"].fillna(0) != 0)]
    perdas = vendas_perdidas(d, meses, categoria, nivel, limite=None)
    perd = {i["chave"]: i for i in perdas.get("itens", [])} if perdas.get("status") == "ok" else {}
    rot = _rotulos(d, nivel)
    if d.externos:
        Pk = d.P[["sku", k]].drop_duplicates()
        tot_k = Pk.groupby(k)["sku"].nunique()
        ext_k = Pk[Pk["sku"].isin(d.externos)].groupby(k)["sku"].nunique()
        chaves_externas = set(ext_k[ext_k == tot_k.reindex(ext_k.index)].index)
    else:
        chaves_externas = set()
    fat_tot = df["fat"].fillna(0).sum()
    # curva ABC: a mesma classificação global por modelo usada no filtro do topo (Vendas › Curva ABC)
    from . import abc as _abc
    _cls = _abc.classificar(dados_base())["classes"]
    _mod = {}
    for _k in df.index:
        if _k not in _mod:
            _p = interpretar(str(_k), com_tamanho=False)
            _mod[_k] = _p.modelo if (_p.categoria == "calcado" and nivel != "modelo") else _k
    curva = pd.Series({_k: _abc.classe(_cls, _mod[_k]) for _k in df.index}, dtype=object)
    dias = dias_periodo(d, meses)
    dias_ant = dias_periodo(d, ant) if ant else None
    deps = [c for c in df.columns if c.startswith("dep::")]
    linhas = []
    for key, r in df.iterrows():
        un = float(r.get("un") or 0) if not pd.isna(r.get("un")) else 0.0
        fat = float(r.get("fat") or 0) if not pd.isna(r.get("fat")) else 0.0
        e = None if pd.isna(r.get("est")) else float(r["est"])
        dm = None if pd.isna(r.get("dem_dia")) else float(r["dem_dia"])
        cat = r.get("categoria")
        if pd.isna(cat) if not isinstance(cat, str) else False:
            cat = interpretar(key).categoria
        var_un = var_fat = None
        if ant:
            ua, fa = r.get("un_ant"), r.get("fat_ant")
            ua = 0 if pd.isna(ua) else ua
            fa = 0 if pd.isna(fa) else fa
            if contem_parcial:
                var_un = _pct(un / dias, ua / dias_ant) if ua else None
                var_fat = _pct(fat / dias, fa / dias_ant) if fa else None
            else:
                var_un, var_fat = _pct(un, ua) if ua else None, _pct(fat, fa) if fa else None
        linhas.append({
            "chave": key, "descricao": rot.get(key, ""), "categoria": cat,
            "unidades": _f(un, 0), "faturamento": _f(fat), "preco_medio": _f(fat / un) if un else None,
            "participacao": _f(fat / fat_tot * 100, 2) if fat_tot else None,
            "unidades_ml": _f(r.get("ml"), 0) if not pd.isna(r.get("ml")) else None,
            "unidades_shopee": _f(r.get("sh"), 0) if not pd.isna(r.get("sh")) else None,
            "skus": int(r.get("skus")) if not pd.isna(r.get("skus")) else 0,
            "var_unidades": var_un, "var_faturamento": var_fat,
            "estoque": _f(e, 0), "estoque_depositos": {c[5:]: _f(r[c], 0) for c in deps if not pd.isna(r[c])},
            "demanda_dia": _f(dm, 2), "cobertura_dias": _f(e / dm, 0) if (e is not None and dm) else None,
            "status_estoque": ("externo" if key in chaves_externas else
                               status_cobertura(e or 0, dm) if e is not None else "sem_cadastro"),
            "perdas_pares": perd[key]["pares"] if key in perd else None,
            "perdas_valor": perd[key]["valor"] if key in perd else None,
            "curva": curva.get(key, "–"),
        })
    linhas.sort(key=lambda x: -(x["faturamento"] or 0))
    return linhas


def mensal(d: Dados, categoria) -> list:
    out = serie_mensal(d, d.meses, categoria)
    for i, m in enumerate(out):
        mes = pd.Timestamp(m["mes"] + "-01")
        eco = economia_pe(d, [mes], categoria)
        m["economia_pe"] = eco.get("economia") if eco.get("status") == "ok" else None
        m["pares_pe"] = eco.get("pares_calculados") if eco.get("status") == "ok" else None
        perd = vendas_perdidas(d, [mes], categoria)
        m["vendas_perdidas_pares"] = perd.get("pares") if perd.get("status") == "ok" else None
        m["vendas_perdidas_valor"] = perd.get("valor") if perd.get("status") == "ok" else None
        if i > 0:
            a = out[i - 1]
            if m["parcial"] or a["parcial"]:
                m["var_unidades"] = _pct(m["unidades_dia"], a["unidades_dia"])
                m["var_faturamento"] = _pct(m["faturamento_dia"], a["faturamento_dia"])
                m["base_var"] = "media_diaria"
            else:
                m["var_unidades"] = _pct(m["unidades"], a["unidades"])
                m["var_faturamento"] = _pct(m["faturamento"], a["faturamento"])
                m["base_var"] = "total"
            m["var_preco_medio"] = _pct(m["preco_medio"], a["preco_medio"])
    return out


def comparar_meses(d: Dados, a: str, b: str, categoria, nivel, limite=15) -> dict:
    ma, mb = pd.Timestamp(a + "-01"), pd.Timestamp(b + "-01")
    k = f"k_{nivel}"
    V = _filtrar_cat(d.V, categoria)
    da, db_ = d.dias_mes.get(ma), d.dias_mes.get(mb)
    usar_dia = (ma in d.parciais) or (mb in d.parciais)
    ga = V[V["mes"] == ma].groupby(k).agg(un_a=("un", "sum"), fat_a=("fat", "sum"))
    gb = V[V["mes"] == mb].groupby(k).agg(un_b=("un", "sum"), fat_b=("fat", "sum"))
    df = ga.join(gb, how="outer").fillna(0)
    if usar_dia:
        df["delta_un"] = df["un_b"] / db_ * 30 - df["un_a"] / da * 30
        df["delta_fat"] = df["fat_b"] / db_ * 30 - df["fat_a"] / da * 30
    else:
        df["delta_un"] = df["un_b"] - df["un_a"]
        df["delta_fat"] = df["fat_b"] - df["fat_a"]
    rot = _rotulos(d, nivel)

    def lst(s):
        return [{"chave": i, "descricao": rot.get(i, ""), "unidades_a": _f(r.un_a, 0), "unidades_b": _f(r.un_b, 0),
                 "faturamento_a": _f(r.fat_a), "faturamento_b": _f(r.fat_b), "delta_faturamento": _f(r.delta_fat),
                 "delta_unidades": _f(r.delta_un, 0)} for i, r in s.iterrows()]
    ka, kb = kpis_vendas(d, [ma], categoria), kpis_vendas(d, [mb], categoria)
    return {"a": {"mes": a, "rotulo": mes_label(ma), "parcial": ma in d.parciais, **{x: ka[x] for x in ("unidades", "faturamento", "preco_medio", "skus_vendidos", "unidades_dia", "faturamento_dia")}},
            "b": {"mes": b, "rotulo": mes_label(mb), "parcial": mb in d.parciais, **{x: kb[x] for x in ("unidades", "faturamento", "preco_medio", "skus_vendidos", "unidades_dia", "faturamento_dia")}},
            "base": "media_30_dias" if usar_dia else "total",
            "altas": lst(df.sort_values("delta_fat", ascending=False).head(limite)),
            "quedas": lst(df.sort_values("delta_fat").head(limite))}


def detalhe(d: Dados, nivel, chave, categoria="todos") -> dict:
    k = f"k_{nivel}"
    V = d.V[d.V[k] == chave]
    serie = []
    for m in d.meses:
        s = V[V["mes"] == m]
        un, fat = float(s["un"].sum()), float(s["fat"].sum())
        # unidades por marketplace (quando o arquivo traz o canal); o resto fica como "sem canal"
        ml = float(pd.to_numeric(s["ml"], errors="coerce").fillna(0).sum()) if "ml" in s else 0.0
        sh = float(pd.to_numeric(s["sh"], errors="coerce").fillna(0).sum()) if "sh" in s else 0.0
        serie.append({"mes": m.strftime("%Y-%m"), "rotulo": mes_label(m), "parcial": m in d.parciais,
                      "unidades": _f(un, 0), "faturamento": _f(fat), "preco_medio": _f(fat / un) if un else None,
                      "unidades_ml": _f(ml, 0), "unidades_shopee": _f(sh, 0), "unidades_outros": _f(max(un - ml - sh, 0), 0)})
    filhos = []
    if nivel != "sku":
        g = V.groupby("sku").agg(un=("un", "sum"), fat=("fat", "sum"), desc=("descricao", "first"))
        for s, r in g.sort_values("fat", ascending=False).iterrows():
            filhos.append({"sku": s, "unidades": _f(r.un, 0), "faturamento": _f(r.fat),
                           "preco_medio": _f(r.fat / r.un) if r.un else None})
    E = estoque_em(d)
    E = E[E[k] == chave]
    por_tam = []
    if not E.empty:
        pt = E.pivot_table(index="tamanho", columns="deposito", values="qtd", aggfunc="sum").fillna(0) if E["tamanho"].notna().any() else None
        if pt is not None:
            for t, r in pt.iterrows():
                por_tam.append({"tamanho": t, **{c: _f(v, 0) for c, v in r.items()}, "total": _f(r.sum(), 0)})
            por_tam.sort(key=lambda x: int(x["tamanho"]) if str(x["tamanho"]).isdigit() else 999)
    por_dep = E.groupby("deposito")["qtd"].sum().to_dict() if not E.empty else {}
    base = meses_base_demanda(d)
    P = d.P[(d.P[k] == chave) & d.P["mes"].isin(base)]
    dem = float(P["un"].sum()) / dias_periodo(d, base) if base else 0
    est = float(E["qtd"].sum()) if not E.empty else 0
    C = d.C
    compras = []
    hist_compras = {"notas": 0, "pares": 0, "primeira": None, "ultima": None, "linhas_sem_quantidade": 0}
    if not C.empty:
        mod = chave if nivel == "modelo" else interpretar(chave).modelo
        cm = C[C["modelo"] == mod]
        if not cm.empty:
            q = pd.to_numeric(cm["quantidade"], errors="coerce")
            hist_compras = {"notas": int(cm["nota_chave"].nunique()), "pares": _f(q.sum(), 0),
                            "primeira": cm["data"].min().strftime("%Y-%m-%d"), "ultima": cm["data"].max().strftime("%Y-%m-%d"),
                            "linhas_sem_quantidade": int(q.isna().sum())}
            g = cm.groupby([cm["data"].dt.strftime("%Y-%m-%d"), "modalidade"]).agg(
                preco=("valor_unitario", "median"), liquido=("preco_desconto", "median"),
                pares=("quantidade", lambda s: s.sum() if s.notna().any() else None)).reset_index()
            compras = [{"data": r["data"], "modalidade": r["modalidade"], "preco_tabela": _f(r["preco"]),
                        "preco_liquido": _f(r["liquido"]), "pares": _f(r["pares"], 0)} for _, r in g.iterrows()]
    rot = _rotulos(d, nivel)
    p = interpretar(chave)
    # informações detalhadas do produto
    vend = V[V["un"] > 0]
    ult3 = V[V["mes"].isin(meses_base_demanda(d))] if not V.empty else V
    un3, fat3 = float(ult3["un"].sum()), float(ult3["fat"].sum())
    cm_ = C[C["modelo"] == (chave if nivel == "modelo" else p.modelo)] if not C.empty else C
    if nivel == "sku" and not cm_.empty and "sku" in cm_:
        cm_ = cm_[cm_["sku"] == chave] if (cm_["sku"] == chave).any() else cm_
    q_ = pd.to_numeric(cm_["quantidade"], errors="coerce") if not cm_.empty else pd.Series(dtype=float)
    pl_ = pd.to_numeric(cm_["preco_desconto"], errors="coerce") if not cm_.empty else pd.Series(dtype=float)
    custo = float((q_ * pl_).sum() / q_.sum()) if not cm_.empty and q_.sum() else None
    tams_venda = sorted({t for t in (E["tamanho"].dropna().astype(str) if not E.empty else [])}, key=lambda x: int(x) if x.isdigit() else 99)
    from . import abc as _abc
    from . import linha as _linha
    mod_key = chave if (nivel == "modelo" or p.categoria != "calcado") else p.modelo
    e_linha = _linha.estado(mod_key)
    info = {
        "categoria": "Calçado" if p.categoria == "calcado" else "Outro produto",
        "modelo": p.modelo if p.categoria == "calcado" else None, "cabedal": p.cabedal, "cor": p.cor,
        "skus": int(V["sku"].nunique()) if not V.empty else 0,
        "tamanhos_em_estoque": tams_venda,
        "codigos_estoque": sorted(E["codigo"].dropna().astype(str).unique().tolist())[:30] if not E.empty else [],
        "eans": sorted(cm_["ean"].dropna().astype(str).unique().tolist())[:12] if not cm_.empty else [],
        "fornecedor": cm_["fornecedor"].mode().iat[0] if not cm_.empty and cm_["fornecedor"].notna().any() else None,
        "primeira_venda": vend["mes"].min().strftime("%Y-%m") if not vend.empty else None,
        "ultima_venda": vend["mes"].max().strftime("%Y-%m") if not vend.empty else None,
        "meses_com_venda": int(vend["mes"].nunique()) if not vend.empty else 0,
        "preco_venda_3m": _f(fat3 / un3) if un3 else None,
        "custo_medio_compra": _f(custo),
        "curva": _abc.classe(_abc.classificar(dados_base())["classes"], mod_key),
        "linha": "Em linha" if e_linha is True else "Fora de linha" if e_linha is False else "Sem marcação",
        "excluido": chave in (d.excluidos or set()),
    }
    return {"chave": chave, "nivel": nivel, "descricao": rot.get(chave, ""), "info": info,
            "modelo": p.modelo, "cabedal": (p.cabedal or (SEM_CABEDAL if p.categoria == "calcado" else None)),
            "cor": p.cor, "categoria": p.categoria,
            "serie": serie, "filhos": filhos, "estoque_por_tamanho": por_tam,
            "estoque_por_deposito": {k2: _f(v, 0) for k2, v in por_dep.items()},
            "estoque": _f(est, 0), "demanda_dia": _f(dem, 2),
            "cobertura_dias": _f(est / dem, 0) if dem else None, "status_estoque": status_cobertura(est, dem),
            "compras": compras[-40:], "compras_historico": hist_compras,
            "economia_pe": economia_pe(d, d.meses, "todos", nivel, chave) if d.meses else None}


# --------------------------------------------------------------------------- vendas dia a dia
_DIAS_SEM = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def vendas_diarias(d: Dados, categoria="calcado", semanas=12, dias=35) -> dict:
    """Vendas lançadas pelas listas diárias: série por dia, por semana (segunda a domingo)
    e comparações da semana e dos últimos 7 dias. Faturamento: ticket médio da planilha
    ou, sem ele, estimado pelo preço médio."""
    L = d.L
    if L is None or L.empty:
        return {"status": "sem_dados", "motivo": "Nenhuma lista de vendas do dia importada ainda. Suba as listas em Dados › Importar arquivos."}
    L = _filtrar_cat(L, categoria)
    if L.empty:
        return {"status": "sem_dados", "motivo": "Sem vendas do dia lançadas para esta categoria."}
    L = L.assign(dia=pd.to_datetime(L["dia"]).dt.normalize())
    ultimo = L["dia"].max()

    def agrega(df, chave):
        g = df.groupby(chave).agg(un=("un", "sum"), fat=("fat", "sum"))
        for c, nome in (("ml", "ml"), ("shopee", "sh")):
            g[nome] = df[df["canal"] == c].groupby(chave)["un"].sum()
        g["outros"] = df[~df["canal"].isin(["ml", "shopee"])].groupby(chave)["un"].sum()
        g["est"] = df[df["fat_estimado"]].groupby(chave)["fat"].sum()
        return g.fillna(0)

    # por dia
    ini_d = ultimo - pd.Timedelta(days=dias - 1)
    gd = agrega(L[L["dia"] >= ini_d], "dia").reindex(pd.date_range(ini_d, ultimo, freq="D"))
    lancados = set(L["dia"].unique())
    serie_dia = [{"data": x.strftime("%Y-%m-%d"), "rotulo": f"{_DIAS_SEM[x.weekday()]} {x:%d/%m}", "com_dados": x in lancados,
                  "unidades": _f(r.un, 0) if x in lancados else None, "faturamento": _f(r.fat) if x in lancados else None,
                  "unidades_ml": _f(r.ml, 0), "unidades_shopee": _f(r.sh, 0), "unidades_outros": _f(r.outros, 0)}
                 for x, r in gd.fillna(0).iterrows()]

    # por semana (segunda-feira)
    L = L.assign(semana=L["dia"] - pd.to_timedelta(L["dia"].dt.weekday, unit="D"))
    sem_fim = ultimo - pd.Timedelta(days=ultimo.weekday())
    sem_ini = sem_fim - pd.Timedelta(weeks=semanas - 1)
    sem_ini = max(sem_ini, L["semana"].min())     # não mostra semanas antes da primeira lista
    gs = agrega(L[L["semana"] >= sem_ini], "semana").reindex(pd.date_range(sem_ini, sem_fim, freq="7D")).fillna(0)
    dias_sem = L.groupby("semana")["dia"].nunique()
    serie_sem = []
    for s_, r in gs.iterrows():
        n = int(dias_sem.get(s_, 0))
        serie_sem.append({"semana": s_.strftime("%Y-%m-%d"), "rotulo": f"{s_:%d/%m}", "ate": (s_ + pd.Timedelta(days=6)).strftime("%d/%m"),
                          "dias_com_dados": n, "unidades": _f(r.un, 0) if n else None, "faturamento": _f(r.fat) if n else None,
                          "unidades_ml": _f(r.ml, 0), "unidades_shopee": _f(r.sh, 0), "unidades_outros": _f(r.outros, 0),
                          "faturamento_estimado": _f(r.est), "media_dia": _f(r.un / n, 1) if n else None})

    def janela(a, b):
        x = L[(L["dia"] >= a) & (L["dia"] <= b)]
        return {"unidades": _f(x["un"].sum(), 0), "faturamento": _f(x["fat"].sum()), "dias": int(x["dia"].nunique())}
    s_atual = janela(sem_fim, ultimo)
    # semana anterior comparada nos mesmos dias da semana já passados (seg..dia atual)
    s_ant = janela(sem_fim - pd.Timedelta(days=7), ultimo - pd.Timedelta(days=7))
    u7 = janela(ultimo - pd.Timedelta(days=6), ultimo)
    a7 = janela(ultimo - pd.Timedelta(days=13), ultimo - pd.Timedelta(days=7))
    for atual, ant in ((s_atual, s_ant), (u7, a7)):
        atual["var_unidades"] = _pct(atual["unidades"], ant["unidades"]) if ant["dias"] else None
        atual["var_faturamento"] = _pct(atual["faturamento"], ant["faturamento"]) if ant["dias"] else None
    por_dia = L.groupby("dia")["un"].sum()
    melhor = por_dia.idxmax()
    # dia da semana (média por dia lançado)
    dsem = L.groupby(L["dia"].dt.weekday).apply(lambda g: g["un"].sum() / g["dia"].nunique(), include_groups=False)
    top = (L[L["dia"] >= ultimo - pd.Timedelta(days=6)].groupby("k_modelo").agg(un=("un", "sum"), fat=("fat", "sum"))
           .sort_values("un", ascending=False).head(10))
    rot = _rotulos(d, "modelo")
    return {
        "status": "ok", "ultimo_dia": ultimo.strftime("%Y-%m-%d"), "primeiro_dia": L["dia"].min().strftime("%Y-%m-%d"),
        "dias_lancados": int(L["dia"].nunique()),
        "dias": serie_dia, "semanas": serie_sem,
        "semana_atual": {**s_atual, "inicio": sem_fim.strftime("%Y-%m-%d")}, "semana_anterior": s_ant,
        "ultimos7": u7, "anteriores7": a7,
        "melhor_dia": {"data": melhor.strftime("%Y-%m-%d"), "unidades": _f(por_dia[melhor], 0)},
        "dia_da_semana": [{"dia": _DIAS_SEM[i], "media": _f(dsem.get(i), 1) if i in dsem.index else None} for i in range(7)],
        "top_7dias": [{"chave": k, "descricao": rot.get(k, ""), "unidades": _f(r.un, 0), "faturamento": _f(r.fat)} for k, r in top.iterrows()],
        "faturamento_estimado_pct": _f(L.loc[L["fat_estimado"], "fat"].sum() / L["fat"].sum() * 100, 0) if L["fat"].sum() else None,
        "nota": "Vendas das listas diárias importadas. Faturamento pelo ticket médio da planilha; quando não há ticket, estimado pelo preço médio do produto.",
    }


def graficos_resultado(tab: list, faixas: dict) -> dict:
    """Dados extras dos gráficos do Resultado: concentração (curva ABC), quem mais
    cresceu/caiu em R$ e participação por faixa de preço."""
    com = [t for t in tab if (t.get("faturamento") or 0) > 0]
    com.sort(key=lambda t: -t["faturamento"])
    total = sum(t["faturamento"] for t in com) or 1
    pareto, acum = [], 0.0
    n = len(com)
    for i, t in enumerate(com, 1):
        acum += t["faturamento"]
        # no máximo ~60 pontos para o gráfico
        if n <= 60 or i == 1 or i == n or i % max(1, n // 60) == 0:
            pareto.append({"pct_itens": _f(i / n * 100, 1), "pct_fat": _f(acum / total * 100, 1), "itens": i})
    def ate(p):
        a = 0
        for i, t in enumerate(com, 1):
            a += t["faturamento"]
            if a / total * 100 >= p:
                return i
        return n
    mov = []
    for t in tab:
        v, fat = t.get("var_faturamento"), t.get("faturamento") or 0
        if v is None or v <= -100:
            continue
        ant = fat / (1 + v / 100)
        mov.append({"chave": t["chave"], "descricao": t.get("descricao", ""), "delta": _f(fat - ant), "var": v})
    mov.sort(key=lambda x: x["delta"])
    quedas = [x for x in mov if x["delta"] < 0][:6]
    altas = [x for x in reversed(mov) if x["delta"] > 0][:6]
    fx = None
    if faixas.get("status") == "ok":
        tf = sum(x["faturamento"] or 0 for x in faixas["faixas"]) or 1
        fx = [{"rotulo": x["rotulo"], "faturamento": x["faturamento"], "unidades": x["unidades"],
               "pct": _f((x["faturamento"] or 0) / tf * 100, 1)} for x in faixas["faixas"] if x["unidades"]]
    return {"pareto": pareto, "itens": n, "itens_80": ate(80), "itens_50": ate(50),
            "altas": altas, "quedas": list(reversed(quedas))[::-1], "faixas": fx}


# --------------------------------------------------------------------------- mais comprados
def mais_comprados(d: Dados, meses, a_receber: dict | None = None) -> dict:
    """Ranking dos modelos mais comprados nos relatórios de compras (notas de entrada) do período,
    com venda do período, estoque de hoje e pares ainda a receber em pedidos do Omie."""
    C = d.C
    from . import linha as _linha
    modo = _linha.MODO.get()
    if C is None or C.empty:
        return {"status": "sem_dados", "motivo": f"Nenhuma compra de produtos marcados como “{_linha.MODOS[modo].lower()}”." if modo
                else "Nenhum relatório de compras importado."}
    ini = pd.Timestamp(meses[0]); fim = pd.Timestamp(meses[-1]) + pd.offsets.MonthEnd(0)
    c = C[(C["data"] >= ini) & (C["data"] <= fim) & C["modelo"].notna()].copy()
    if c.empty:
        return {"status": "sem_dados", "motivo": "Nenhuma compra com modelo identificado no período."}
    c["qtd"] = pd.to_numeric(c["quantidade"], errors="coerce")
    c["preco"] = pd.to_numeric(c["preco_desconto"], errors="coerce").fillna(pd.to_numeric(c["valor_unitario"], errors="coerce"))
    c["valor"] = c["qtd"] * c["preco"]
    c["pe"] = c["qtd"].where(c["modalidade"] == "PE", 0.0)
    c["sem_qtd"] = c["qtd"].isna().astype(int)
    # histórico completo (todas as compras importadas, independente do período)
    h = C[C["modelo"].notna()].assign(qtd=pd.to_numeric(C["quantidade"], errors="coerce"))
    hist = h.groupby("modelo").agg(h_notas=("nota_chave", "nunique"), h_pares=("qtd", "sum"), h_primeira=("data", "min"),
                                   h_ultima=("data", "max"), h_meses=("data", lambda x: x.dt.to_period("M").nunique()))
    g = c.groupby("modelo").agg(pares=("qtd", "sum"), valor=("valor", "sum"), pe=("pe", "sum"), sem_qtd=("sem_qtd", "sum"),
                                linhas=("qtd", "size"), notas=("nota_chave", "nunique"), ultima=("data", "max"),
                                primeira=("data", "min"), preco_min=("preco", "min"), preco_max=("preco", "max"))
    V = d.V[d.V["mes"].isin(meses)]
    vend = V.groupby("k_modelo")["un"].sum() if not V.empty else pd.Series(dtype=float)
    est = _estoque_por_chave(d, "todos", "modelo")
    est = est["est"] if "est" in est else pd.Series(dtype=float)
    rot = _rotulos(d, "modelo")
    a_receber = a_receber or {}
    separados = set(_produto.modelos_por_cabedal())

    def soma(serie, m):
        """Modelo separado por cabedal comprado sem cabedal: soma todos os cabedais dele."""
        if m in separados:
            return float(sum(v for k, v in serie.items() if str(k).startswith(m + "-") or k == m))
        return float(serie.get(m, 0) or 0)

    itens = []
    for m, r in g.iterrows():
        p = float(r.pares or 0)
        vd = soma(vend, m)
        desc = rot.get(m) or next((rot[k] for k in rot if m in separados and str(k).startswith(m + "-")), "")
        itens.append({
            "modelo": m, "descricao": desc, "todos_cabedais": m in separados, "pares": _f(p, 0), "valor": _f(r.valor) if r.valor else None,
            "preco_medio": _f(r.valor / p) if p and r.valor else None,
            "preco_min": _f(r.preco_min), "preco_max": _f(r.preco_max),
            "pe_pct": _f(r.pe / p * 100, 0) if p else None, "notas": int(r.notas),
            "linhas_sem_quantidade": int(r.sem_qtd), "ultima_compra": r.ultima.strftime("%Y-%m-%d"),
            "primeira_compra": r.primeira.strftime("%Y-%m-%d"),
            "vendidos": _f(vd, 0), "vendido_pct": _f(vd / p * 100, 0) if p else None,
            "estoque": _f(soma(est, m), 0), "a_receber": _f(soma(a_receber, m), 0),
            "historico_compras": int(hist.at[m, "h_notas"]) if m in hist.index else 0,
            "historico_pares": _f(hist.at[m, "h_pares"], 0) if m in hist.index else 0,
            "historico_meses": int(hist.at[m, "h_meses"]) if m in hist.index else 0,
            "historico_primeira": hist.at[m, "h_primeira"].strftime("%Y-%m-%d") if m in hist.index else None,
        })
    itens.sort(key=lambda x: (-(x["pares"] or 0), -(x["linhas_sem_quantidade"] or 0)))
    for i, x in enumerate(itens, 1):
        x["posicao"] = i
    por_mes = (c.groupby([c["data"].dt.to_period("M"), "modalidade"])["qtd"].sum().unstack(fill_value=0)
               if c["qtd"].notna().any() else pd.DataFrame())
    serie = [{"mes": str(pm), "rotulo": mes_label(pm.to_timestamp()), "pe": _f(row.get("PE", 0), 0),
              "prog": _f(row.get("PROG", 0), 0), "pares": _f(row.sum(), 0)} for pm, row in por_mes.iterrows()]
    tot_p = float(c["qtd"].sum())
    return {
        "status": "ok", "itens": itens, "serie": serie,
        "historico": {"de": C["data"].min().strftime("%Y-%m-%d"), "ate": C["data"].max().strftime("%Y-%m-%d"),
                      "notas": int(C["nota_chave"].nunique()), "modelos": int(C["modelo"].nunique())},
        "totais": {"pares": _f(tot_p, 0), "valor": _f(c["valor"].sum()), "modelos": len(itens), "notas": int(c["nota_chave"].nunique()),
                   "pe_pct": _f(c["pe"].sum() / tot_p * 100, 0) if tot_p else None,
                   "preco_medio": _f(c["valor"].sum() / tot_p) if tot_p else None,
                   "linhas_sem_quantidade": int(c["sem_qtd"].sum()), "linhas": len(c)},
        "nota": ("Fonte: relatórios de compras (notas de entrada) importados em Dados. Pares = soma das quantidades; "
                 "linhas sem quantidade não entram nos pares nem no valor. Vendidos = vendas do mesmo período; "
                 "estoque é o de hoje; a receber vem dos pedidos em aberto do Omie."),
    }


# --------------------------------------------------------------------------- vendas por semana do mês
def semana_do_mes(dia) -> int:
    """Semana 1 = dias 1–7, 2 = 8–14, 3 = 15–21, 4 = 22–28, 5 = 29 até o fim do mês."""
    return min((int(dia) - 1) // 7, 4) + 1


def _faixa_semana(mes: pd.Timestamp, n: int):
    ini = mes + pd.Timedelta(days=(n - 1) * 7)
    fim = (mes + pd.offsets.MonthEnd(0)) if n == 5 else ini + pd.Timedelta(days=6)
    return ini, fim


def vendas_semanas(d: Dados, mes: str, categoria="calcado") -> dict:
    """Vendas de um mês por semana (das planilhas semanais/diárias) comparadas com as mesmas
    semanas do mês anterior. Comparação pela média por dia lançado (a semana 5 tem 1 a 3 dias)."""
    m = pd.Timestamp(mes + "-01")
    ant = m - pd.offsets.MonthBegin(1)
    L = d.L if d.L is not None else pd.DataFrame()
    L = _filtrar_cat(L, categoria) if not L.empty else L
    if not L.empty:
        L = L.assign(dia=pd.to_datetime(L["dia"]).dt.normalize())

    def resumo(mes_ts):
        out = []
        for n in range(1, 6):
            ini, fim = _faixa_semana(mes_ts, n)
            if ini.month != mes_ts.month:
                continue
            x = L[(L["dia"] >= ini) & (L["dia"] <= fim)] if not L.empty else L
            dias_tot = (fim - ini).days + 1
            dias_dados = int(x["dia"].nunique()) if not x.empty else 0
            un = float(x["un"].sum()) if not x.empty else 0.0
            fat = float(x["fat"].sum()) if not x.empty else 0.0
            canais = x.groupby("canal")["dia"].nunique().to_dict() if not x.empty else {}
            out.append({"semana": n, "rotulo": f"Semana {n}", "de": ini.strftime("%Y-%m-%d"), "ate": fim.strftime("%Y-%m-%d"),
                        "periodo": f"{ini:%d/%m}–{fim:%d/%m}", "dias": dias_tot, "dias_com_dados": dias_dados,
                        "completa": dias_dados == dias_tot, "unidades": _f(un, 0) if dias_dados else None,
                        "faturamento": _f(fat) if dias_dados else None,
                        "unidades_ml": _f(x.loc[x["canal"] == "ml", "un"].sum(), 0) if dias_dados else None,
                        "unidades_shopee": _f(x.loc[x["canal"] == "shopee", "un"].sum(), 0) if dias_dados else None,
                        "media_dia": _f(un / dias_dados, 1) if dias_dados else None,
                        "fat_estimado": _f(x.loc[x["fat_estimado"], "fat"].sum()) if dias_dados else None,
                        "canais_dias": {k: int(v) for k, v in canais.items()}})
        return out

    atual, anterior = resumo(m), resumo(ant)
    for s_ in atual:
        a = next((x for x in anterior if x["semana"] == s_["semana"]), None)
        s_["anterior"] = a
        s_["var_media_dia"] = _pct(s_["media_dia"], a["media_dia"]) if a and s_["media_dia"] is not None and a["media_dia"] else None
    top = []
    if not L.empty:
        x = L[(L["dia"] >= m) & (L["dia"] <= m + pd.offsets.MonthEnd(0))]
        if not x.empty:
            x = x.assign(sem=x["dia"].dt.day.map(semana_do_mes))
            pv = x.pivot_table(index="k_modelo", columns="sem", values="un", aggfunc="sum").fillna(0)
            pv["total"] = pv.sum(axis=1)
            rot = _rotulos(d, "modelo")
            for k, r in pv.sort_values("total", ascending=False).head(25).iterrows():
                top.append({"modelo": k, "descricao": rot.get(k, ""), "total": _f(r["total"], 0),
                            "semanas": {int(c): _f(v, 0) for c, v in r.items() if c != "total"}})
    tem = any(s_["dias_com_dados"] for s_ in atual)
    return {"mes": mes, "rotulo": mes_label(m), "anterior": mes_label(ant), "tem_dados": tem,
            "semanal_desde": d.semanal_desde.strftime("%Y-%m") if d.semanal_desde is not None else None,
            "semanas": atual, "semanas_anterior": anterior, "top_modelos": top,
            "nota": "Semana do mês: 1 = dias 1–7, 2 = 8–14, 3 = 15–21, 4 = 22–28, 5 = 29 ao fim. A comparação usa a média por dia "
                    "com planilha importada, porque as semanas têm tamanhos diferentes e podem estar incompletas."}


def semanas_importadas(d: Dados, meses_n=4) -> list:
    """Quais semanas (por canal) já têm planilha, nos últimos meses — para saber o que falta enviar."""
    hoje = pd.Timestamp(date.today())
    ini = (d.semanal_desde if d.semanal_desde is not None else hoje - pd.offsets.MonthBegin(meses_n - 1))
    ini = max(pd.Timestamp(ini), hoje - pd.offsets.MonthBegin(meses_n))
    L = d.L if d.L is not None and not d.L.empty else pd.DataFrame(columns=["dia", "canal"])
    L = L.assign(dia=pd.to_datetime(L["dia"]).dt.normalize()) if not L.empty else L
    out, m = [], pd.Timestamp(ini).replace(day=1)
    while m <= hoje:
        sems = []
        for n in range(1, 6):
            a, b = _faixa_semana(m, n)
            if a.month != m.month or a > hoje:
                continue
            b2 = min(b, hoje)
            x = L[(L["dia"] >= a) & (L["dia"] <= b2)] if not L.empty else L
            dias = (b2 - a).days + 1
            cn = x.groupby("canal")["dia"].nunique().to_dict() if not x.empty else {}
            sems.append({"semana": n, "periodo": f"{a:%d/%m}–{b:%d/%m}", "de": a.strftime("%Y-%m-%d"), "ate": b.strftime("%Y-%m-%d"),
                         "dias": dias, "ml": int(cn.get("ml", 0)), "shopee": int(cn.get("shopee", 0)),
                         "sem_canal": int(cn.get("nao_informado", 0)), "em_andamento": b > hoje})
        out.append({"mes": m.strftime("%Y-%m"), "rotulo": mes_label(m), "semanas": sems})
        m = m + pd.offsets.MonthBegin(1)
    return out
