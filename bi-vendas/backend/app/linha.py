"""Produtos em linha / fora de linha: marcação por modelo e filtro global.

O filtro vem do parâmetro `linha` de qualquer requisição (em_linha | fora | sem_marcacao),
guardado num contextvar pelo middleware. `indicadores.dados()` e `pedidos.carregar()` aplicam
o filtro, então todas as telas e relatórios respeitam a escolha.
"""
from __future__ import annotations

import contextvars
import threading
from dataclasses import replace
from datetime import datetime

import pandas as pd
from sqlalchemy import delete, func, insert, select

from . import db

MODOS = {"em_linha": "Em linha", "fora": "Fora de linha", "sem_marcacao": "Sem marcação"}
MODO: contextvars.ContextVar = contextvars.ContextVar("linha_modo", default=None)

_lock = threading.Lock()
_cache: dict = {}


def versao() -> tuple:
    with db.engine.connect() as c:
        r = c.execute(select(func.count(), func.max(db.produtos_linha.c.atualizado_em))).first()
    return (r[0], str(r[1]))


def marcas() -> dict:
    """chave -> True (em linha) / False (fora de linha)."""
    v = versao()
    with _lock:
        if _cache.get("v") == v:
            return _cache["m"]
    with db.engine.connect() as c:
        m = {r.chave: bool(r.em_linha) for r in c.execute(select(db.produtos_linha))}
    with _lock:
        _cache["v"], _cache["m"] = v, m
    return m


def estado(chave, m=None):
    """True/False/None. Um modelo comprado sem cabedal (ex.: 7208.101) herda a marcação
    quando todos os seus cabedais marcados concordam."""
    m = marcas() if m is None else m
    if chave in m:
        return m[chave]
    chave = str(chave)
    filhos = {v for k, v in m.items() if k.startswith(chave + "-")}
    if len(filhos) == 1:
        return filhos.pop()
    base = chave.rsplit("-", 1)[0] if "-" in chave else None
    if base and base in m and "." in base:
        return m[base]
    return None


def mascara(chaves: pd.Series, modo: str, m=None) -> pd.Series:
    m = marcas() if m is None else m
    cache = {}
    def ok(k):
        if k not in cache:
            e = estado(k, m)
            cache[k] = (e is True) if modo == "em_linha" else (e is False) if modo == "fora" else (e is None)
        return cache[k]
    return chaves.map(ok).astype(bool) if len(chaves) else pd.Series([], dtype=bool, index=chaves.index)


def filtrar_dados(d, modo):
    m = marcas()
    def f(df, col):
        if df is None or df.empty or col not in df:
            return df
        return df[mascara(df[col], modo, m)]
    return replace(d, V=f(d.V, "k_modelo"), P=f(d.P, "k_modelo"), E=f(d.E, "k_modelo"),
                   C=f(d.C, "modelo"), L=f(d.L, "k_modelo"))


def definir(chaves, em_linha) -> int:
    chaves = [str(c).strip() for c in chaves if str(c).strip()]
    with db.engine.begin() as c:
        c.execute(delete(db.produtos_linha).where(db.produtos_linha.c.chave.in_(chaves)))
        if em_linha is not None:
            agora = datetime.utcnow()
            c.execute(insert(db.produtos_linha), [{"chave": k[:160], "em_linha": bool(em_linha), "atualizado_em": agora} for k in chaves])
    return len(chaves)
