"""Importação de posição de estoque (foto do saldo em uma data, por depósito).

Campos: codigo (obrigatório), quantidade (obrigatório).
Parâmetros: deposito, data_referencia.
Reimportar o mesmo depósito na mesma data substitui a foto anterior (com registro para desfazer).
"""
from __future__ import annotations

from sqlalchemy import delete, insert, select

from .. import db
from ..produto import interpretar, vincular_outro
from .comum import Resumo, achar_coluna, numero, texto

CAMPOS = {"codigo": ("Código do Produto", "codigo", "sku"),
          "quantidade": ("Quantidade Disponível", "quantidade", "saldo", "qtd")}


def parece_estoque(abas) -> bool:
    df = next(iter(abas.values()))
    return bool(achar_coluna(df.columns, "Código do Produto", "codigo")
                and achar_coluna(df.columns, "Quantidade Disponível", "quantidade", "saldo"))


def sugerir_mapeamento(abas) -> dict:
    nome = next(iter(abas))
    df = abas[nome]
    return {"aba": nome, "colunas": {k: achar_coluna(df.columns, *v) for k, v in CAMPOS.items()}}


def skus_conhecidos(conn) -> list[str]:
    s = {r.sku for r in conn.execute(select(db.produtos.c.sku).where(db.produtos.c.categoria == "outro"))}
    s |= {r.sku for r in conn.execute(select(db.demanda_pecas.c.sku).distinct())}
    s = {x for x in s if interpretar(x).categoria == "outro"}
    return sorted(s, key=len, reverse=True)


def vincular(codigo: str, manuais: dict, conhecidos: list[str]):
    """Retorna (sku, tamanho, origem)."""
    if codigo in manuais:
        sku, tam = manuais[codigo]
        return sku, tam, "manual"
    p = interpretar(codigo, com_tamanho=True)
    if p.categoria == "calcado":
        return p.sku, p.tamanho, "padrao"
    r = vincular_outro(codigo, conhecidos)
    if r:
        return r[0], (r[1] or None), ("exato" if not r[1] else "sufixo")
    # Sem correspondência: o próprio código vira o produto (ex.: item sem venda no histórico)
    return interpretar(codigo).sku, None, "proprio"


def importar(conn, abas, mapeamento, params, importacao_id) -> Resumo:
    res = Resumo("estoque")
    deposito = (params.get("deposito") or "").strip()
    data_ref = params["data_referencia"]
    if not deposito:
        res.avisos.append("Informe o depósito.")
        res.rejeitados += 1
        return res
    aba = mapeamento.get("aba")
    if aba not in abas:          # mapeamento salvo de um arquivo com outro nome de aba
        aba = next(iter(abas))
    df = abas.get(aba)
    cols = mapeamento.get("colunas", {})
    c_cod, c_qtd = cols.get("codigo"), cols.get("quantidade")
    if df is None or c_cod not in df.columns or c_qtd not in df.columns:
        res.avisos.append("Colunas de código e quantidade precisam ser mapeadas.")
        res.rejeitados += 1
        return res

    manuais = {r.codigo: (r.sku, r.tamanho) for r in conn.execute(select(db.vinculos))}
    conhecidos = skus_conhecidos(conn)

    itens, vistos = [], {}
    for i, row in enumerate(df[[c_cod, c_qtd]].itertuples(index=False), start=2):
        cod = texto(row[0])
        if not cod:
            res.ignorados += 1
            continue
        try:
            q = numero(row[1])
        except (ValueError, TypeError):
            res.erro(i, "quantidade não numérica", texto(row[1]))
            continue
        if q is None:
            q = 0.0
        if q < 0:
            res.avisos.append(f"Linha {i}: quantidade negativa ({q}) em {cod} — mantida.")
        if cod in vistos:
            res.duplicados += 1
            if abs(vistos[cod] - q) > 1e-9:
                res.erro(i, "código repetido no arquivo com quantidade diferente", cod)
            continue
        vistos[cod] = q
        sku, tam, origem = vincular(cod, manuais, conhecidos)
        itens.append({"codigo": cod, "sku": sku, "tamanho": tam, "quantidade": q, "vinculo": origem})

    # Substitui foto da mesma data/depósito
    ant = conn.execute(select(db.estoque_snapshots).where(
        (db.estoque_snapshots.c.deposito == deposito) & (db.estoque_snapshots.c.data == data_ref))).first()
    if ant:
        antigos = [dict(r._mapping) for r in conn.execute(
            select(db.estoque_itens).where(db.estoque_itens.c.snapshot_id == ant.id))]
        conn.execute(insert(db.alteracoes).values(
            importacao_id=importacao_id, tabela="estoque_snapshots", registro_id=ant.id,
            antes=db.dumps({"snapshot": dict(ant._mapping), "itens": antigos})))
        conn.execute(delete(db.estoque_itens).where(db.estoque_itens.c.snapshot_id == ant.id))
        conn.execute(delete(db.estoque_snapshots).where(db.estoque_snapshots.c.id == ant.id))
        velhos = {a["codigo"]: a["quantidade"] for a in antigos}
        for it in itens:
            if it["codigo"] not in velhos:
                res.adicionados += 1
            elif abs(velhos[it["codigo"]] - it["quantidade"]) < 1e-9:
                res.duplicados += 1
            else:
                res.atualizados += 1
        res.avisos.append(f"Já havia estoque de {deposito} em {data_ref:%d/%m/%Y}: foto substituída.")
    else:
        res.adicionados = len(itens)

    sid = conn.execute(insert(db.estoque_snapshots).values(
        deposito=deposito, data=data_ref, importacao_id=importacao_id)).inserted_primary_key[0]
    conn.execute(insert(db.alteracoes).values(importacao_id=importacao_id, tabela="estoque_snapshots",
                                              registro_id=sid, antes=None))
    if itens:
        for it in itens:
            it["snapshot_id"] = sid
        conn.execute(insert(db.estoque_itens), itens)

    sem = [it for it in itens if it["vinculo"] == "proprio"]
    res.detalhes.update({
        "deposito": deposito, "data": data_ref.isoformat(), "codigos": len(itens),
        "quantidade_total": sum(it["quantidade"] for it in itens),
        "sem_vinculo": len(sem), "quantidade_sem_vinculo": sum(it["quantidade"] for it in sem),
        "por_vinculo": {k: sum(1 for it in itens if it["vinculo"] == k)
                        for k in ("padrao", "exato", "sufixo", "manual", "proprio")},
    })
    if sem:
        res.avisos.append(f"{len(sem)} códigos não correspondem a nenhum SKU vendido ({res.detalhes['quantidade_sem_vinculo']:.0f} un.). "
                          "Entram como produtos próprios (sem histórico de venda); se forem variações de um SKU vendido, vincule na área de Dados.")
    return res
