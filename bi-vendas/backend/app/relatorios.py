"""Tendência do estoque (está baixando?) e relatório de estoque em Excel."""
from __future__ import annotations

import io
from datetime import date, datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import indicadores as ind
from . import pedidos as pd_

f = ind._f

ROT_REPO = {"ruptura_sem_pedido": "Zerado sem pedido", "critico_sem_pedido": "Acabando sem pedido",
            "pedido_chega_tarde": "Pedido chega tarde", "ruptura_com_pedido": "Zerado com pedido",
            "coberto": "Coberto pelo pedido", "excesso": "Excesso", "sem_demanda": "Comprado sem venda recente", "ok": "OK"}
ROT_EST = {"ruptura": "Zerado", "critico": f"Menos de {ind.COBERTURA_CRITICA} dias", "ok": "OK",
           "excesso": f"Mais de {ind.COBERTURA_EXCESSO} dias", "sem_giro": "Sem venda", "inativo": "Inativo",
           "externo": "Estoque externo", "sem_cadastro": "Sem cadastro"}


# --------------------------------------------------------------------------- tendência
def _datas_fotos(d: ind.Dados) -> list:
    if d.E.empty:
        return []
    return sorted(pd.to_datetime(d.E["data"]).dt.normalize().unique())


def evolucao(d: ind.Dados, categoria="calcado", maximo=90) -> list:
    """Unidades totais em estoque em cada data com foto (soma dos depósitos vigentes naquela data)."""
    out = []
    for dt in _datas_fotos(d)[-maximo:]:
        E = ind._filtrar_cat(ind.estoque_em(d, pd.Timestamp(dt)), categoria)
        out.append({"data": pd.Timestamp(dt).strftime("%Y-%m-%d"), "rotulo": pd.Timestamp(dt).strftime("%d/%m"),
                    "unidades": f(E["qtd"].sum(), 0) if not E.empty else 0})
    return out


def tendencia(d: ind.Dados, categoria="calcado", nivel="sku", dias=7) -> dict:
    """Compara o estoque de hoje com o de `dias` atrás (ou a foto mais antiga disponível)
    e projeta quando cada item zera no ritmo de venda atual."""
    datas = _datas_fotos(d)
    if not datas:
        return {"status": "sem_dados", "motivo": "Nenhum estoque importado."}
    ultima = pd.Timestamp(datas[-1])
    alvo = ultima - pd.Timedelta(days=int(dias))
    anteriores = [pd.Timestamp(x) for x in datas if pd.Timestamp(x) <= alvo]
    ref = anteriores[-1] if anteriores else (pd.Timestamp(datas[0]) if len(datas) > 1 else None)
    base = ind.meses_base_demanda(d)
    atual = ind._estoque_por_chave(d, categoria, nivel)
    atual = atual["est"] if "est" in atual else pd.Series(dtype=float)
    antes = pd.Series(dtype=float)
    if ref is not None and ref < ultima:
        a = ind._estoque_por_chave(d, categoria, nivel, data=ref)
        antes = a["est"] if "est" in a else antes
    dem = ind._demanda_por_chave(d, base, categoria, nivel) if base else pd.Series(dtype=float)
    df = pd.concat([atual.rename("atual"), antes.rename("antes"), dem.rename("dem")], axis=1)
    df = df[(df["atual"].fillna(0) != 0) | (df["antes"].fillna(0) != 0)]
    rot = ind._rotulos(d, nivel)
    tem_hist = ref is not None and ref < ultima
    itens = []
    for k, r in df.iterrows():
        at = 0.0 if pd.isna(r.atual) else float(r.atual)
        an = None if (not tem_hist or pd.isna(r.antes)) else float(r.antes)
        if tem_hist and an is None:
            an = 0.0
        dm = 0.0 if pd.isna(r.dem) else float(r.dem)
        var = (at - an) if an is not None else None
        if an is None:
            tend = "sem_historico"
        elif an > 0 and at <= 0:
            tend = "zerou"
        elif an <= 0 < at:
            tend = "entrou"
        elif var < 0 and (an and abs(var) / an >= 0.05):
            tend = "baixando"
        elif var > 0 and (an and var / an >= 0.05):
            tend = "subindo"
        else:
            tend = "estavel"
        cob = at / dm if (dm > 0 and at > 0) else None
        itens.append({"chave": k, "descricao": rot.get(k, ""), "estoque_antes": f(an, 0), "estoque": f(at, 0),
                      "variacao": f(var, 0), "variacao_pct": f(var / an * 100, 1) if (an and var is not None) else None,
                      "tendencia": tend, "venda_dia": f(dm, 2), "venda_mes": f(dm * 30, 0),
                      "dias_para_zerar": f(cob, 0),
                      "zera_em": (ultima + pd.Timedelta(days=round(cob))).strftime("%Y-%m-%d") if cob is not None else None})
    if tem_hist:
        itens.sort(key=lambda x: (x["variacao"] if x["variacao"] is not None else 0, -(x["venda_dia"] or 0)))
    else:
        itens.sort(key=lambda x: (x["dias_para_zerar"] if x["dias_para_zerar"] is not None else 99999, -(x["venda_dia"] or 0)))
    cont = pd.Series([i["tendencia"] for i in itens]).value_counts().to_dict() if itens else {}
    return {"status": "ok", "tem_historico": bool(tem_hist),
            "data_atual": ultima.strftime("%Y-%m-%d"), "data_anterior": ref.strftime("%Y-%m-%d") if tem_hist else None,
            "base": [ind.mes_label(base[0]), ind.mes_label(base[-1])] if base else None,
            "contagem": {k: int(v) for k, v in cont.items()},
            "total_atual": f(sum(i["estoque"] or 0 for i in itens), 0),
            "total_antes": f(sum(i["estoque_antes"] or 0 for i in itens), 0) if tem_hist else None,
            "itens": itens,
            "nota": ("Compara o estoque da última foto com a foto de " + ref.strftime("%d/%m/%Y") + ". "
                     if tem_hist else "Só há uma data de estoque importada; importe o estoque todos os dias para ver a evolução. ")
                    + "'Zera em' = estoque atual ÷ venda diária dos últimos 3 meses, sem contar pedidos a caminho."}


# --------------------------------------------------------------------------- Excel
FONTE = "Arial"
CAB = PatternFill("solid", start_color="1F2937")
FAIXA = PatternFill("solid", start_color="F3F4F6")


def _aba(wb, titulo, colunas, linhas, descricao=None):
    """colunas: [(rótulo, chave ou função, formato, largura)]"""
    ws = wb.create_sheet(titulo[:31])
    r0 = 1
    if descricao:
        ws.cell(1, 1, descricao).font = Font(name=FONTE, italic=True, size=9, color="4B5563")
        r0 = 3
    for j, (rot, _, _, larg) in enumerate(colunas, 1):
        c = ws.cell(r0, j, rot)
        c.font = Font(name=FONTE, bold=True, color="FFFFFF", size=10)
        c.fill = CAB
        c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(j)].width = larg
    ws.row_dimensions[r0].height = 30
    for i, item in enumerate(linhas, r0 + 1):
        for j, (_, k, fmt, _) in enumerate(colunas, 1):
            v = k(item) if callable(k) else item.get(k)
            if isinstance(v, str) and len(v) == 10 and v[4] == "-" and v[7] == "-":
                try:
                    v = datetime.strptime(v, "%Y-%m-%d")
                    fmt = "dd/mm/yyyy"
                except ValueError:
                    pass
            c = ws.cell(i, j, v)
            c.font = Font(name=FONTE, size=10)
            if fmt:
                c.number_format = fmt
    ws.freeze_panes = ws.cell(r0 + 1, 2)
    if linhas:
        ws.auto_filter.ref = f"A{r0}:{get_column_letter(len(colunas))}{r0 + len(linhas)}"
    return ws, r0


def planilha_estoque(categoria="calcado", nivel="sku", fornecedor=None, dias=7, limite_baixo=ind.COBERTURA_CRITICA) -> bytes:
    d = ind.dados()
    base = ind.meses_base_demanda(d)
    hoje = date.today()
    nome_nivel = {"modelo": "Modelo", "cabedal": "Cabedal", "sku": "SKU"}[nivel]
    nome_cat = {"calcado": "Calçados", "outro": "Outros produtos", "todos": "Todos os produtos"}[categoria]
    wb = Workbook()
    wb.remove(wb.active)
    resumo = wb.create_sheet("Resumo")

    # Posição
    tab = ind.tabela(d, base, categoria, nivel) if base else []
    tab = [t for t in tab if (t["estoque"] or 0) != 0 or t["status_estoque"] in ("ruptura", "sem_cadastro")]
    deps = sorted({k for t in tab for k in (t["estoque_depositos"] or {})})
    _aba(wb, "Posição", [
        (nome_nivel, "chave", None, 26), ("Descrição", "descricao", None, 44),
        *[(dp, (lambda t, dp=dp: (t["estoque_depositos"] or {}).get(dp)), "#,##0", 12) for dp in deps],
        ("Estoque total", "estoque", "#,##0", 12), ("Venda/dia", "demanda_dia", "#,##0.0", 11),
        ("Cobertura (dias)", "cobertura_dias", "#,##0", 12),
        ("Situação", lambda t: ROT_EST.get(t["status_estoque"], t["status_estoque"]), None, 20),
        ("Curva", "curva", None, 8)], tab,
        f"Estoque atual por {nome_nivel.lower()}. Venda/dia = média dos últimos 3 meses ({ind.mes_label(base[0])} a {ind.mes_label(base[-1])})." if base else None)

    # Tendência
    tdc = tendencia(d, categoria, nivel, dias)
    ROT_T = {"baixando": "Baixando", "subindo": "Subindo", "estavel": "Estável", "zerou": "Zerou", "entrou": "Entrou",
             "sem_historico": "Sem histórico"}
    if tdc["status"] == "ok":
        dt_ant = tdc["data_anterior"]
        _aba(wb, "Tendência", [
            (nome_nivel, "chave", None, 26), ("Descrição", "descricao", None, 44),
            (f"Estoque em {datetime.strptime(dt_ant, '%Y-%m-%d'):%d/%m}" if dt_ant else "Estoque anterior", "estoque_antes", "#,##0", 13),
            (f"Estoque em {datetime.strptime(tdc['data_atual'], '%Y-%m-%d'):%d/%m}", "estoque", "#,##0", 13),
            ("Variação", "variacao", "+#,##0;-#,##0;0", 11), ("Variação %", lambda x: (x["variacao_pct"] / 100) if x["variacao_pct"] is not None else None, "+0.0%;-0.0%;0%", 11),
            ("Tendência", lambda x: ROT_T[x["tendencia"]], None, 14), ("Vende/mês", "venda_mes", "#,##0", 11),
            ("Dias para zerar", "dias_para_zerar", "#,##0", 12), ("Zera em", "zera_em", None, 12)],
            tdc["itens"], tdc["nota"])

    # Reposição (pedidos de compra x estoque)
    rp = pd_.reposicao(d, categoria, nivel, fornecedor)
    rp_itens = rp["itens"] if rp.get("status") == "ok" else []
    hj = pd.Timestamp(hoje)

    def chega(x):
        if not x["previsao"]:
            return None
        return (pd.Timestamp(x["previsao"]) - hj).days

    col_rep = [
        (nome_nivel, "chave", None, 26), ("Descrição", "descricao", None, 44),
        ("Vende/mês", "demanda_mes", "#,##0", 11), ("Estoque", "estoque", "#,##0", 11),
        ("Dura (dias)", "cobertura", "#,##0", 11), ("A receber", "a_receber", "#,##0", 11),
        ("Previsão", "previsao", None, 12), ("Chega em (dias)", chega, "#,##0;-#,##0", 12),
        ("Dura c/ pedidos (dias)", "cobertura_com_pedidos", "#,##0", 13),
        ("Situação", lambda x: ROT_REPO.get(x["situacao"], x["situacao"]), None, 24)]
    forn_txt = fornecedor or "todos os fornecedores"
    _aba(wb, "Reposição", col_rep, rp_itens, f"Estoque x venda (3 meses) x pedidos em aberto no Omie ({forn_txt}). {rp.get('nota', '')}")

    baixo = [x for x in rp_itens if (x["a_receber"] or 0) <= 0 and (x["demanda_mes"] or 0) > 0
             and ((x["estoque"] or 0) <= 0 or (x["cobertura"] is not None and x["cobertura"] < limite_baixo))]
    baixo.sort(key=lambda x: -(x["demanda_mes"] or 0))
    _aba(wb, "Sem pedido e baixo", col_rep[:5] + [col_rep[-1]], baixo,
         f"Itens que vendem, estão zerados ou duram menos de {limite_baixo} dias e não têm pedido de compra em aberto ({forn_txt}).")

    cheg = [x for x in rp_itens if (x["a_receber"] or 0) > 0]
    cheg.sort(key=lambda x: x["previsao"] or "9999")
    _aba(wb, "Comprado chegando", col_rep + [("Chega a tempo?", lambda x: (
        "Sem venda recente" if (x["demanda_mes"] or 0) <= 0 else
        "Já zerado" if (x["estoque"] or 0) <= 0 else
        "Faturado" if (chega(x) is not None and chega(x) < 0) else
        "Não" if x["situacao"] == "pedido_chega_tarde" else "Sim"), None, 16)], cheg,
        f"Itens com pedido de compra em aberto e pares a receber ({forn_txt}). 'Chega a tempo?' compara a previsão com quanto o estoque atual dura.")

    # Grade quebrada e parado
    if categoria != "outro":
        gq = pd_.grade_com_pedidos(d, fornecedor, limite=2000)
        if gq.get("status") == "ok":
            _aba(wb, "Grade quebrada", [
                ("SKU", "sku", None, 26), ("Vende/mês", "pares_mes", "#,##0", 11), ("Estoque", "estoque", "#,##0", 11),
                ("Grade disponível", lambda x: (x["disponivel_pct"] or 0) / 100, "0%", 12),
                ("Tamanhos zerados sem pedido", lambda x: ", ".join(x["tamanhos_sem_pedido"]), None, 26),
                ("Tamanhos zerados com pedido", lambda x: ", ".join(f"{t} ({int(q)})" for t, q in x["a_caminho"].items()), None, 30)],
                gq["itens"], "SKUs que vendem e têm algum tamanho zerado.")
    par = ind.estoque_parado(d, categoria, nivel, limite=5000)
    if par.get("status") == "ok":
        _aba(wb, "Parado", [(nome_nivel, "chave", None, 26), ("Descrição", "descricao", None, 44),
                            ("Unidades", "estoque", "#,##0", 11), ("Última venda", "ultima_venda", None, 22)],
             par["itens"], "Estoque sem nenhuma venda nos últimos 3 meses.")

    ev = evolucao(d, categoria)
    _aba(wb, "Evolução", [("Data", "data", None, 12), ("Unidades em estoque", "unidades", "#,##0", 18)], ev,
         "Total em estoque em cada data importada (soma dos depósitos).")

    # Resumo com fórmulas que leem as outras abas
    resumo.column_dimensions["A"].width = 46
    resumo.column_dimensions["B"].width = 16
    resumo.column_dimensions["C"].width = 60
    resumo["A1"] = "Relatório de estoque"
    resumo["A1"].font = Font(name=FONTE, bold=True, size=14)
    info = [("Gerado em", datetime.now().strftime("%d/%m/%Y %H:%M")), ("Produtos", nome_cat), ("Agrupado por", nome_nivel),
            ("Pedidos de compra considerados", forn_txt),
            ("Base de venda", f"{ind.mes_label(base[0])} a {ind.mes_label(base[-1])}" if base else "—"),
            ("Estoque baixo = dura menos de", f"{limite_baixo} dias")]
    for i, (a, b) in enumerate(info, 3):
        resumo.cell(i, 1, a).font = Font(name=FONTE, size=10, color="4B5563")
        resumo.cell(i, 2, b).font = Font(name=FONTE, size=10)
    r = 3 + len(info) + 1
    resumo.cell(r, 1, "Indicador").font = Font(name=FONTE, bold=True, color="FFFFFF")
    resumo.cell(r, 2, "Valor").font = Font(name=FONTE, bold=True, color="FFFFFF")
    resumo.cell(r, 3, "De onde vem").font = Font(name=FONTE, bold=True, color="FFFFFF")
    for j in (1, 2, 3):
        resumo.cell(r, j).fill = CAB

    def conta(aba, col, rot):
        return f"=COUNTIF('{aba}'!{col}:{col},\"{rot}\")"

    def col_de(ws_nome, cabecalho):
        ws = wb[ws_nome]
        for row in ws.iter_rows(min_row=1, max_row=3):
            for c in row:
                if c.value == cabecalho:
                    return get_column_letter(c.column)
        return None

    kp = []
    cp = col_de("Posição", "Estoque total")
    if cp:
        kp.append(("Unidades em estoque", f"=SUM('Posição'!{cp}:{cp})", "#,##0", "Soma da coluna Estoque total da aba Posição"))
    cs = col_de("Posição", "Situação")
    if cs:
        for rot, txt in (("Zerado", "Itens zerados (que vendem)"), (ROT_EST["critico"], f"Itens que duram menos de {ind.COBERTURA_CRITICA} dias"),
                         (ROT_EST["excesso"], f"Itens com mais de {ind.COBERTURA_EXCESSO} dias de estoque"), ("Sem venda", "Itens com estoque e sem venda")):
            kp.append((txt, conta("Posição", cs, rot), "#,##0", "Aba Posição, coluna Situação"))
    if "Tendência" in wb.sheetnames:
        ct = col_de("Tendência", "Tendência")
        for rot, txt in (("Baixando", "Itens com estoque baixando"), ("Zerou", "Itens que zeraram no período"), ("Subindo", "Itens com estoque subindo")):
            kp.append((txt, conta("Tendência", ct, rot), "#,##0", "Aba Tendência, coluna Tendência"))
    kp.append(("Itens sem pedido e com estoque baixo", "=MAX(COUNTA('Sem pedido e baixo'!A:A)-2,0)", "#,##0",
               "Linhas da aba Sem pedido e baixo"))
    ca = col_de("Comprado chegando", "A receber")
    if ca:
        kp.append(("Itens comprados com estoque chegando", "=MAX(COUNTA('Comprado chegando'!A:A)-2,0)", "#,##0", "Linhas da aba Comprado chegando"))
        kp.append(("Unidades a receber", f"=SUM('Comprado chegando'!{ca}:{ca})", "#,##0", "Soma da coluna A receber"))
        ct2 = get_column_letter(len(col_rep) + 1)
        kp.append(("Pedidos que chegam depois de o estoque acabar", conta("Comprado chegando", ct2, "Não"), "#,##0",
                   "Aba Comprado chegando, coluna Chega a tempo?"))
        kp.append(("Itens com pedido faturado", conta("Comprado chegando", ct2, "Faturado"), "#,##0",
                   "Aba Comprado chegando, coluna Chega a tempo?"))
    for i, (a, form, fmt, orig) in enumerate(kp, r + 1):
        resumo.cell(i, 1, a).font = Font(name=FONTE, size=10)
        c = resumo.cell(i, 2, form)
        c.font = Font(name=FONTE, size=10, bold=True)
        c.number_format = fmt
        resumo.cell(i, 3, orig).font = Font(name=FONTE, size=9, color="6B7280")
        if (i - r) % 2 == 0:
            for j in (1, 2, 3):
                resumo.cell(i, j).fill = FAIXA
    resumo.cell(r + len(kp) + 2, 1, "As abas têm filtro no cabeçalho. Os números deste resumo são fórmulas e se atualizam se você editar as abas.").font = Font(name=FONTE, size=9, italic=True, color="6B7280")
    wb.calculation.fullCalcOnLoad = True
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
