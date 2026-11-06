"""Itens comprados (relatório de notas sem preço por item):
Nome PJ Emitente | Data Emissão | Número | Valor Total da Nota | Valor Total Produtos | [Item] EAN

Cada linha é um item de uma nota. O BI guarda emitente, data, número e EAN; o SKU sai do EAN.
Reimportar não duplica. Notas que já estão nas planilhas de compras (mesma data e valor) não
contam duas vezes no calendário.
"""
from __future__ import annotations

import html

import pandas as pd
from sqlalchemy import insert, select

from .. import db
from .comum import Resumo, achar_coluna, normalizar_texto, numero, texto

CAMPOS = {
    "fornecedor": ("Nome PJ Emitente", "emitente", "fornecedor"),
    "data": ("Data Emissão", "data emissao", "emissao", "data"),
    "numero": ("Número", "numero", "numero da nota", "nf"),
    "valor_nota": ("Valor Total da Nota", "valor total nota", "valor da nota"),
    "ean": ("[Item] EAN", "ean", "item ean", "codigo de barras"),
}
OBRIGATORIOS = ("fornecedor", "data", "numero", "ean")


def parece_itens_compra(abas, nome: str = "") -> bool:
    df = next(iter(abas.values()))
    cols = {normalizar_texto(c) for c in df.columns}
    tem = any("emitente" in c for c in cols) and any("ean" in c for c in cols) and any(c in ("numero", "número") or c.startswith("numero") for c in cols)
    # a planilha de compras completa (com preço/SKU por item) segue pelo importador de compras
    completa = any("valor unitario" in c or c == "sku" or "preco com desconto" in c for c in cols)
    return tem and not completa


def sugerir_mapeamento(abas) -> dict:
    nome = next(iter(abas))
    df = abas[nome]
    return {"aba": nome, "colunas": {k: achar_coluna(df.columns, *v) for k, v in CAMPOS.items()}}


def traducao_ean(conn) -> dict:
    """EAN -> código/SKU já conhecido (planilhas de compras, Qive e pedidos do Omie)."""
    m = {}
    for e, s in conn.execute(select(db.compras.c.ean, db.compras.c.sku_original).where(db.compras.c.ean.isnot(None))):
        if e and s and s != "0" and e not in m:
            m[e] = s
    for e, c, s in conn.execute(select(db.omie_itens.c.ean, db.omie_itens.c.codigo, db.omie_itens.c.sku).where(db.omie_itens.c.ean.isnot(None))):
        if e and e not in m and (c or s):
            m[e] = c or s
    return m


def importar(conn, abas, mapeamento, params, importacao_id) -> Resumo:
    res = Resumo("itens_compra")
    aba = mapeamento.get("aba")
    if aba not in abas:
        aba = next(iter(abas))
    df = abas[aba]
    cols = mapeamento.get("colunas", {})
    faltando = [c for c in OBRIGATORIOS if not cols.get(c) or cols[c] not in df.columns]
    if faltando:
        res.avisos.append("Colunas obrigatórias não mapeadas: " + ", ".join(faltando))
        res.rejeitados += 1
        return res
    existentes = {r[0] for r in conn.execute(select(db.compras_itens.c.chave))}
    vistos, novos, seq = set(), [], {}
    for i, row in enumerate(df.itertuples(index=False), start=2):
        r = dict(zip(df.columns, row))
        forn = html.unescape(texto(r.get(cols["fornecedor"])) or "").strip()
        num = texto(r.get(cols["numero"]))
        ean = texto(r.get(cols["ean"]))
        try:
            dt = pd.to_datetime(r.get(cols["data"]), dayfirst=True)
            dt = None if pd.isna(dt) else dt.date()
        except (ValueError, TypeError):
            dt = None
        if not forn or not num or not dt or not ean:
            res.ignorados += 1
            continue
        num = num.split(".")[0] if num.replace(".", "").isdigit() else num
        ean = ean.split(".")[0]
        try:
            vn = numero(r.get(cols["valor_nota"])) if cols.get("valor_nota") in df.columns else None
        except (ValueError, TypeError):
            vn = None
        base = f"{forn}|{num}|{dt.isoformat()}|{ean}"
        seq[base] = seq.get(base, 0) + 1          # mesmo EAN em duas linhas da mesma nota
        chave = f"{base}|{seq[base]}"[:300]
        if chave in existentes or chave in vistos:
            res.duplicados += 1
            continue
        vistos.add(chave)
        novos.append({"importacao_id": importacao_id, "chave": chave, "fornecedor": forn[:200], "numero_nota": num[:60],
                      "data": dt, "valor_nota": vn, "ean": ean[:40]})
    for i in range(0, len(novos), 500):
        ids = conn.execute(insert(db.compras_itens).returning(db.compras_itens.c.id), novos[i:i + 500]).scalars().all()
        conn.execute(insert(db.alteracoes), [{"importacao_id": importacao_id, "tabela": "compras_itens", "registro_id": x, "antes": None} for x in ids])
    res.adicionados = len(novos)
    tr = traducao_ean(conn)
    eans = {n["ean"] for n in novos}
    sem = sorted(e for e in eans if e not in tr)
    notas = {(n["numero_nota"], n["data"]) for n in novos}
    res.detalhes.update({
        "notas": len(notas), "itens": len(novos),
        "periodo": [min(n["data"] for n in novos).isoformat(), max(n["data"] for n in novos).isoformat()] if novos else None,
        "eans": len(eans), "eans_identificados": len(eans) - len(sem), "eans_sem_sku": len(sem),
    })
    if sem:
        res.avisos.append(f"{len(sem)} EANs ainda sem SKU conhecido (aparecem como “EAN não identificado” no calendário). "
                          "Eles são reconhecidos sozinhos quando aparecerem numa planilha de compras completa, no Qive ou num pedido do Omie.")
    return res
