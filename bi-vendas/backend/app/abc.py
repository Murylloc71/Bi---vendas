"""Curva ABC (princípio de Pareto) por modelo, a partir das vendas.

Classificação: ordena os modelos pelo critério (faturamento ou unidades) num período base fixo
(últimos N meses com venda) e acumula: até `limite_a`% = A, até `limite_b`% = B, o resto = C.
Modelos sem venda no período base ficam sem curva ("sem venda").

O filtro global vem do parâmetro `curva` de qualquer requisição (A, B, C, AB, sem_venda);
`indicadores.dados()` e `pedidos.carregar()` aplicam o filtro, como no filtro de produtos em linha.
"""
from __future__ import annotations

import contextvars
import json
import threading

import numpy as np
import pandas as pd
from sqlalchemy import delete, insert, select

from . import db

PADRAO = {"meses": 3, "criterio": "faturamento", "limite_a": 80, "limite_b": 95}
FILTROS = {"A": {"A"}, "B": {"B"}, "C": {"C"}, "AB": {"A", "B"}, "sem_venda": {"–"}}
MODO: contextvars.ContextVar = contextvars.ContextVar("curva_modo", default=None)
_lock = threading.Lock()
_cache: dict = {}


def config() -> dict:
    with db.engine.connect() as c:
        v = c.execute(select(db.configuracoes.c.valor).where(db.configuracoes.c.chave == "curva_abc")).scalar()
    cfg = {**PADRAO, **(json.loads(v) if v else {})}
    return cfg


def salvar_config(**kw) -> dict:
    cfg = config()
    if kw.get("meses") in (1, 3, 6, 12):
        cfg["meses"] = int(kw["meses"])
    if kw.get("criterio") in ("faturamento", "unidades"):
        cfg["criterio"] = kw["criterio"]
    a, b = kw.get("limite_a", cfg["limite_a"]), kw.get("limite_b", cfg["limite_b"])
    if not (50 <= float(a) < float(b) <= 99.9):
        raise ValueError("Use limites entre 50% e 99,9%, com o da curva A menor que o da B.")
    cfg["limite_a"], cfg["limite_b"] = float(a), float(b)
    with db.engine.begin() as c:
        c.execute(delete(db.configuracoes).where(db.configuracoes.c.chave == "curva_abc"))
        c.execute(insert(db.configuracoes).values(chave="curva_abc", valor=json.dumps(cfg)))
    return cfg


def meses_base(d, n):
    """Últimos n meses com venda (inclui o mês parcial, como a base de demanda)."""
    return list(d.meses[-n:]) if d.meses else []


def classificar(d, cfg=None) -> dict:
    """{'classes': {modelo: 'A'|'B'|'C'}, 'tabela': DataFrame ordenado, 'meses': [...] }"""
    cfg = cfg or config()
    chave = (d.versao, json.dumps(cfg, sort_keys=True))
    with _lock:
        if _cache.get("k") == chave:
            return _cache["v"]
    meses = meses_base(d, int(cfg["meses"]))
    V = d.V[d.V["mes"].isin(meses)] if not d.V.empty else d.V
    col = "fat" if cfg["criterio"] == "faturamento" else "un"
    g = V.groupby("k_modelo").agg(fat=("fat", "sum"), un=("un", "sum"), cat=("categoria", "first")) if not V.empty \
        else pd.DataFrame(columns=["fat", "un", "cat"])
    g = g[g[col] > 0].sort_values(col, ascending=False)
    # uma curva por categoria (calçados x outros produtos): cada uma soma 100%
    partes = []
    for _, h in g.groupby("cat", sort=False):
        h = h.copy()
        tot = h[col].sum()
        acum = h[col].cumsum() / tot * 100
        ant = acum.shift(fill_value=0)   # o item que cruza o limite entra na faixa de cima
        h["classe"] = np.where(ant < cfg["limite_a"], "A", np.where(ant < cfg["limite_b"], "B", "C"))
        h["acum"], h["part"] = acum, h[col] / tot * 100
        partes.append(h)
    g = pd.concat(partes) if partes else g.assign(classe=[], acum=[], part=[])
    v = {"classes": g["classe"].to_dict(), "tabela": g, "meses": meses, "criterio": cfg["criterio"], "cfg": cfg}
    with _lock:
        _cache["k"], _cache["v"] = chave, v
    return v


def classe(classes: dict, chave) -> str:
    """Classe de um modelo; um modelo comprado sem cabedal (ex.: 7208.101) herda a melhor classe dos seus cabedais."""
    if chave in classes:
        return classes[chave]
    s = str(chave)
    filhos = [v for k, v in classes.items() if str(k).startswith(s + "-")]
    return min(filhos) if filhos else "–"


def mascara(chaves: pd.Series, modo: str, classes: dict) -> pd.Series:
    ok = FILTROS[modo]
    cache = {}
    def f(k):
        if k not in cache:
            cache[k] = classe(classes, k) in ok
        return cache[k]
    return chaves.map(f).astype(bool) if len(chaves) else pd.Series([], dtype=bool, index=chaves.index)


def filtrar_dados(d, base, modo):
    """Filtra `d` pela curva calculada sobre `base` (sempre os dados completos)."""
    from dataclasses import replace
    classes = classificar(base)["classes"]
    def f(df, col):
        if df is None or df.empty or col not in df:
            return df
        return df[mascara(df[col], modo, classes)]
    return replace(d, V=f(d.V, "k_modelo"), P=f(d.P, "k_modelo"), E=f(d.E, "k_modelo"),
                   C=f(d.C, "modelo"), L=f(d.L, "k_modelo"))
