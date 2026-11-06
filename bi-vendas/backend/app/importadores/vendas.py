"""Importação do relatório mensal de vendas (formato largo: SKU x meses).

Abas reconhecidas (mapeáveis):
    unidades        -> unidades vendidas (total)            [obrigatória]
    faturamento     -> faturamento (total)                  [obrigatória]
    unidades_ml     -> unidades Mercado Livre               [opcional]
    unidades_shopee -> unidades Shopee                      [opcional]
    pecas           -> "visão compra" (kits em peças)       [opcional]

Chave de deduplicação: (SKU canônico, mês). Reimportar um mês já existente
atualiza os valores (ex.: mês parcial) e registra o valor anterior para desfazer.
"""
from __future__ import annotations

import calendar
import re
from datetime import date

from sqlalchemy import insert, select, update

from .. import db
from ..produto import interpretar
from .comum import Resumo, achar_coluna, normalizar_texto, numero, texto

MESES = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8,
         "set": 9, "out": 10, "nov": 11, "dez": 12}
MES_RE = re.compile(r"^(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-z]*[/\-\s]*(\d{2,4})", re.I)

CAMPOS = {
    "unidades": ("unidades - total", "unidades total"),
    "faturamento": ("faturamento - total", "faturamento"),
    "unidades_ml": ("unidades - mercado livre", "mercado livre"),
    "unidades_shopee": ("unidades - shopee", "shopee"),
    "pecas": ("unid. visao compra", "visao compra"),
}


def parece_vendas(abas) -> bool:
    for df in abas.values():
        if any(MES_RE.match(normalizar_texto(c)) for c in df.columns) and achar_coluna(df.columns, "sku"):
            return True
    return False


def sugerir_mapeamento(abas) -> dict:
    nomes = list(abas.keys())
    abas_map = {}
    usados = set()
    for campo, cands in CAMPOS.items():
        for cand in cands:
            achado = next((n for n in nomes if n not in usados and cand in normalizar_texto(n)), None)
            if achado:
                abas_map[campo] = achado
                usados.add(achado)
                break
    if "unidades" not in abas_map and len(nomes) == 1:
        abas_map["unidades"] = nomes[0]
    primeira = abas[abas_map.get("unidades", nomes[0])]
    return {
        "abas": abas_map,
        "coluna_sku": achar_coluna(primeira.columns, "SKU", "codigo do produto", "codigo"),
        "coluna_descricao": achar_coluna(primeira.columns, "Produto", "descricao", "nome"),
        "coluna_curva": achar_coluna(primeira.columns, "Curva"),
    }


def colunas_mes(colunas):
    out = []
    for c in colunas:
        m = MES_RE.match(normalizar_texto(c))
        if not m:
            continue
        ano = int(m.group(2))
        ano = ano + 2000 if ano < 100 else ano
        out.append((c, date(ano, MESES[m.group(1).lower()[:3]], 1), "parcial" in normalizar_texto(c)))
    return out


def _dias(mes: date, parcial: bool, data_ref: date) -> int:
    total = calendar.monthrange(mes.year, mes.month)[1]
    if not parcial:
        return total
    if data_ref.year == mes.year and data_ref.month == mes.month:
        return max(1, data_ref.day)
    return total


def _ler_aba(df, mapeamento, campo, res: Resumo, aba_nome, chave_fn):
    """Retorna {(chave, mes): valor}, metadados de meses e descrições."""
    col_sku = mapeamento.get("coluna_sku") or achar_coluna(df.columns, "SKU")
    if not col_sku or col_sku not in df.columns:
        res.avisos.append(f"Aba '{aba_nome}': coluna de SKU não encontrada; aba ignorada.")
        return {}, [], {}
    meses = colunas_mes(df.columns)
    if not meses:
        res.avisos.append(f"Aba '{aba_nome}': nenhuma coluna de mês reconhecida (ex.: 'jan/26').")
        return {}, [], {}
    col_desc = mapeamento.get("coluna_descricao")
    col_curva = mapeamento.get("coluna_curva")
    valores, meta = {}, {}
    for i, row in enumerate(df.itertuples(index=False), start=2):
        r = dict(zip(df.columns, row))
        bruto = texto(r.get(col_sku))
        if not bruto or bruto.upper() in {"TOTAL", "TOTAL GERAL"}:
            res.ignorados += 1
            continue
        chave, aviso = chave_fn(bruto)
        if aviso:
            res.detalhes.setdefault("skus_ajustados", {})[bruto] = chave
        meta.setdefault(chave, {"descricao": texto(r.get(col_desc)) if col_desc else "",
                                "curva": texto(r.get(col_curva)) if col_curva else ""})
        for col, mes, _parc in meses:
            try:
                v = numero(r.get(col))
            except (ValueError, TypeError):
                res.erro(i, f"valor não numérico em {col}", texto(r.get(col)), aba_nome)
                continue
            if v is None:
                continue
            if v < 0:
                res.erro(i, f"valor negativo em {col}", v, aba_nome)
                continue
            valores[(chave, mes)] = valores.get((chave, mes), 0.0) + v
    return valores, meses, meta


def _chave_produto(bruto):
    p = interpretar(bruto, com_tamanho="auto")
    return p.sku, bool(p.avisos)


def importar(conn, abas, mapeamento, params, importacao_id) -> Resumo:
    res = Resumo("vendas")
    data_ref: date = params["data_referencia"]
    abas_map = mapeamento.get("abas", {})
    if "unidades" not in abas_map or abas_map["unidades"] not in abas:
        res.avisos.append("Aba de unidades (total) não mapeada — nada importado.")
        res.rejeitados += 1
        return res

    dados, meses_info, metas = {}, {}, {}
    for campo in ("unidades", "faturamento", "unidades_ml", "unidades_shopee"):
        nome = abas_map.get(campo)
        if not nome:
            continue
        if nome not in abas:
            res.avisos.append(f"Aba '{nome}' mapeada para {campo} não existe no arquivo.")
            continue
        v, meses, meta = _ler_aba(abas[nome], mapeamento, campo, res, nome, _chave_produto)
        dados[campo] = v
        for _, mes, parc in meses:
            meses_info[mes] = meses_info.get(mes, False) or parc
        for k, m in meta.items():
            metas.setdefault(k, m)
    if "faturamento" not in dados:
        res.avisos.append("Aba de faturamento não mapeada: faturamento e preço médio ficarão sem dados.")

    # Validação cruzada Total = ML + Shopee
    if "unidades_ml" in dados and "unidades_shopee" in dados:
        dif = 0
        for k, v in dados["unidades"].items():
            soma = dados["unidades_ml"].get(k, 0) + dados["unidades_shopee"].get(k, 0)
            if abs(soma - v) > 0.001:
                dif += 1
        if dif:
            res.avisos.append(f"{dif} combinações SKU/mês em que Total ≠ Mercado Livre + Shopee.")
        res.detalhes["conferencia_canais"] = "ok" if not dif else f"{dif} divergências"

    sem_fat = sum(1 for k, v in dados["unidades"].items()
                  if v > 0 and "faturamento" in dados and not dados["faturamento"].get(k))
    if sem_fat:
        res.avisos.append(f"{sem_fat} combinações SKU/mês com unidades mas sem faturamento.")

    # Produtos
    existentes = {r.sku: r for r in conn.execute(select(db.produtos))}
    novos = 0
    for sku, m in metas.items():
        if sku in existentes:
            if m["descricao"] and not existentes[sku].descricao:
                conn.execute(update(db.produtos).where(db.produtos.c.id == existentes[sku].id)
                             .values(descricao=m["descricao"][:500]))
            continue
        p = interpretar(sku, com_tamanho=False)
        rid = conn.execute(insert(db.produtos).values(
            sku=sku, categoria=p.categoria, modelo=p.modelo, cabedal=p.cabedal, cor=p.cor,
            descricao=(m["descricao"] or "")[:500])).inserted_primary_key[0]
        existentes[sku] = type("P", (), {"id": rid, "sku": sku, "descricao": m["descricao"]})
        novos += 1
    res.detalhes["produtos_novos"] = novos
    pid = {k: v.id for k, v in existentes.items()}

    atuais = {(r.produto_id, r.mes): r for r in conn.execute(select(db.vendas_mensais))}
    chaves = set(dados["unidades"])
    for campo in ("faturamento", "unidades_ml", "unidades_shopee"):
        chaves |= set(dados.get(campo, {}))
    for sku, mes in sorted(chaves):
        parc = meses_info.get(mes, False)
        novo = {
            "unidades": dados["unidades"].get((sku, mes), 0.0),
            "faturamento": dados.get("faturamento", {}).get((sku, mes)),
            "unidades_ml": dados.get("unidades_ml", {}).get((sku, mes)),
            "unidades_shopee": dados.get("unidades_shopee", {}).get((sku, mes)),
            "parcial": parc, "dias_cobertos": _dias(mes, parc, data_ref),
            "curva": (metas.get(sku, {}).get("curva") or None),
        }
        atual = atuais.get((pid[sku], mes))
        _upsert(conn, db.vendas_mensais, atual, novo,
                {"produto_id": pid[sku], "mes": mes}, importacao_id, res,
                vazio=not any(novo[c] for c in ("unidades", "faturamento")))

    # Visão compra (peças)
    nome_pecas = abas_map.get("pecas")
    if nome_pecas and nome_pecas in abas:
        sub = Resumo("pecas")
        v, meses, _ = _ler_aba(abas[nome_pecas], mapeamento, "pecas", sub, nome_pecas, _chave_produto)
        atuais_p = {(r.sku, r.mes): r for r in conn.execute(select(db.demanda_pecas))}
        parc_p = {mes: parc for _, mes, parc in meses}
        for (sku, mes), qtd in sorted(v.items()):
            parc = parc_p.get(mes, False)
            novo = {"unidades": qtd, "parcial": parc, "dias_cobertos": _dias(mes, parc, data_ref)}
            _upsert(conn, db.demanda_pecas, atuais_p.get((sku, mes)), novo,
                    {"sku": sku, "mes": mes}, importacao_id, sub, vazio=not qtd)
        res.detalhes["pecas"] = {"adicionados": sub.adicionados, "atualizados": sub.atualizados,
                                 "duplicados": sub.duplicados, "rejeitados": sub.rejeitados}
        res.erros.extend(sub.erros[:50])
        res.rejeitados += sub.rejeitados

    meses_ord = sorted(meses_info)
    res.detalhes["meses"] = [m.isoformat() for m in meses_ord]
    res.detalhes["meses_parciais"] = [m.isoformat() for m in meses_ord if meses_info[m]]
    res.detalhes["skus"] = len(metas)
    return res


def _igual(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-6
    return a == b


def _upsert(conn, tabela, atual, novo, chave, importacao_id, res: Resumo, vazio=False):
    if atual is None:
        if vazio:
            return
        rid = conn.execute(insert(tabela).values(**chave, **novo, importacao_id=importacao_id)
                           ).inserted_primary_key[0]
        conn.execute(insert(db.alteracoes).values(importacao_id=importacao_id, tabela=tabela.name,
                                                  registro_id=rid, antes=None))
        res.adicionados += 1
        return
    atual_d = dict(atual._mapping)
    if all(_igual(atual_d.get(k), v) for k, v in novo.items()):
        res.duplicados += 1
        return
    conn.execute(insert(db.alteracoes).values(importacao_id=importacao_id, tabela=tabela.name,
                                              registro_id=atual_d["id"], antes=db.dumps(atual_d)))
    conn.execute(update(tabela).where(tabela.c.id == atual_d["id"])
                 .values(**novo, importacao_id=importacao_id))
    res.atualizados += 1
