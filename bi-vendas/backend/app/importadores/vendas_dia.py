"""Importação de vendas por período: planilha simples com SKU x quantidade vendida
(ex.: "lista de produtos vendidos" do dia), opcionalmente de um canal.

Campos: codigo (SKU/código do produto), quantidade (vendas). Obrigatórios.
         ticket_medio (valor médio por unidade). Opcional: com ele, faturamento = vendas x ticket;
         sem ele (ou com a célula vazia), o faturamento é estimado pelo preço médio histórico.
Parâmetros: canal (ml | shopee | nao_informado), conta (opcional, ex.: loja ou CNPJ),
periodo_inicio, periodo_fim (padrão: a data de referência, ou seja, um dia só).

Os códigos são ligados ao SKU do BI pela mesma regra do estoque (inclui vínculos manuais).
Reimportar o mesmo canal, conta e período substitui o lançamento anterior.
As unidades entram nos indicadores somadas às vendas mensais, só nos dias que o
relatório mensal ainda não cobre (ver indicadores._somar_lancamentos).
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from sqlalchemy import delete, func, insert, select

from .. import db
from .comum import Resumo, achar_coluna, normalizar_texto, numero, texto
from .estoque import skus_conhecidos, vincular

CANAIS = {"ml": "Mercado Livre", "shopee": "Shopee", "nao_informado": "Canal não informado"}
CAMPOS = {"codigo": ("SKU", "codigo do produto", "codigo", "sku do produto"),
          "quantidade": ("Vendas", "vendidos", "quantidade vendida", "quantidade", "qtd", "unidades"),
          "ticket_medio": ("Ticket médio", "ticket medio", "ticket", "preco medio", "preço médio", "valor medio")}
OBRIGATORIOS = ("codigo", "quantidade")


def parece_vendas_dia(abas, nome: str = "") -> bool:
    df = next(iter(abas.values()))
    cols = [normalizar_texto(c) for c in df.columns]
    tem_sku = achar_coluna(df.columns, "SKU", "codigo do produto", "codigo")
    tem_venda = any(c.startswith("venda") or "vendid" in c for c in cols)
    return bool(tem_sku and (tem_venda or ("vend" in normalizar_texto(nome) and achar_coluna(df.columns, "quantidade", "qtd"))))


def sugerir_mapeamento(abas) -> dict:
    nome = next(iter(abas))
    df = abas[nome]
    return {"aba": nome, "colunas": {k: achar_coluna(df.columns, *v) for k, v in CAMPOS.items()}}


def _data(v, padrao: date) -> date:
    if not v:
        return padrao
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def periodo(params) -> tuple[date, date]:
    ref = params["data_referencia"]
    ini = _data(params.get("periodo_inicio"), ref)
    fim = _data(params.get("periodo_fim"), ini if params.get("periodo_inicio") else ref)
    if fim < ini:
        ini, fim = fim, ini
    return ini, fim


def rotulo(canal: str, ini: date, fim: date, conta: str = "") -> str:
    p = f"{ini:%d/%m/%Y}" if ini == fim else f"{ini:%d/%m/%Y}-{fim:%d/%m/%Y}"
    c = f" ({conta})" if conta else ""
    return f"{CANAIS.get(canal, canal)}{c} {p}"[:60]


def importar(conn, abas, mapeamento, params, importacao_id) -> Resumo:
    res = Resumo("vendas_dia")
    canal = params.get("canal") or "nao_informado"
    if canal not in CANAIS:
        res.avisos.append("Canal inválido; use Mercado Livre, Shopee ou não informado.")
        res.rejeitados += 1
        return res
    ini, fim = periodo(params)
    conta = (params.get("conta") or "").strip()[:60]
    somar = str(params.get("somar_sempre")).lower() in ("1", "true", "sim", "on")
    if (fim - ini).days > 366:
        res.avisos.append("O período passa de um ano; confira as datas.")
        res.rejeitados += 1
        return res
    aba = mapeamento.get("aba")
    if aba not in abas:          # mapeamento salvo de um arquivo com outro nome de aba
        aba = next(iter(abas))
    df = abas.get(aba)
    cols = mapeamento.get("colunas", {})
    c_cod, c_qtd = cols.get("codigo"), cols.get("quantidade")
    c_tk = cols.get("ticket_medio")
    if df is None or c_cod not in df.columns or c_qtd not in df.columns:
        res.avisos.append("Colunas de SKU e de quantidade vendida precisam ser mapeadas.")
        res.rejeitados += 1
        return res
    if c_tk and c_tk not in df.columns:
        c_tk = None

    manuais = {r.codigo: (r.sku, r.tamanho) for r in conn.execute(select(db.vinculos))}
    conhecidos = skus_conhecidos(conn)
    linhas, somas = [], {}
    usar = [c_cod, c_qtd] + ([c_tk] if c_tk else [])
    for i, row in enumerate(df[usar].itertuples(index=False), start=2):
        cod = texto(row[0])
        if not cod or cod.upper() in {"TOTAL", "TOTAL GERAL"}:
            res.ignorados += 1
            continue
        try:
            q = numero(row[1])
        except (ValueError, TypeError):
            res.erro(i, "quantidade não numérica", texto(row[1]))
            continue
        if not q:
            res.ignorados += 1
            continue
        if q < 0:
            res.erro(i, "quantidade negativa", q)
            continue
        tk = None
        if c_tk:
            try:
                tk = numero(row[2])
            except (ValueError, TypeError):
                res.avisos.append(f"Linha {i}: ticket médio '{texto(row[2])}' não é um número; faturamento estimado.")
                tk = None
            if tk is not None and tk < 0:
                res.avisos.append(f"Linha {i}: ticket médio negativo em {cod}; faturamento estimado.")
                tk = None
        fat = q * tk if tk is not None else None
        if cod in somas:
            res.avisos.append(f"Linha {i}: código {cod} repetido no arquivo; quantidades somadas.")
            it = somas[cod]
            it["unidades"] += q
            # só soma o faturamento se as duas linhas trouxerem ticket
            it["faturamento"] = (it["faturamento"] + fat) if (it["faturamento"] is not None and fat is not None) else None
            continue
        sku, tam, origem = vincular(cod, manuais, conhecidos)
        item = {"codigo": cod, "sku": sku, "tamanho": tam, "unidades": q, "faturamento": fat, "vinculo": origem}
        somas[cod] = item
        linhas.append(item)

    # Substitui o lançamento anterior do mesmo canal e período (fica registrado para desfazer)
    cond = ((db.vendas_lancamentos.c.canal == canal) & (db.vendas_lancamentos.c.conta == conta)
            & (db.vendas_lancamentos.c.data_inicio == ini) & (db.vendas_lancamentos.c.data_fim == fim))
    anteriores = list(conn.execute(select(db.vendas_lancamentos).where(cond)))
    for a in anteriores:
        conn.execute(insert(db.alteracoes).values(importacao_id=importacao_id, tabela="vendas_lancamentos",
                                                  registro_id=a.id, antes=db.dumps(dict(a._mapping))))
    if anteriores:
        conn.execute(delete(db.vendas_lancamentos).where(cond))
        res.atualizados = len(anteriores)
        res.avisos.append(f"Já havia vendas de {rotulo(canal, ini, fim, conta)}: o lançamento anterior foi substituído por este arquivo. "
                          "Se for outra conta/loja, informe a conta para os dois ficarem guardados.")

    sobre = conn.execute(select(func.count()).select_from(db.vendas_lancamentos).where(
        (db.vendas_lancamentos.c.canal == canal) & (db.vendas_lancamentos.c.conta == conta)
        & (db.vendas_lancamentos.c.data_inicio <= fim)
        & (db.vendas_lancamentos.c.data_fim >= ini))).scalar()
    if sobre:
        res.avisos.append(f"Já existem vendas de {CANAIS[canal]}{' (' + conta + ')' if conta else ''} lançadas em dias deste período (com outras datas de início/fim). "
                          "Esses dias ficariam contados duas vezes; desfaça o lançamento antigo em Histórico de importações se for o caso.")

    for it in linhas:
        rid = conn.execute(insert(db.vendas_lancamentos).values(
            importacao_id=importacao_id, codigo=it["codigo"][:160], sku=it["sku"], tamanho=it["tamanho"],
            canal=canal, conta=conta, data_inicio=ini, data_fim=fim, unidades=it["unidades"],
            faturamento=it["faturamento"], somar_sempre=somar)).inserted_primary_key[0]
        conn.execute(insert(db.alteracoes).values(importacao_id=importacao_id, tabela="vendas_lancamentos",
                                                  registro_id=rid, antes=None))
    res.adicionados = len(linhas)

    # Dias que o relatório mensal já cobre não são somados de novo
    cob = {}
    for r in conn.execute(select(db.vendas_mensais.c.mes, func.max(db.vendas_mensais.c.dias_cobertos))
                          .group_by(db.vendas_mensais.c.mes)):
        cob[r[0]] = r[1] or calendar.monthrange(r[0].year, r[0].month)[1]
    dias = [ini + timedelta(days=k) for k in range((fim - ini).days + 1)]
    cobertos = [d for d in dias if d.replace(day=1) in cob and d.day <= cob[d.replace(day=1)]]
    total = sum(it["unidades"] for it in linhas)
    if cobertos and somar:
        res.avisos.append(f"{len(cobertos)} dia(s) do período também estão no relatório mensal e serão somados mesmo assim "
                          "(opção 'somar mesmo assim' marcada).")
    elif cobertos:
        txt = ("Todos os dias deste período já estão no relatório mensal de vendas: o lançamento aparece nos gráficos por dia e por semana, "
               "mas não muda o resultado do mês (para não contar a venda duas vezes).") if len(cobertos) == len(dias) else (
               f"{len(cobertos)} de {len(dias)} dias do período já estão no relatório mensal; só os outros dias mudam o resultado do mês.")
        res.avisos.append(txt + " Se o relatório mensal ainda não tem as vendas destes dias, marque 'Somar mesmo assim'.")

    com_tk = [it for it in linhas if it["faturamento"] is not None]
    if c_tk and len(com_tk) < len(linhas):
        res.avisos.append(f"{len(linhas) - len(com_tk)} códigos sem ticket médio: o faturamento deles é estimado pelo preço médio de cada produto.")
    elif not c_tk:
        res.avisos.append("A planilha não tem coluna de ticket médio: o faturamento é estimado pelo preço médio de cada produto.")
    sem = [it for it in linhas if it["vinculo"] == "proprio"]
    res.detalhes.update({
        "canal": CANAIS[canal], "conta": conta, "periodo": [ini.isoformat(), fim.isoformat()], "dias": len(dias),
        "faturamento_informado": round(sum(it["faturamento"] for it in com_tk), 2),
        "unidades_com_ticket": sum(it["unidades"] for it in com_tk), "codigos_com_ticket": len(com_tk),
        "ticket_medio": round(sum(it["faturamento"] for it in com_tk) / sum(it["unidades"] for it in com_tk), 2) if com_tk else None,
        "unidades": total, "codigos": len(linhas), "skus": len({it["sku"] for it in linhas}),
        "dias_ja_no_relatorio_mensal": len(cobertos), "somar_sempre": somar,
        "relatorio_mensal_ate": (lambda x: x.isoformat() if x else None)(max((m + timedelta(days=c - 1) for m, c in cob.items()), default=None)),
        "sem_vinculo": len(sem), "unidades_sem_vinculo": sum(it["unidades"] for it in sem),
    })
    if sem:
        res.avisos.append(f"{len(sem)} códigos ({sum(it['unidades'] for it in sem):.0f} un.) não correspondem a nenhum SKU conhecido; "
                          "entram como produtos próprios. Ligue-os em Dados › Vínculos de estoque se forem o mesmo produto.")
    return res
