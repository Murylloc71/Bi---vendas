import { useState } from 'react'
import { SemanasComparadas, BarrasSimples, CanaisMes, CompareBars, DiasVendas, Divergente, MonthBars, MonthLine, Pareto, PriceBins, Rosca, SemanasVendas, StackBar } from '../charts'
import { useCtx } from '../ctx'
import { dataBR, money, money2, n0, n1, pct } from '../fmt'
import { Box, DataTable, Delta, Empty, Load, Stat, Stats, Status, Summary, useApi } from '../ui'

const NIVEL = { modelo: 'Modelo', cabedal: 'Cabedal', sku: 'SKU' }

function baseTxt(c) {
  if (!c) return null
  return (c.base === 'media_diaria' ? 'média diária vs ' : 'vs ') + c.periodo[0] + (c.periodo[1] !== c.periodo[0] ? '–' + c.periodo[1] : '')
}

export function Resultado() {
  const { f, per, versao, openProduto, go, irParaMes } = useCtx()
  const st = useApi('/api/vendas/resultado', { inicio: per[0], fim: per[1], categoria: f.categoria }, [versao])
  return (
    <Load state={st} height={600}>{(d) => {
      const k = d.kpis, c = k.comparacao
      return (
        <>
          <Stats>
            <Stat label="Faturamento" value={money(k.faturamento)} sub={c ? <><Delta v={c.faturamento} /> {baseTxt(c)}</> : `${money(k.faturamento_dia)} por dia`} />
            <Stat label="Unidades vendidas" value={n0(k.unidades)} sub={c ? <><Delta v={c.unidades} /> {baseTxt(c)}</> : `${n1(k.unidades_dia)} por dia`} />
            <Stat label="Preço médio" value={money2(k.preco_medio)} sub={c ? <><Delta v={c.preco_medio} /> vs período anterior</> : 'faturamento ÷ unidades'} />
            <Stat label="SKUs com venda" value={n0(k.skus_vendidos)} sub={`${n0(k.modelos_vendidos)} modelos de calçado`} />
            {d.economia_pe.status === 'ok' && d.economia_pe.pares_calculados
              ? <Stat label="Economia pronta-entrega" value={money(d.economia_pe.economia)} sub={`${n0(d.economia_pe.pares_calculados)} pares, ${n1(d.economia_pe.economia_pct)}% abaixo`} />
              : <Stat label="Economia pronta-entrega" na value="Sem dados" sub="Sem compras PE com quantidade" />}
            {d.vendas_perdidas.status === 'ok'
              ? <Stat label="Vendas perdidas" value={n0(d.vendas_perdidas.pares)} tone="alarm" sub={`${money(d.vendas_perdidas.valor)} em ${d.vendas_perdidas.dias_monitorados} dia(s)`} />
              : <Stat label="Vendas perdidas" na value="Sem dados" sub="Requer estoque diário no período" />}
          </Stats>
          {per[0] === per[1] && <SemanasDoMes mes={per[0]} />}
          <DiaADia />
          <div className="row c-wide">
            <Box title="Faturamento por mês" sub={d.periodo.meses > 1 ? 'Cada mês comparado ao mês equivalente do período anterior. Clique em um mês para ver só ele.' : d.periodo.rotulo}>
              <CompareBars atual={d.serie} anterior={d.serie_anterior} dataKey="faturamento" fmtTip={money} onSelect={d.periodo.meses > 1 ? (x) => irParaMes(x.mes, null) : undefined} />
            </Box>
            <Box title="Canais" sub={`${n0(k.unidades)} unidades no período`}>
              {k.unidades_ml === null ? <Empty>O arquivo não traz unidades por canal.</Empty> : (
                <StackBar parts={[{ label: 'Mercado Livre', value: k.unidades_ml || 0, color: 'var(--s1)' }, { label: 'Shopee', value: k.unidades_shopee || 0, color: 'var(--s2)' }]} unit=" un." />
              )}
              <p className="note">O relatório traz faturamento só no total; por canal, apenas unidades.</p>
            </Box>
          </div>
          <div className="row c2">
            <Box title="Unidades por canal, mês a mês" sub="Últimos 12 meses; o período escolhido fica em destaque">
              {d.serie_12m.some((m) => m.unidades_ml || m.unidades_shopee)
                ? <CanaisMes data={d.serie_12m} selecionados={d.serie.map((m) => m.mes)} />
                : <Empty>O arquivo não traz unidades por canal.</Empty>}
            </Box>
            <Box title="Preço médio por mês" sub="Faturamento ÷ unidades, nos últimos 12 meses">
              <MonthLine data={d.serie_12m.filter((m) => m.preco_medio)} dataKey="preco_medio" rows={[['Preço médio', (m) => money2(m.preco_medio)], ['Unidades', (m) => n0(m.unidades)]]} fmt={(v) => 'R$' + Math.round(v)} height={230} />
            </Box>
          </div>
          <div className="row c2">
            <Box title="Concentração do faturamento" sub={`${n0(d.graficos.itens_80)} de ${n0(d.graficos.itens)} modelos fazem 80% do faturamento; ${n0(d.graficos.itens_50)} fazem metade`}>
              {d.graficos.pareto.length > 1 ? <Pareto data={d.graficos.pareto} itens80={d.graficos.itens_80} total={d.graficos.itens} /> : <Empty>Sem faturamento no período.</Empty>}
            </Box>
            <Box title="Faturamento por faixa de preço" sub="Preço médio de cada SKU no mês">
              {d.graficos.faixas?.length ? <Rosca data={d.graficos.faixas} dataKey="faturamento" /> : <Empty>Sem faturamento no período.</Empty>}
            </Box>
          </div>
          {(d.graficos.altas.length > 0 || d.graficos.quedas.length > 0) && (
            <div className="row c2">
              <Box title="Quem mais ganhou faturamento" sub="Modelos, em R$, contra o período anterior de mesma duração. Clique para abrir.">
                {d.graficos.altas.length ? <Divergente data={d.graficos.altas} onSelect={(x) => openProduto('modelo', x.chave)} /> : <Empty>Nenhum modelo cresceu.</Empty>}
              </Box>
              <Box title="Quem mais perdeu faturamento" sub="Modelos, em R$, contra o período anterior de mesma duração. Clique para abrir.">
                {d.graficos.quedas.length ? <Divergente data={d.graficos.quedas} onSelect={(x) => openProduto('modelo', x.chave)} /> : <Empty>Nenhum modelo caiu.</Empty>}
              </Box>
            </div>
          )}
          <Box title="Maiores faturamentos" sub="Modelos do período" right={<button className="btn ghost" onClick={() => go('/vendas/produtos')}>Ver todos os produtos</button>} flush="b">
            <ul className="list">
              {d.top.map((t) => (
                <li key={t.chave}><div className="t"><button className="link" onClick={() => openProduto('modelo', t.chave)}>{t.chave}</button>
                  <span>{t.descricao} · {n0(t.unidades)} un. · {n1(t.participacao)}% do faturamento</span></div>
                  <div className="v">{money(t.faturamento)}<small><Delta v={t.var_faturamento} /></small></div></li>
              ))}
            </ul>
          </Box>
        </>
      )
    }}</Load>
  )
}

/** Vendas do mês por semana (planilhas semanais), comparadas com as mesmas semanas do mês anterior. */
function SemanasDoMes({ mes }) {
  const { f, versao, openProduto, go } = useCtx()
  const st = useApi('/api/vendas/semanas', { mes, categoria: f.categoria }, [versao])
  const d = st.data
  if (st.error || !d) return null
  if (!d.tem_dados && !(d.semanal_desde && mes >= d.semanal_desde)) return null
  const tot = d.semanas.reduce((a, x) => a + (x.unidades || 0), 0)
  const semNums = d.semanas.map((x) => x.semana)
  return (
    <Box title={`Semanas de ${d.rotulo}`} className="mb"
      sub={`Cada semana comparada com a mesma semana de ${d.anterior}. Passe o mouse nas barras para ver média por dia e variação.`}
      right={<button className="btn ghost" onClick={() => go('/dados/importar')}>Enviar planilha da semana</button>}>
      {!d.tem_dados ? <Empty>Nenhuma planilha semanal de {d.rotulo} enviada ainda.</Empty> : (
        <>
          {!d.semanas_anterior.some((x) => x.dias_com_dados) && (
            <div className="alert" style={{ marginBottom: 10 }}>{d.anterior} não tem planilhas semanais (só o relatório mensal), então ainda não dá para comparar semana a semana. A comparação aparece a partir do mês seguinte ao primeiro mês com semanas enviadas.</div>)}
          <div className="row c-wide" style={{ marginBottom: 8 }}>
            <div><SemanasComparadas data={d.semanas} mes={d.rotulo} anterior={d.anterior} /></div>
            <div className="tscroll"><table className="dt">
              <thead><tr><th>Semana</th><th className="r">Unid.</th><th className="r">Média/dia</th><th className="r">vs {d.anterior}</th></tr></thead>
              <tbody>{d.semanas.map((x) => (
                <tr key={x.semana}>
                  <td><b>{x.rotulo}</b><span className="d">{x.periodo}{x.dias_com_dados && !x.completa ? ` · ${x.dias_com_dados} de ${x.dias} dias` : ''}{!x.dias_com_dados ? ' · sem planilha' : ''}</span></td>
                  <td className="r">{n0(x.unidades)}<span className="d">ML {n0(x.unidades_ml)} · Shopee {n0(x.unidades_shopee)}</span></td>
                  <td className="r">{x.media_dia === null ? '—' : n1(x.media_dia)}</td>
                  <td className="r">{x.var_media_dia === null || x.var_media_dia === undefined ? '—' : <span className={x.var_media_dia >= 0 ? 'seta-up' : 'seta-down'}>{x.var_media_dia >= 0 ? '▲' : '▼'} {pct(x.var_media_dia)}</span>}</td>
                </tr>))}
                <tr><td><b>Total</b></td><td className="r"><b>{n0(tot)}</b></td><td colSpan={2} /></tr>
              </tbody>
            </table></div>
          </div>
          {d.top_modelos.length > 0 && (
            <>
              <h3 className="sub-h">Modelos mais vendidos em {d.rotulo}, semana a semana</h3>
              <div className="tscroll"><table className="dt">
                <thead><tr><th>Modelo</th>{semNums.map((n) => <th key={n} className="r">S{n}</th>)}<th className="r">Total</th></tr></thead>
                <tbody>{d.top_modelos.slice(0, 15).map((m) => (
                  <tr key={m.modelo}><td><button className="link" onClick={() => openProduto('modelo', m.modelo)}>{m.modelo}</button><span className="d">{m.descricao}</span></td>
                    {semNums.map((n) => <td key={n} className="r">{m.semanas[n] ? n0(m.semanas[n]) : <span style={{ color: 'var(--muted)' }}>·</span>}</td>)}
                    <td className="r"><b>{n0(m.total)}</b></td></tr>))}</tbody>
              </table></div>
            </>
          )}
          <p className="note" style={{ marginBottom: 0 }}>{d.nota}</p>
        </>
      )}
    </Box>
  )
}

/** Vendas das listas diárias: semana a semana, dia a dia e comparações. Não depende do período escolhido. */
function DiaADia() {
  const { f, versao, openProduto, go } = useCtx()
  const st = useApi('/api/vendas/diario', { categoria: f.categoria }, [versao])
  const d = st.data
  if (st.error) return null
  if (!d) return <div className="skel" style={{ height: 300, marginBottom: 16 }} />
  if (d.status !== 'ok') return (
    <Box title="Vendas dia a dia" sub="Semana a semana, a partir das listas de vendidos do dia" className="mb"
      right={<button className="btn ghost" onClick={() => go('/dados/importar')}>Importar lista do dia</button>}>
      <Empty>{d.motivo}</Empty>
    </Box>
  )
  const cmp = (x, rot) => <small>{x.var_unidades === null || x.var_unidades === undefined ? 'sem base de comparação' : <><Delta v={x.var_unidades} /> {rot}</>}</small>
  const sa = d.semana_atual
  return (
    <Box title="Vendas dia a dia" className="mb"
      sub={`Listas de vendidos importadas de ${dataBR(d.primeiro_dia)} a ${dataBR(d.ultimo_dia)} (${n0(d.dias_lancados)} dias). Não depende do período escolhido no topo.`}
      right={<button className="btn ghost" onClick={() => go('/dados/importar')}>Importar lista do dia</button>}>
      <div className="kpi-mini">
        <div><span>Semana atual ({dataBR(sa.inicio).slice(0, 5)} em diante, {sa.dias} {sa.dias === 1 ? 'dia' : 'dias'})</span><b>{n0(sa.unidades)} un.</b> · {money(sa.faturamento)}{cmp(sa, 'vs mesmos dias da semana passada')}</div>
        <div><span>Últimos 7 dias</span><b>{n0(d.ultimos7.unidades)} un.</b> · {money(d.ultimos7.faturamento)}{cmp(d.ultimos7, 'vs 7 dias anteriores')}</div>
        <div><span>Último dia lançado ({dataBR(d.ultimo_dia).slice(0, 5)})</span><b>{n0(d.dias.at(-1)?.unidades)} un.</b> · {money(d.dias.at(-1)?.faturamento)}<small>melhor dia: {dataBR(d.melhor_dia.data).slice(0, 5)}, {n0(d.melhor_dia.unidades)} un.</small></div>
      </div>
      <div className="row c-wide" style={{ marginBottom: 8 }}>
        <div>
          <h3 className="sub-h">Vendas por semana</h3>
          <SemanasVendas data={d.semanas} />
        </div>
        <div>
          <h3 className="sub-h">Média de unidades por dia da semana</h3>
          <BarrasSimples data={d.dia_da_semana} dataKey="media" rotulo="dia" height={250} />
        </div>
      </div>
      <div className="row c-wide" style={{ marginBottom: 0 }}>
        <div>
          <h3 className="sub-h">Vendas por dia (últimos {d.dias.length} dias)</h3>
          <DiasVendas data={d.dias} />
        </div>
        <div>
          <h3 className="sub-h">Mais vendidos nos últimos 7 dias</h3>
          <ul className="list compacta">
            {d.top_7dias.slice(0, 7).map((t) => (
              <li key={t.chave}><div className="t"><button className="link" onClick={() => openProduto('modelo', t.chave)}>{t.chave}</button><span>{t.descricao}</span></div>
                <div className="v">{n0(t.unidades)} un.<small>{money(t.faturamento)}</small></div></li>))}
          </ul>
        </div>
      </div>
      <p className="note" style={{ marginBottom: 0 }}>{d.nota}{d.faturamento_estimado_pct ? ` Neste momento, ${n0(d.faturamento_estimado_pct)}% do faturamento diário é estimado (listas sem ticket médio).` : ''}</p>
    </Box>
  )
}

export function Produtos() {
  const { f, per, versao, openProduto } = useCtx()
  const st = useApi('/api/vendas/produtos', { inicio: per[0], fim: per[1], nivel: f.nivel, categoria: f.categoria }, [versao])
  return (
    <Load state={st} height={600}>{(d) => (
      <Box title={`Desempenho por ${NIVEL[f.nivel].toLowerCase()}`} sub={`${d.periodo.rotulo}. Variação contra o período anterior de mesma duração; estoque e cobertura são de hoje.`} flush="b">
        <DataTable rows={d.tabela} searchKeys={['chave', 'descricao']} initialSort={{ key: 'faturamento', dir: 'desc' }} columns={[
          { key: 'chave', label: NIVEL[f.nivel], sortValue: (r) => r.chave, render: (r) => <><button className="link" onClick={() => openProduto(f.nivel, r.chave)}>{r.chave}</button><span className="d">{r.descricao}</span></> },
          { key: 'unidades', label: 'Unidades', right: true, render: (r) => n0(r.unidades) },
          { key: 'faturamento', label: 'Faturamento', right: true, render: (r) => money(r.faturamento) },
          { key: 'preco_medio', label: 'Preço médio', right: true, render: (r) => money2(r.preco_medio) },
          { key: 'participacao', label: '% fat.', right: true, render: (r) => (r.participacao === null ? '—' : n1(r.participacao) + '%') },
          { key: 'var_faturamento', label: 'Var. fat.', right: true, render: (r) => <Delta v={r.var_faturamento} /> },
          { key: 'unidades_shopee', label: 'Shopee', right: true, render: (r) => (r.unidades ? n0((r.unidades_shopee || 0) / r.unidades * 100) + '%' : '—'), sortValue: (r) => (r.unidades ? (r.unidades_shopee || 0) / r.unidades : null) },
          { key: 'estoque', label: 'Estoque', right: true, render: (r) => n0(r.estoque) },
          { key: 'cobertura_dias', label: 'Cobertura', right: true, render: (r) => (r.cobertura_dias === null ? '—' : n0(r.cobertura_dias) + ' d') },
          { key: 'status_estoque', label: 'Situação', render: (r) => <Status s={r.status_estoque} /> },
          { key: 'curva', label: 'ABC', render: (r) => r.curva },
        ]} />
      </Box>
    )}</Load>
  )
}

export function Precos() {
  const { f, per, versao } = useCtx()
  const st = useApi('/api/vendas/precos', { inicio: per[0], fim: per[1], categoria: f.categoria }, [versao])
  return (
    <Load state={st} height={500}>{(d) => {
      const pr = d.precos
      return (
        <>
          <Stats>
            <Stat label="Preço médio no período" value={money2(d.kpis.preco_medio)} sub={d.kpis.comparacao ? <><Delta v={d.kpis.comparacao.preco_medio} /> vs período anterior</> : null} />
            {pr.status === 'ok' && <Stat label="Faixa que mais vendeu" value={`R$ ${pr.faixa_top.rotulo}`} sub={`${n0(pr.faixa_top.unidades)} unidades em ${pr.faixa_top.skus} SKUs`} />}
            {pr.status === 'ok' && <Stat label="Preço mais frequente" value={money(pr.precos_top[0]?.preco)} sub={`${n0(pr.precos_top[0]?.unidades)} unidades`} />}
          </Stats>
          <div className="row c-wide">
            <Box title="Unidades por faixa de preço" sub={d.periodo.rotulo}>
              {pr.status !== 'ok' ? <Empty>{pr.motivo}</Empty> : <PriceBins data={pr.faixas} />}
              <p className="note">{pr.nota}</p>
            </Box>
            <Box title="Preços que mais venderam" sub="Arredondados ao real" flush="b">
              {pr.status === 'ok' && <ul className="list">{pr.precos_top.map((p) => (
                <li key={p.preco}><div className="t"><b className="num">{money(p.preco)}</b></div><div className="v">{n0(p.unidades)}<small>unidades</small></div></li>))}</ul>}
            </Box>
          </div>
          <Box title="Preço médio por mês" sub="Todo o histórico, recalculado a cada mês">
            <MonthLine data={d.serie} dataKey="preco_medio" fmt={(v) => 'R$ ' + n0(v)} rows={[['Preço médio', (x) => money2(x.preco_medio)], ['Unidades', (x) => n0(x.unidades)]]} height={240} />
          </Box>
        </>
      )
    }}</Load>
  )
}

export function Historico() {
  const { f, meta, versao, openProduto, irParaMes } = useCtx()
  const st = useApi('/api/mensal', { categoria: f.categoria }, [versao])
  const completos = meta.meses.filter((m) => !m.parcial)
  const [a, setA] = useState(completos.at(-2)?.mes)
  const [b, setB] = useState(completos.at(-1)?.mes)
  const cmp = useApi('/api/comparar', { a, b, nivel: f.nivel, categoria: f.categoria }, [versao])
  return (
    <Load state={st} height={600}>{(d) => {
      const m = d.meses
      const lst = (items, s) => (
        <ul className="list">{items.filter((i) => (s > 0 ? i.delta_faturamento > 0 : i.delta_faturamento < 0)).slice(0, 8).map((i) => (
          <li key={i.chave}><div className="t"><button className="link" onClick={() => openProduto(f.nivel, i.chave)}>{i.chave}</button>
            <span>{money(i.faturamento_a)} → {money(i.faturamento_b)} · {n0(i.unidades_a)} → {n0(i.unidades_b)} un.</span></div>
            <div className="v" style={{ color: s > 0 ? 'var(--good-ink)' : 'var(--critical-ink)' }}>{s > 0 ? '+' : ''}{money(i.delta_faturamento)}</div></li>))}</ul>
      )
      return (
        <>
          <div className="row c2">
            <Box title="Faturamento por mês" sub="Clique em um mês para compará-lo com o anterior">
              <MonthBars data={m} dataKey="faturamento" selected={b}
                onSelect={(x) => { const i = m.findIndex((y) => y.mes === x.mes); if (i > 0) { setA(m[i - 1].mes); setB(x.mes) } }}
                rows={[['Faturamento', (x) => money(x.faturamento)], ['Por dia', (x) => money(x.faturamento_dia)]]} />
            </Box>
            <Box title="Unidades por mês" sub="Clique em um mês para abrir o resultado dele"
              right={b && <button className="btn ghost" onClick={() => irParaMes(b)}>Abrir {m.find((x) => x.mes === b)?.rotulo}</button>}>
              <MonthBars data={m} dataKey="unidades" color="var(--s2)" onSelect={(x) => irParaMes(x.mes)} rows={[['Unidades', (x) => n0(x.unidades)], ['Por dia', (x) => n1(x.unidades_dia)]]} />
            </Box>
          </div>
          <Box title="Mês a mês" sub="Variações envolvendo o mês parcial usam média diária" flush="b">
            <DataTable rows={m} initialSort={{ key: 'mes', dir: 'desc' }} pageSize={24} rowKey={(r) => r.mes} columns={[
              { key: 'mes', label: 'Mês', sortValue: (r) => r.mes, render: (r) => <button className="link" title="Abrir o resultado deste mês" onClick={() => irParaMes(r.mes)}>{r.rotulo}{r.parcial ? ` (parcial, ${r.dias} d)` : ''}</button> },
              { key: 'faturamento', label: 'Faturamento', right: true, render: (r) => money(r.faturamento) },
              { key: 'var_faturamento', label: 'Var.', right: true, render: (r) => <Delta v={r.var_faturamento} /> },
              { key: 'unidades', label: 'Unidades', right: true, render: (r) => n0(r.unidades) },
              { key: 'var_unidades', label: 'Var.', right: true, render: (r) => <Delta v={r.var_unidades} /> },
              { key: 'preco_medio', label: 'Preço médio', right: true, render: (r) => money2(r.preco_medio) },
              { key: 'faturamento_dia', label: 'Fat. por dia', right: true, render: (r) => money(r.faturamento_dia) },
              { key: 'skus_ativos', label: 'SKUs', right: true, render: (r) => n0(r.skus_ativos) },
              { key: 'unidades_shopee', label: 'Shopee', right: true, render: (r) => (r.unidades ? n0((r.unidades_shopee / r.unidades) * 100) + '%' : '—') },
              { key: 'economia_pe', label: 'Economia PE', right: true, render: (r) => money(r.economia_pe) },
              { key: 'vendas_perdidas_pares', label: 'Vendas perdidas', right: true, render: (r) => (r.vendas_perdidas_pares === null ? <span style={{ color: 'var(--muted)' }}>sem dados</span> : n1(r.vendas_perdidas_pares)) },
            ]} />
          </Box>
          <div style={{ height: 16 }} />
          <Box title="Comparar dois meses" sub={`Por ${NIVEL[f.nivel].toLowerCase()}`} right={
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <select className="input" value={a} onChange={(e) => setA(e.target.value)} aria-label="Primeiro mês">{meta.meses.map((x) => <option key={x.mes} value={x.mes}>{x.rotulo}</option>)}</select>
              <span style={{ color: 'var(--muted)' }}>com</span>
              <select className="input" value={b} onChange={(e) => setB(e.target.value)} aria-label="Segundo mês">{meta.meses.map((x) => <option key={x.mes} value={x.mes}>{x.rotulo}</option>)}</select>
            </div>}>
            <Load state={cmp} height={300}>{(c) => (
              <>
                <Stats>
                  {[['Faturamento', 'faturamento', money], ['Unidades', 'unidades', n0], ['Preço médio', 'preco_medio', money2], ['SKUs com venda', 'skus_vendidos', n0]].map(([t, k, fm]) => (
                    <Stat key={k} label={t} value={<span style={{ fontSize: 18 }}>{fm(c.a[k])} → {fm(c.b[k])}</span>}
                      sub={c.a[k] ? pct(((c.b[k] - c.a[k]) / c.a[k]) * 100) : null} />))}
                </Stats>
                {c.base !== 'total' && <p className="note" style={{ marginTop: -6 }}>Um dos meses é parcial: as diferenças por item usam o ritmo de 30 dias.</p>}
                <div className="row c2" style={{ marginBottom: 0 }}>
                  <div><h3 style={{ fontSize: 14, margin: '0 0 4px', fontWeight: 600 }}>Maiores altas em {c.b.rotulo}</h3><div style={{ margin: '0 -18px' }}>{lst(c.altas, 1)}</div></div>
                  <div><h3 style={{ fontSize: 14, margin: '0 0 4px', fontWeight: 600 }}>Maiores quedas em {c.b.rotulo}</h3><div style={{ margin: '0 -18px' }}>{lst(c.quedas, -1)}</div></div>
                </div>
              </>
            )}</Load>
          </Box>
        </>
      )
    }}</Load>
  )
}
