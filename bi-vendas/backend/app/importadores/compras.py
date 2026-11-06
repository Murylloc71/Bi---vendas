"""Importação de compras (itens de notas fiscais de entrada).

Modalidade:
    PE   (pronta-entrega) -> "Preço com desconto" == "Valor Unitário" (preço já negociado)
    PROG (programado)     -> preços diferentes (desconto aplicado na nota)

Chave de deduplicação: nota (nº da nota, se mapeado; senão fornecedor+data+valores da nota)
+ EAN + ocorrência do EAN na nota.

Modos:
    acrescentar  -> insere linhas novas; linhas já existentes são duplicadas ou atualizadas
    substituir   -> apaga as compras do período coberto pelo arquivo e grava o arquivo
                    (use ao reexportar um período, por exemplo para incluir a quantidade)
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, insert, select, update

from .. import db
from ..produto import interpretar
from .comum import Resumo, achar_coluna, data_valor, numero, texto

CAMPOS = {
    "fornecedor": ("Nome PJ Emitente", "fornecedor", "emitente"),
    "data": ("Data Emissão", "data emissao", "Data da manifestação", "data"),
    "numero_nota": ("Número da Nota", "numero nota", "nº nota", "numero nf"),
    "valor_nota": ("Valor Total da Nota",),
    "valor_produtos": ("Valor Total Produtos",),
    "ean": ("[Item] EAN", "ean"),
    "sku": ("SKU", "[Item] Código", "codigo"),
    "valor_unitario": ("[Item] Valor Unitário", "valor unitario"),
    "preco_desconto": ("Preço com desconto", "preco com desconto"),
    "quantidade": ("[Item] Quantidade", "quantidade", "qtd", "qtde"),
}
OBRIGATORIOS = ("data", "valor_unitario", "sku")


def parece_compras(abas) -> bool:
    df = next(iter(abas.values()))
    return bool(achar_coluna(df.columns, "[Item] Valor Unitário", "valor unitario")
                and achar_coluna(df.columns, "Nome PJ Emitente", "Valor Total da Nota"))


def sugerir_mapeamento(abas) -> dict:
    nome = next(iter(abas))
    df = abas[nome]
    cols = {}
    for k, cands in CAMPOS.items():
        cols[k] = achar_coluna(df.columns, *cands)
    # evita confundir "Valor Total da Nota"/"Produtos" com outras colunas
    return {"aba": nome, "colunas": cols}


def importar(conn, abas, mapeamento, params, importacao_id) -> Resumo:
    res = Resumo("compras")
    modo = params.get("modo") or "acrescentar"
    aba = mapeamento.get("aba")
    if aba not in abas:          # mapeamento salvo de um arquivo com outro nome de aba
        aba = next(iter(abas))
    df = abas.get(aba)
    cols = mapeamento.get("colunas", {})
    faltando = [c for c in OBRIGATORIOS if not cols.get(c) or cols[c] not in df.columns]
    if faltando:
        res.avisos.append("Campos obrigatórios não mapeados: " + ", ".join(faltando))
        res.rejeitados += 1
        return res
    if cols.get("data") and "manifest" in cols["data"].lower():
        res.avisos.append("A data usada é a de manifestação. Prefira a Data de Emissão para manter o mesmo critério em todos os arquivos.")
    if not cols.get("quantidade"):
        res.avisos.append("Arquivo sem coluna de quantidade: só será possível deduzir a quantidade em notas com um único modelo e preço.")

    def g(r, campo):
        c = cols.get(campo)
        return r.get(c) if c else None

    linhas, fora_padrao, nota_maior = [], [], set()
    for i, row in enumerate(df.itertuples(index=False), start=2):
        r = dict(zip(df.columns, row))
        try:
            data = data_valor(g(r, "data"))
            vu = numero(g(r, "valor_unitario"))
            pdsc = numero(g(r, "preco_desconto"))
            vnota = numero(g(r, "valor_nota"))
            vprod = numero(g(r, "valor_produtos"))
            qtd = numero(g(r, "quantidade"))
        except (ValueError, TypeError) as e:
            res.erro(i, str(e))
            continue
        if data is None:
            res.erro(i, "data vazia")
            continue
        if not vu or vu <= 0:
            res.erro(i, "valor unitário vazio ou zero", vu)
            continue
        if qtd is not None and qtd < 0:
            res.erro(i, "quantidade negativa", qtd)
            continue
        if pdsc is None:
            pdsc = vu * (vnota / vprod) if vnota and vprod else vu
        sku_o = texto(g(r, "sku"))
        p = interpretar(sku_o, com_tamanho=False)
        modelo = p.modelo if p.categoria == "calcado" else None
        sku_c = p.sku if (p.categoria == "calcado" and p.cor) else None
        if p.categoria != "calcado":
            fora_padrao.append(f"{i} ('{sku_o}')")
        if vnota and vprod and vnota > vprod * 1.0001:
            nota_maior.add(f"{data:%d/%m/%Y} R$ {vnota:,.2f} x R$ {vprod:,.2f}")
        forn = texto(g(r, "fornecedor"))
        num = texto(g(r, "numero_nota"))
        nota = f"{forn}|NF{num}" if num else f"{forn}|{data.isoformat()}|{vnota}|{vprod}"
        linhas.append({
            "linha": i, "nota_chave": nota[:200], "numero_nota": num or None, "data": data,
            "fornecedor": forn[:200], "ean": texto(g(r, "ean"))[:40], "sku_original": sku_o[:160],
            "modelo": modelo, "sku": sku_c, "valor_unitario": vu, "preco_desconto": pdsc,
            "valor_nota": vnota, "valor_produtos": vprod, "quantidade": qtd,
            "quantidade_origem": "arquivo" if qtd is not None else None,
            "modalidade": "PE" if abs(pdsc - vu) <= 0.005 else "PROG",
        })

    if fora_padrao:
        res.avisos.append(f"{len(fora_padrao)} linhas com SKU fora do padrão de modelo (mantidas sem modelo, "
                          f"fora do cálculo de economia). Linhas: {', '.join(fora_padrao[:8])}"
                          + (" ..." if len(fora_padrao) > 8 else ""))
    if nota_maior:
        res.avisos.append(f"{len(nota_maior)} nota(s) com valor total maior que o dos produtos: " + "; ".join(sorted(nota_maior)[:5]))

    # ocorrência do EAN dentro da nota + inferência de quantidade
    por_nota = defaultdict(list)
    for l in linhas:
        por_nota[l["nota_chave"]].append(l)
    identicas = 0
    inferidas = 0
    for nota, ls in por_nota.items():
        cont = defaultdict(int)
        for l in ls:
            cont[l["ean"]] += 1
            l["linha_chave"] = f"{nota}|{l['ean']}|{cont[l['ean']]}"[:300]
            if cont[l["ean"]] > 1:
                identicas += 1
        if all(l["quantidade"] is None for l in ls):
            precos = {round(l["valor_unitario"], 4) for l in ls}
            modelos = {l["modelo"] for l in ls}
            vprod = ls[0]["valor_produtos"]
            if len(precos) == 1 and len(modelos) == 1 and None not in modelos and vprod:
                total = vprod / ls[0]["valor_unitario"]
                if abs(total - round(total)) < 0.01:
                    for l in ls:
                        l["quantidade"] = round(total) / len(ls)
                        l["quantidade_origem"] = "inferida"
                    inferidas += 1
    if identicas:
        res.avisos.append(f"{identicas} linhas repetem o mesmo EAN na mesma nota; foram mantidas como itens distintos.")

    if not linhas:
        return res

    # modo substituir: remove compras do período
    if modo == "substituir":
        dmin, dmax = min(l["data"] for l in linhas), max(l["data"] for l in linhas)
        antigos = [dict(r._mapping) for r in conn.execute(
            select(db.compras).where(db.compras.c.data.between(dmin, dmax)))]
        for a in antigos:
            conn.execute(insert(db.alteracoes).values(importacao_id=importacao_id, tabela="compras",
                                                      registro_id=a["id"], antes=db.dumps(a)))
        conn.execute(delete(db.compras).where(db.compras.c.data.between(dmin, dmax)))
        res.detalhes["removidos_periodo"] = len(antigos)
        res.detalhes["periodo_substituido"] = [dmin.isoformat(), dmax.isoformat()]

    existentes = {r.linha_chave: r for r in conn.execute(select(db.compras))}
    campos = ("data", "fornecedor", "ean", "sku_original", "modelo", "sku", "valor_unitario",
              "preco_desconto", "valor_nota", "valor_produtos", "quantidade", "quantidade_origem",
              "modalidade", "numero_nota", "nota_chave")
    novas = []
    for l in linhas:
        reg = {k: l[k] for k in campos}
        atual = existentes.get(l["linha_chave"])
        if atual is None:
            novas.append({**reg, "linha_chave": l["linha_chave"], "importacao_id": importacao_id})
            continue
        a = dict(atual._mapping)
        if all((a[k] == reg[k]) or (isinstance(reg[k], float) and a[k] is not None
                                   and abs(a[k] - reg[k]) < 1e-6) for k in campos):
            res.duplicados += 1
            continue
        conn.execute(insert(db.alteracoes).values(importacao_id=importacao_id, tabela="compras",
                                                  registro_id=a["id"], antes=db.dumps(a)))
        conn.execute(update(db.compras).where(db.compras.c.id == a["id"]).values(**reg, importacao_id=importacao_id))
        res.atualizados += 1
    if novas:
        res_ids = []
        for bloco in range(0, len(novas), 1000):
            conn.execute(insert(db.compras), novas[bloco:bloco + 1000])
        # marca inserções para desfazer
        chaves = [n["linha_chave"] for n in novas]
        for bloco in range(0, len(chaves), 500):
            for r in conn.execute(select(db.compras.c.id).where(db.compras.c.linha_chave.in_(chaves[bloco:bloco + 500]))):
                res_ids.append({"importacao_id": importacao_id, "tabela": "compras", "registro_id": r.id, "antes": None})
        if res_ids:
            conn.execute(insert(db.alteracoes), res_ids)
        res.adicionados = len(novas)

    res.detalhes.update({
        "notas": len(por_nota), "linhas": len(linhas),
        "pe": sum(1 for l in linhas if l["modalidade"] == "PE"),
        "prog": sum(1 for l in linhas if l["modalidade"] == "PROG"),
        "notas_quantidade_inferida": inferidas,
        "linhas_sem_quantidade": sum(1 for l in linhas if l["quantidade"] is None),
        "periodo": [min(l["data"] for l in linhas).isoformat(), max(l["data"] for l in linhas).isoformat()],
    })
    return res
