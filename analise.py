"""Monta um texto (prompt) com os números do BI para ser colado numa conversa com o Claude,
que faz o papel de analista de compras. Não inclui informação financeira (parcelas,
vencimentos, contas a pagar): só vendas, estoque, compras (notas) e pedidos.
"""
from __future__ import annotations

from datetime import date

from . import indicadores as ind
from . import linha as _linha
from . import pedidos as pd_
from . import relatorios as rel


def _n(v, casas=0):
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = f"{v:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _r(v):
    return "—" if v is None else "R$ " + _n(v, 0)


def _p(v):
    return "—" if v is None else (("+" if v > 0 else "") + _n(v, 1) + "%")


def _tabela(cab, linhas):
    if not linhas:
        return "(sem dados)\n"
    out = "| " + " | ".join(cab) + " |\n|" + "|".join("---" for _ in cab) + "|\n"
    for l in linhas:
        out += "| " + " | ".join(str(x) for x in l) + " |\n"
    return out


def gerar(main, inicio=None, fim=None, categoria="calcado", detalhe="completo") -> dict:
    """`main` é o módulo de rotas (reaproveita os mesmos cálculos das telas)."""
    top_n = 15 if detalhe == "completo" else 8
    partes = []
    d = ind.dados()
    meses = main._periodo(d, inicio, fim)
    per = ind.mes_label(meses[0]) + ("" if len(meses) == 1 else f" a {ind.mes_label(meses[-1])}")
    modo = _linha.MODO.get()
    cat_txt = {"calcado": "calçados", "outro": "outros produtos", "todos": "todos os produtos"}[categoria]

    partes.append(f"""# Pedido de análise do BI de Vendas, Estoque e Compras (Uai Comprei)

Você é meu analista de compras e estoque. Trabalho na área de compras e preciso de uma visão geral do negócio.
Abaixo estão os números do meu BI, gerados em {date.today():%d/%m/%Y}. Período analisado: **{per}**; produtos: **{cat_txt}**{f"; só produtos **{_linha.MODOS[modo].lower()}**" if modo else ""}.
Vendas em Mercado Livre e Shopee; principal fornecedor: Calçados Beira Rio (marcas Beira Rio, Vizzano, Moleca, Modare, Molekinho).

Com base nesses dados, responda em português, de forma direta e prática:
1. **O que posso esperar** nas próximas semanas e meses (vendas, estoque, entregas), com as premissas que você usou.
2. **O que aprendemos**: padrões de venda, sazonalidade, canais, preço, concentração, comportamento de compra.
3. **O que melhoramos com o tempo** e o que piorou (compare meses e períodos).
4. **Riscos e oportunidades**: rupturas, excesso, estoque parado, grade quebrada, pedidos atrasados, dependência de poucos modelos.
5. **Recomendações de compra**: o que repor, o que segurar, o que liquidar, priorizadas por impacto.
6. Qualquer outra leitura que você achar útil, e quais dados a mais deixariam a análise melhor.
Aponte quando um número parecer inconsistente ou quando a base for pequena demais para concluir algo.
""")

    # ------------------------------------------------------------------ vendas
    r = main.vendas_resultado(meses[0].strftime("%Y-%m"), meses[-1].strftime("%Y-%m"), categoria)
    k = r["kpis"]; c = k.get("comparacao") or {}
    partes.append(f"""## 1. Vendas no período ({per})
- Faturamento {_r(k['faturamento'])} ({_p(c.get('faturamento'))} vs {'–'.join(c.get('periodo', []) or ['—'])}, {'média diária' if c.get('base') == 'media_diaria' else 'total'}); unidades {_n(k['unidades'])} ({_p(c.get('unidades'))}); preço médio {_r(k['preco_medio'])} ({_p(c.get('preco_medio'))}).
- {_n(k['dias'])} dias de venda{' (inclui mês parcial)' if k.get('contem_parcial') else ''}; {_n(k['unidades_dia'], 1)} unidades/dia; {_r(k['faturamento_dia'])}/dia.
- Canais: Mercado Livre {_n(k['unidades_ml'])} un. ({_n(100 * k['unidades_ml'] / k['unidades'], 0) if k['unidades'] else '—'}%), Shopee {_n(k['unidades_shopee'])} un.
- {_n(k['modelos_vendidos'])} modelos e {_n(k['skus_vendidos'])} SKUs com venda.
- Concentração: {_n(r['graficos']['itens_80'])} de {_n(r['graficos']['itens'])} modelos fazem 80% do faturamento; {_n(r['graficos']['itens_50'])} fazem metade.
""")
    partes.append("### Últimos 12 meses\n" + _tabela(
        ["Mês", "Unidades", "Faturamento", "Preço médio", "ML", "Shopee", "SKUs ativos", "Un./dia"],
        [[m["rotulo"] + (" (parcial)" if m.get("parcial") else ""), _n(m["unidades"]), _r(m["faturamento"]), _r(m["preco_medio"]),
          _n(m.get("unidades_ml")), _n(m.get("unidades_shopee")), _n(m.get("skus_ativos")), _n(m.get("unidades_dia"), 1)] for m in r["serie_12m"]]))
    partes.append(f"### Top {len(r['top'][:top_n])} modelos do período\n" + _tabela(
        ["Modelo", "Descrição", "Unidades", "Faturamento", "Var. fat.", "Preço", "Estoque", "Dura (dias)", "Curva"],
        [[t["chave"], (t.get("descricao") or "")[:45], _n(t["unidades"]), _r(t["faturamento"]), _p(t.get("var_faturamento")),
          _r(t.get("preco_medio")), _n(t.get("estoque")), _n(t.get("cobertura_dias")), t.get("curva") or "—"] for t in r["top"][:top_n]]))
    g = r["graficos"]
    if g["altas"] or g["quedas"]:
        partes.append("### Quem mais ganhou e perdeu faturamento (vs período anterior)\n" + _tabela(
            ["Modelo", "Descrição", "Diferença", "Variação"],
            [[x["chave"], (x.get("descricao") or "")[:45], _r(x["delta"]), _p(x["var"])] for x in g["altas"] + g["quedas"]]))
    if g.get("faixas"):
        partes.append("### Faturamento por faixa de preço\n" + _tabela(
            ["Faixa", "Unidades", "Faturamento", "Participação"],
            [[f"R$ {x['rotulo']}", _n(x["unidades"]), _r(x["faturamento"]), _n(x["pct"], 1) + "%"] for x in g["faixas"]]))

    # ------------------------------------------------------------------ dia a dia
    dd = ind.vendas_diarias(d, categoria)
    if dd.get("status") == "ok":
        sa, u7 = dd["semana_atual"], dd["ultimos7"]
        partes.append(f"""## 2. Vendas dia a dia (listas diárias importadas: {dd['primeiro_dia']} a {dd['ultimo_dia']}, {dd['dias_lancados']} dias)
- Últimos 7 dias: {_n(u7['unidades'])} un., {_r(u7['faturamento'])} ({_p(u7.get('var_unidades'))} em unidades vs 7 dias anteriores).
- Semana atual ({sa['dias']} dias): {_n(sa['unidades'])} un. ({_p(sa.get('var_unidades'))} vs mesmos dias da semana passada).
- Média por dia da semana: {', '.join(f"{x['dia']} {_n(x['media'])}" for x in dd['dia_da_semana'] if x['media'] is not None)}.
- Faturamento diário estimado (sem ticket médio na planilha): {_n(dd.get('faturamento_estimado_pct'))}%.
""" + _tabela(["Semana", "Dias com dados", "Unidades", "ML", "Shopee", "Faturamento"],
              [[f"{s['rotulo']} a {s['ate']}", s["dias_com_dados"], _n(s["unidades"]), _n(s["unidades_ml"]), _n(s["unidades_shopee"]), _r(s["faturamento"])]
               for s in dd["semanas"][-8:] if s["dias_com_dados"]]))
    else:
        partes.append("## 2. Vendas dia a dia\n(nenhuma lista diária importada ainda)\n")

    # ------------------------------------------------------------------ estoque
    pos = main.estoque_posicao("modelo", categoria)
    est, te = pos["estoque"], pos["tempo_estoque"]
    if est.get("status") == "ok":
        partes.append(f"""## 3. Estoque (foto de {', '.join(f"{x['deposito']} {x['data']}" for x in est['depositos'])})
- Total {_n(est['total'])} unidades ({', '.join(f"{x['deposito']} {_n(x['unidades'])}" for x in est['depositos'])}); {_n(est.get('skus_com_saldo'))} SKUs com saldo.
- Tempo de estoque: {_n(te.get('dias'))} dias no ritmo de venda de {'–'.join(pos['base'])} ({_n(te.get('demanda_dia'), 1)} un./dia).
""" + _tabela(["Faixa de cobertura", "SKUs", "Unidades"], [[x["rotulo"], _n(x["skus"]), _n(x["unidades"])] for x in te.get("faixas", [])]))
    tnd = rel.tendencia(d, categoria, "modelo", 7)
    if tnd.get("status") == "ok":
        if tnd["tem_historico"]:
            cc = tnd["contagem"]
            partes.append(f"- Tendência ({tnd['data_anterior']} → {tnd['data_atual']}): total {_n(tnd['total_antes'])} → {_n(tnd['total_atual'])}; "
                          f"{_n(cc.get('baixando', 0))} modelos baixando, {_n(cc.get('zerou', 0))} zeraram, {_n(cc.get('subindo', 0))} subindo.\n")
        zera = [x for x in tnd["itens"] if x.get("dias_para_zerar") is not None and x["dias_para_zerar"] <= 30][:top_n]
        if zera:
            partes.append("### Modelos que zeram em até 30 dias (sem contar pedidos)\n" + _tabela(
                ["Modelo", "Descrição", "Estoque", "Vende/mês", "Zera em"],
                [[x["chave"], (x.get("descricao") or "")[:45], _n(x["estoque"]), _n(x["venda_mes"]), x["zera_em"]] for x in zera]))

    # ------------------------------------------------------------------ reposição
    rp = main.estoque_reposicao("modelo", categoria)
    rr = rp["reposicao"]
    if rr.get("status") == "ok":
        rot = {"ruptura_sem_pedido": "Zerado sem pedido", "critico_sem_pedido": "Acabando sem pedido", "pedido_chega_tarde": "Pedido chega tarde",
               "ruptura_com_pedido": "Zerado com pedido", "coberto": "Coberto pelo pedido", "ok": "OK", "excesso": "Excesso", "sem_demanda": "Comprado sem venda recente"}
        partes.append("## 4. Reposição (estoque x venda dos últimos 3 meses x pedidos em aberto)\n" + _tabela(
            ["Situação", "Modelos", "Venda/mês", "A receber"],
            [[rot.get(s, s), _n(v["itens"]), _n(v["demanda_mes"]), _n(v["a_receber"])] for s, v in rr["contagem"].items()]))
        urg = [x for x in rr["itens"] if x["situacao"] in ("ruptura_sem_pedido", "critico_sem_pedido", "pedido_chega_tarde")]
        urg.sort(key=lambda x: -(x.get("demanda_mes") or 0))
        if urg:
            partes.append("### Mais urgentes\n" + _tabela(
                ["Modelo", "Descrição", "Vende/mês", "Estoque", "Dura", "A receber", "Previsão", "Situação"],
                [[x["chave"], (x.get("descricao") or "")[:40], _n(x["demanda_mes"]), _n(x["estoque"]), _n(x.get("cobertura")),
                  _n(x["a_receber"]), x.get("previsao") or "—", rot.get(x["situacao"])] for x in urg[:top_n]]))
    gq = rp.get("grade") or {}
    if gq.get("status") == "ok":
        sem_ped = [x for x in gq["itens"] if x["tamanhos_sem_pedido"]]
        exemplos = ", ".join("{} ({})".format(x["sku"], "/".join(x["tamanhos_sem_pedido"])) for x in sem_ped[:5])
        partes.append(f"- Grade quebrada: {_n(len(gq['itens']))} SKUs que vendem têm tamanho zerado; em {_n(len(sem_ped))} deles há tamanho zerado sem pedido "
                      f"(ex.: {exemplos or '—'}).\n")
    pa = main.estoque_parado_ep("modelo", categoria)
    par = pa.get("parado") or {}
    if par.get("status") == "ok":
        maiores = ", ".join("{} ({})".format(x["chave"], _n(x["estoque"])) for x in par["itens"][:6])
        partes.append(f"- Estoque parado (sem venda em {'–'.join(par.get('base', []))}): {_n(par['unidades'])} unidades em {_n(par['skus'])} itens; "
                      f"maiores: {maiores}.\n")

    # ------------------------------------------------------------------ compras (notas)
    try:
        _, I = pd_.carregar(None)
        rec = I.groupby("modelo")["a_receber"].sum().to_dict() if not I.empty else {}
    except Exception:  # noqa: BLE001
        rec = {}
    mc = ind.mais_comprados(d, meses, rec)
    mc_all = ind.mais_comprados(d, d.meses, rec) if d.meses else mc
    if mc.get("status") == "ok" or mc_all.get("status") == "ok":
        base_c = mc if mc.get("status") == "ok" else mc_all
        t = base_c["totais"]
        partes.append(f"""## 5. Compras (relatórios de notas de entrada; histórico {mc_all.get('historico', {}).get('de', '—')} a {mc_all.get('historico', {}).get('ate', '—')})
- No período: {_n(t['pares'])} pares, {_r(t['valor'])}, {_n(t['modelos'])} modelos, {_n(t['notas'])} notas; preço médio de compra {_r(t['preco_medio'])}/par; pronta-entrega {_n(t['pe_pct'])}% dos pares; {_n(t['linhas_sem_quantidade'])} linhas sem quantidade (fora da soma).
""" + "### Compras por mês (todo o histórico)\n" + _tabela(
            ["Mês", "Pares", "Programado", "Pronta-entrega"],
            [[s["rotulo"], _n(s["pares"]), _n(s["prog"]), _n(s["pe"])] for s in mc_all.get("serie", [])]))
        partes.append(f"### Top {top_n} mais comprados (todo o histórico) x venda e estoque\n" + _tabela(
            ["Modelo", "Descrição", "Pares comprados", "Compras (notas)", "Preço médio", "PE", "Vendidos", "% vendido", "Estoque", "A receber"],
            [[x["modelo"], (x.get("descricao") or "")[:40], _n(x["pares"]), _n(x["historico_compras"]), _r(x.get("preco_medio")),
              (_n(x["pe_pct"]) + "%") if x.get("pe_pct") is not None else "—", _n(x["vendidos"]), (_n(x["vendido_pct"]) + "%") if x.get("vendido_pct") is not None else "—",
              _n(x["estoque"]), _n(x["a_receber"])] for x in mc_all.get("itens", [])[:top_n]]))
    eco = r.get("economia_pe") or {}
    if eco.get("status") == "ok":
        partes.append(f"- Economia com pronta-entrega no período: {_r(eco.get('economia'))} ({_n(eco.get('economia_pct'), 1)}%) em {_n(eco.get('pares_calculados'))} pares.\n")

    # ------------------------------------------------------------------ pedidos (sem parcelas/vencimentos)
    ped = main.compras_pedidos()
    rs = ped.get("resumo") or {}
    if rs.get("status") == "ok":
        ab = rs["abertos"]
        partes.append(f"""## 6. Pedidos de compra em aberto no Omie ({rs.get('fornecedor')})
- {_n(ab['pedidos'])} pedidos, {_n(ab['pares'])} pares a receber, {_n(ab['modelos'])} modelos / {_n(ab['skus'])} SKUs; custo médio {_r(ab['preco_medio_par'])}/par.
- Faturados (previsão já passou, a caminho): {_n(rs['previsao_vencida']['pedidos'])} pedidos, {_n(rs['previsao_vencida']['pares'])} pares.
- Próximos 7 dias: {_n(rs['proximos_7']['pares'])} pares; próximos 30 dias: {_n(rs['proximos_30']['pares'])} pares.
""" + "### Entregas previstas por semana\n" + _tabela(
            ["Semana", "Pares", "Pedidos", "Situação"],
            [[e["rotulo"], _n(e["pares"]), e["pedidos"], "faturado" if e["vencida"] else "previsto"] for e in rs.get("entregas", [])]))

    # ------------------------------------------------------------------ linha e qualidade
    m = _linha.marcas()
    if m:
        partes.append(f"## 7. Produtos em linha\n- {sum(1 for v in m.values() if v)} modelos marcados em linha e {sum(1 for v in m.values() if not v)} fora de linha (o restante sem marcação).\n")
    partes.append("""## Observações sobre os dados
- Vendas mensais vêm do relatório de vendas; os dias seguintes, das listas diárias (faturamento estimado quando a lista não tem ticket médio).
- Estoque é a última foto importada de cada depósito (Unlock e Juatuba); estoque no Full não está incluído.
- Compras vêm das notas de entrada; nem toda linha tem quantidade. Pedidos vêm do Omie.
- Este resumo não traz informação financeira (parcelas, vencimentos, contas a pagar).
""")
    texto = "\n".join(partes)
    return {"texto": texto, "caracteres": len(texto), "periodo": per}
