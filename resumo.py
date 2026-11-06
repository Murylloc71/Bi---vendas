"""Resumo textual do período, montado apenas a partir dos indicadores calculados."""
from __future__ import annotations


def _brl(v):
    if v is None:
        return "—"
    s = f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def _n(v):
    return "—" if v is None else f"{v:,.0f}".replace(",", ".")


def _pct(v):
    return "—" if v is None else (f"+{v:.1f}%" if v > 0 else f"{v:.1f}%").replace(".", ",")


def _nome(item):
    d = (item.get("descricao") or "").strip()
    return f"{item['chave']}" + (f" ({d[:48]}{'…' if len(d) > 48 else ''})" if d else "")


def montar(kpis, tabela, tempo, rupturas, perdas, economia, grade, parado, periodo_rotulo) -> dict:
    pos, prob, opo, notas = [], [], [], []
    comp = kpis.get("comparacao")
    base_txt = ""
    if comp:
        base_txt = " (média diária)" if comp["base"] == "media_diaria" else ""
        txt = (f"Faturamento de {_brl(kpis['faturamento'])} com {_n(kpis['unidades'])} unidades — "
               f"{_pct(comp['faturamento'])} vs {comp['periodo'][0]}"
               + (f"–{comp['periodo'][1]}" if comp['periodo'][1] != comp['periodo'][0] else "") + base_txt + ".")
        (pos if (comp["faturamento"] or 0) >= 0 else prob).append(txt)
        if comp.get("preco_medio") is not None and abs(comp["preco_medio"]) >= 5:
            t = f"Preço médio de {_brl(kpis['preco_medio'])}, {_pct(comp['preco_medio'])} vs período anterior."
            (pos if comp["preco_medio"] > 0 else prob).append(t)
    else:
        pos.append(f"Faturamento de {_brl(kpis['faturamento'])} com {_n(kpis['unidades'])} unidades.")
        notas.append("Sem período anterior equivalente para comparação.")

    vend = [t for t in tabela if (t.get("faturamento") or 0) > 0]
    if vend:
        top = vend[0]
        part = str(round(top["participacao"] or 0, 1)).replace(".", ",")
        pos.append(f"Maior faturamento: {_nome(top)} — {_brl(top['faturamento'])} ({part}% do total).")
        def delta(t):  # variação absoluta estimada a partir do % e do valor atual
            v = t.get("var_faturamento")
            if v is None or v <= -100:
                return 0
            return (t["faturamento"] or 0) - (t["faturamento"] or 0) / (1 + v / 100)
        cres = sorted([t for t in vend if t.get("var_faturamento") is not None], key=lambda t: -delta(t))
        if cres and delta(cres[0]) > 0 and cres[0]["var_faturamento"] >= 10:
            t = cres[0]
            pos.append(f"Maior crescimento: {_nome(t)}, {_pct(t['var_faturamento'])} no faturamento "
                       f"(+{_brl(delta(t))}).")
        quedas = sorted([t for t in tabela if t.get("var_faturamento") is not None], key=delta)
        if quedas and delta(quedas[0]) < 0 and quedas[0]["var_faturamento"] <= -10:
            t = quedas[0]
            prob.append(f"Maior queda: {_nome(t)}, {_pct(t['var_faturamento'])} no faturamento "
                        f"({_brl(delta(t)).replace('R$ ', '−R$ ').replace('-', '')}).")
        curva_a_crit = [t for t in tabela if t.get("curva") == "A" and t.get("status_estoque") in ("critico", "ruptura")]
        if curva_a_crit:
            prob.append(f"{len(curva_a_crit)} item(ns) da curva A com estoque crítico ou zerado: "
                        + ", ".join(t["chave"] for t in curva_a_crit[:4]) + ("…" if len(curva_a_crit) > 4 else "") + ".")

    if rupturas.get("status") == "ok" and rupturas.get("skus"):
        nomes = ", ".join(i["chave"] for i in rupturas["itens"][:3])
        prob.append(f"{rupturas['skus']} SKUs com venda recente estão zerados nos depósitos "
                    f"(≈ {_n(rupturas['pares_mes'])} unidades/mês de demanda). Maiores: {nomes}.")
    if perdas.get("status") == "ok" and (perdas.get("pares") or 0) > 0:
        prob.append(f"Vendas perdidas estimadas: {_n(perdas['pares'])} unidades ({_brl(perdas['valor'])}) "
                    f"em {perdas['dias_monitorados']} dia(s) monitorado(s).")
    elif perdas.get("status") == "sem_dados":
        notas.append("Vendas perdidas: " + perdas.get("motivo", "sem dados."))

    if tempo.get("status") == "ok" and tempo.get("dias") is not None:
        t = f"Cobertura geral de {_n(tempo['dias'])} dias de estoque no ritmo de venda do período."
        (pos if 20 <= tempo["dias"] <= 120 else prob).append(t)

    if economia.get("status") == "ok" and economia.get("economia"):
        txt = (f"Economia com pronta-entrega: {_brl(economia['economia'])} em {_n(economia['pares_calculados'])} pares"
               + (f" ({str(economia['economia_pct']).replace('.', ',')}% abaixo do programado)" if economia.get("economia_pct") else "") + ".")
        pos.append(txt)
        falta = []
        if economia.get("pares_sem_referencia"):
            falta.append(f"{_n(economia['pares_sem_referencia'])} pares sem referência de programado")
        if economia.get("notas_sem_quantidade"):
            falta.append(f"{economia['notas_sem_quantidade']} notas sem quantidade")
        if falta:
            notas.append("Economia PE não inclui: " + "; ".join(falta) + ".")

    if grade.get("status") == "ok" and grade.get("skus"):
        opo.append(f"{grade['skus']} SKUs que vendem estão com grade quebrada (tamanhos zerados) — repor os tamanhos faltantes.")
    if parado.get("status") == "ok" and parado.get("unidades"):
        opo.append(f"{_n(parado['unidades'])} unidades em {parado['skus']} SKUs sem venda em {parado['base'][0]}–{parado['base'][1]} — "
                   "candidatos a promoção ou liquidação.")
    if tempo.get("status") == "ok":
        exc = next((f for f in tempo["faixas"] if f["status"] == "excesso"), None)
        if exc and exc["skus"]:
            opo.append(f"{exc['skus']} SKUs com mais de 120 dias de cobertura ({_n(exc['unidades'])} unidades) — "
                       "rever compras desses itens.")
    if kpis.get("contem_parcial"):
        notas.append("O período inclui mês parcial; comparações usam média diária.")
    return {"periodo": periodo_rotulo, "positivos": pos, "problemas": prob, "oportunidades": opo, "notas": notas}
