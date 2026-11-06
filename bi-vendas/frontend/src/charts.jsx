import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, LabelList, Legend, Line, LineChart, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { compact, n0, pct } from './fmt'

const axis = { stroke: 'var(--axis)', tick: { fill: 'var(--muted)', fontSize: 12 }, tickLine: false }

function Tip({ active, payload, rows, title }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="tt">
      <div className="tt-h">{title ? title(d) : d.rotulo}{d.parcial ? ` (parcial, ${d.dias} dias)` : ''}</div>
      {rows.map(([t, f, color]) => (
        <div className="tt-r" key={t}><span>{color && <i className="sw" style={{ background: color }} />}{t}</span><b>{f(d)}</b></div>
      ))}
    </div>
  )
}

/** Barras mensais de uma medida. Mês parcial mais claro; mês selecionado em destaque. */
export function MonthBars({ data, dataKey, rows, height = 220, color = 'var(--s1)', selected, onSelect, fmt = compact }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 14, right: 6, left: 0, bottom: 0 }} barCategoryGap="22%"
        onClick={onSelect && ((e) => { const d = e?.activePayload?.[0]?.payload; if (d) onSelect(d) })} style={onSelect ? { cursor: 'pointer' } : undefined}>
        <CartesianGrid vertical={false} stroke="var(--grid)" />
        <XAxis dataKey="rotulo" {...axis} />
        <YAxis {...axis} axisLine={false} width={56} tickFormatter={fmt} />
        <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<Tip rows={rows} />} />
        <Bar isAnimationActive={false} dataKey={dataKey} radius={[4, 4, 0, 0]} maxBarSize={42}>
          {data.map((d) => <Cell key={d.mes || d.rotulo} fill={color} fillOpacity={d.parcial ? 0.38 : selected && selected !== d.mes ? 0.5 : 1} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Período atual x período anterior, mês a mês (mesma escala). */
export function CompareBars({ atual, anterior, dataKey, fmtTip, height = 230, onSelect }) {
  const data = atual.map((m, i) => ({ ...m, ant: anterior?.[i]?.[dataKey] ?? null, antRot: anterior?.[i]?.rotulo }))
  return (
    <>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 14, right: 6, left: 0, bottom: 0 }} barGap={2} barCategoryGap="26%"
          onClick={onSelect && ((e) => { const d = e?.activePayload?.[0]?.payload; if (d) onSelect(d) })} style={onSelect ? { cursor: 'pointer' } : undefined}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="rotulo" {...axis} />
          <YAxis {...axis} axisLine={false} width={56} tickFormatter={compact} />
          <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<Tip rows={[
            ['Período atual', (d) => fmtTip(d[dataKey]), 'var(--s1)'],
            ...(anterior ? [[`Anterior`, (d) => (d.ant === null ? '—' : fmtTip(d.ant) + ` (${d.antRot})`), 'var(--s-prev)']] : []),
          ]} />} />
          {anterior && <Bar isAnimationActive={false} dataKey="ant" fill="var(--s-prev)" radius={[4, 4, 0, 0]} maxBarSize={30} />}
          <Bar isAnimationActive={false} dataKey={dataKey} radius={[4, 4, 0, 0]} maxBarSize={30}>
            {data.map((d) => <Cell key={d.mes} fill="var(--s1)" fillOpacity={d.parcial ? 0.45 : 1} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="legend" style={{ marginTop: 6 }}>
        <span><i className="sw" style={{ background: 'var(--s1)' }} />Período selecionado</span>
        {anterior && <span><i className="sw" style={{ background: 'var(--s-prev)' }} />Período anterior de mesma duração</span>}
      </div>
    </>
  )
}

export function MonthLine({ data, dataKey, rows, height = 220, color = 'var(--s1)', fmt = compact }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 12, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--grid)" />
        <XAxis dataKey="rotulo" {...axis} />
        <YAxis {...axis} axisLine={false} width={56} domain={['auto', 'auto']} tickFormatter={fmt} />
        <Tooltip cursor={{ stroke: 'var(--axis)' }} content={<Tip rows={rows} />} />
        <Line isAnimationActive={false} type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2} dot={{ r: 3.5, strokeWidth: 2, fill: 'var(--surface)' }} activeDot={{ r: 5 }} />
      </LineChart>
    </ResponsiveContainer>
  )
}

export function PriceBins({ data, height = 240 }) {
  const top = Math.max(...data.map((d) => d.unidades))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 22, right: 6, left: 0, bottom: 0 }} barCategoryGap="14%">
        <CartesianGrid vertical={false} stroke="var(--grid)" />
        <XAxis dataKey="rotulo" {...axis} interval={0} />
        <YAxis {...axis} axisLine={false} width={50} tickFormatter={compact} />
        <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<Tip title={(d) => `R$ ${d.rotulo}`} rows={[['Unidades', (d) => n0(d.unidades)], ['SKUs', (d) => n0(d.skus)]]} />} />
        <Bar isAnimationActive={false} dataKey="unidades" radius={[4, 4, 0, 0]}>
          {data.map((d) => <Cell key={d.rotulo} fill="var(--s1)" fillOpacity={d.unidades === top ? 1 : 0.42} />)}
          <LabelList dataKey="unidades" position="top" content={({ x, y, width, value }) => (value === top ? (
            <text x={x + width / 2} y={y - 7} textAnchor="middle" fontSize={12} fontWeight={600} fill="var(--ink)">{n0(value)}</text>) : null)} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Entregas previstas por semana; semanas com a previsão já passada aparecem como faturado. */
export function WeekBars({ data, height = 220, onSelect }) {
  return (
    <>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 14, right: 6, left: 0, bottom: 0 }} barCategoryGap="18%">
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="rotulo" {...axis} />
          <YAxis {...axis} axisLine={false} width={50} tickFormatter={compact} />
          <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<Tip title={(d) => `Semana de ${d.rotulo}${d.vencida ? ' (faturado)' : ''}`}
            rows={[['Pares', (d) => n0(d.pares)], ['Valor', (d) => 'R$ ' + compact(d.valor)], ['Pedidos', (d) => n0(d.pedidos)]]} />} />
          <Bar isAnimationActive={false} dataKey="pares" radius={[4, 4, 0, 0]} maxBarSize={36} onClick={onSelect}>
            {data.map((d) => <Cell key={d.semana} fill={d.vencida ? 'var(--s1)' : 'var(--inbound)'} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="legend" style={{ marginTop: 6 }}>
        <span><i className="sw" style={{ background: 'var(--inbound)' }} />Previsto</span>
        <span><i className="sw" style={{ background: 'var(--s1)' }} />Faturado, ainda não recebido</span>
      </div>
    </>
  )
}

/** Barra 100% horizontal com legenda tabular. */
export function StackBar({ parts, fmt = n0, unit = '' }) {
  const total = parts.reduce((a, p) => a + (p.value || 0), 0)
  if (!total) return null
  return (
    <div>
      <div className="bar100" role="img" aria-label={parts.map((p) => `${p.label}: ${fmt(p.value)}`).join(', ')}>
        {parts.filter((p) => p.value > 0).map((p) => <div key={p.label} style={{ flex: p.value, background: p.color }} title={`${p.label}: ${fmt(p.value)}${unit}`} />)}
      </div>
      <div className="leg-tab">
        {parts.map((p) => [
          <span key={p.label + 'a'} className="legend"><span><i className="sw" style={{ background: p.color }} />{p.label}</span></span>,
          <span key={p.label + 'b'} className="num" style={{ fontWeight: 600 }}>{fmt(p.value)}{unit}</span>,
          <span key={p.label + 'c'} className="num" style={{ color: 'var(--muted)' }}>{p.extra ?? pct((p.value / total) * 100, 0).replace('+', '')}</span>,
        ])}
      </div>
    </div>
  )
}

const CANAL_CORES = { ml: 'var(--s1)', sh: 'var(--s2)', outros: 'var(--s-prev)' }
const reais = (v) => (v === null || v === undefined ? '—' : 'R$ ' + compact(v))

function Legenda({ itens }) {
  return <div className="legend" style={{ marginTop: 6 }}>{itens.map(([t, c, tipo]) => (
    <span key={t}><i className="sw" style={tipo === 'linha' ? { background: c, height: 3, borderRadius: 2 } : { background: c }} />{t}</span>))}</div>
}

/** Vendas por semana: unidades empilhadas por canal (barras) e faturamento (linha, eixo da direita). */
export function SemanasVendas({ data: bruto, height = 260 }) {
  // a linha de faturamento só liga semanas completas; a semana em andamento fica com barra clara
  const data = bruto.map((d) => ({ ...d, fat_completa: d.dias_com_dados === 7 ? d.faturamento : null }))
  const temOutros = data.some((d) => d.unidades_outros)
  const parcial = data.some((d) => d.dias_com_dados && d.dias_com_dados < 7)
  return (
    <>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 14, right: 4, left: 0, bottom: 0 }} barCategoryGap="22%">
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="rotulo" {...axis} />
          <YAxis yAxisId="u" {...axis} axisLine={false} width={48} tickFormatter={compact} />
          <YAxis yAxisId="f" orientation="right" {...axis} axisLine={false} width={64} tickFormatter={(v) => compact(v).replace(' ', '\u00a0')} />
          <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<Tip title={(d) => `Semana ${d.rotulo} a ${d.ate}${d.dias_com_dados && d.dias_com_dados < 7 ? ` (${d.dias_com_dados} de 7 dias)` : ''}`} rows={[
            ['Unidades', (d) => n0(d.unidades)], ['Mercado Livre', (d) => n0(d.unidades_ml), CANAL_CORES.ml], ['Shopee', (d) => n0(d.unidades_shopee), CANAL_CORES.sh],
            ...(temOutros ? [['Canal não informado', (d) => n0(d.unidades_outros), CANAL_CORES.outros]] : []),
            ['Faturamento', (d) => reais(d.faturamento), 'var(--ink)'], ['Média por dia', (d) => (d.media_dia === null ? '—' : n0(d.media_dia) + ' un.')]]} />} />
          {[['unidades_ml', CANAL_CORES.ml], ['unidades_shopee', CANAL_CORES.sh], ...(temOutros ? [['unidades_outros', CANAL_CORES.outros]] : [])].map(([k, cor], i, arr) => (
            <Bar key={k} yAxisId="u" isAnimationActive={false} dataKey={k} stackId="c" fill={cor} maxBarSize={40} radius={i === arr.length - 1 ? [4, 4, 0, 0] : 0}>
              {data.map((d) => <Cell key={d.semana} fillOpacity={d.dias_com_dados && d.dias_com_dados < 7 ? 0.4 : 1} />)}
            </Bar>))}
          <Line yAxisId="f" isAnimationActive={false} type="linear" dataKey="fat_completa" stroke="var(--ink)" strokeWidth={2} connectNulls dot={{ r: 3, strokeWidth: 2, fill: 'var(--surface)' }} />
        </ComposedChart>
      </ResponsiveContainer>
      <Legenda itens={[['Mercado Livre', CANAL_CORES.ml], ['Shopee', CANAL_CORES.sh], ...(temOutros ? [['Não informado', CANAL_CORES.outros]] : []), ['Faturamento (semanas completas)', 'var(--ink)', 'linha']]} />
      {parcial && <p className="note" style={{ margin: '4px 0 0' }}>Barras claras: semanas com dias sem lista importada (incluindo a semana em andamento).</p>}
    </>
  )
}

/** Unidades por dia, empilhadas por canal; dias sem lista importada ficam vazios. */
export function DiasVendas({ data, height = 220 }) {
  const temOutros = data.some((d) => d.unidades_outros)
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 10, right: 4, left: 0, bottom: 0 }} barCategoryGap="16%">
        <CartesianGrid vertical={false} stroke="var(--grid)" />
        <XAxis dataKey="rotulo" {...axis} interval="preserveStartEnd" minTickGap={18} tickFormatter={(v) => v.slice(4)} />
        <YAxis {...axis} axisLine={false} width={44} tickFormatter={compact} />
        <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<Tip rows={[
          ['Unidades', (d) => (d.com_dados ? n0(d.unidades) : 'sem lista importada')],
          ['Mercado Livre', (d) => n0(d.unidades_ml), CANAL_CORES.ml], ['Shopee', (d) => n0(d.unidades_shopee), CANAL_CORES.sh],
          ['Faturamento', (d) => reais(d.faturamento)]]} />} />
        <Bar isAnimationActive={false} dataKey="unidades_ml" stackId="c" fill={CANAL_CORES.ml} />
        <Bar isAnimationActive={false} dataKey="unidades_shopee" stackId="c" fill={CANAL_CORES.sh} radius={temOutros ? 0 : [3, 3, 0, 0]} />
        {temOutros && <Bar isAnimationActive={false} dataKey="unidades_outros" stackId="c" fill={CANAL_CORES.outros} radius={[3, 3, 0, 0]} />}
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Barras simples com rótulo de categoria (ex.: média por dia da semana). */
export function BarrasSimples({ data, dataKey, rotulo = 'rotulo', height = 200, color = 'var(--s1)', fmt = n0, destaque = true }) {
  const top = Math.max(...data.map((d) => d[dataKey] || 0))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 22, right: 4, left: 0, bottom: 0 }} barCategoryGap="20%">
        <CartesianGrid vertical={false} stroke="var(--grid)" />
        <XAxis dataKey={rotulo} {...axis} interval={0} />
        <YAxis {...axis} axisLine={false} width={44} tickFormatter={compact} />
        <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<Tip title={(d) => d[rotulo]} rows={[['Média', (d) => fmt(d[dataKey])]]} />} />
        <Bar isAnimationActive={false} dataKey={dataKey} radius={[4, 4, 0, 0]} maxBarSize={44}>
          {data.map((d) => <Cell key={d[rotulo]} fill={color} fillOpacity={!destaque || d[dataKey] === top ? 1 : 0.45} />)}
          <LabelList dataKey={dataKey} position="top" content={({ x, y, width, value }) => (value ? (
            <text x={x + width / 2} y={y - 6} textAnchor="middle" fontSize={11.5} fill="var(--ink-2)">{fmt(value)}</text>) : null)} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Unidades por canal, mês a mês (barras empilhadas). */
export function CanaisMes({ data, height = 230, selecionados }) {
  return (
    <>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 10, right: 4, left: 0, bottom: 0 }} barCategoryGap="24%">
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="rotulo" {...axis} />
          <YAxis {...axis} axisLine={false} width={58} tickFormatter={compact} />
          <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<Tip rows={[
            ['Mercado Livre', (d) => `${n0(d.unidades_ml)} (${d.unidades ? Math.round(d.unidades_ml / d.unidades * 100) : 0}%)`, CANAL_CORES.ml],
            ['Shopee', (d) => `${n0(d.unidades_shopee)} (${d.unidades ? Math.round(d.unidades_shopee / d.unidades * 100) : 0}%)`, CANAL_CORES.sh]]} />} />
          {[['unidades_ml', CANAL_CORES.ml], ['unidades_shopee', CANAL_CORES.sh]].map(([k, cor], i) => (
            <Bar key={k} isAnimationActive={false} dataKey={k} stackId="c" fill={cor} maxBarSize={38} radius={i ? [4, 4, 0, 0] : 0}>
              {data.map((d) => <Cell key={d.mes} fillOpacity={selecionados && !selecionados.includes(d.mes) ? 0.35 : 1} />)}
            </Bar>))}
        </BarChart>
      </ResponsiveContainer>
      <Legenda itens={[['Mercado Livre', CANAL_CORES.ml], ['Shopee', CANAL_CORES.sh]]} />
    </>
  )
}

/** Curva de concentração (Pareto): % dos itens x % acumulado do faturamento. */
export function Pareto({ data, itens80, total, height = 230 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 12, right: 12, left: 0, bottom: 0 }}>
        <defs><linearGradient id="gpar" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--s1)" stopOpacity={0.35} /><stop offset="100%" stopColor="var(--s1)" stopOpacity={0.03} /></linearGradient></defs>
        <CartesianGrid vertical={false} stroke="var(--grid)" />
        <XAxis dataKey="pct_itens" type="number" domain={[0, 100]} ticks={[0, 20, 40, 60, 80, 100]} {...axis} tickFormatter={(v) => v + '%'} />
        <YAxis {...axis} axisLine={false} width={44} domain={[0, 100]} ticks={[0, 50, 80, 100]} tickFormatter={(v) => v + '%'} />
        <Tooltip cursor={{ stroke: 'var(--axis)' }} content={<Tip title={(d) => `${n0(d.itens)} de ${n0(total)} modelos (${d.pct_itens}%)`} rows={[['Faturamento acumulado', (d) => d.pct_fat + '%']]} />} />
        <ReferenceLine y={80} stroke="var(--s2)" strokeDasharray="4 4" />
        <ReferenceLine x={total ? Math.round(itens80 / total * 1000) / 10 : 0} stroke="var(--s2)" strokeDasharray="4 4"
          label={{ value: `${n0(itens80)} modelos = 80%`, position: 'insideBottomRight', fill: 'var(--ink-2)', fontSize: 12, offset: 8 }} />
        <Area isAnimationActive={false} type="monotone" dataKey="pct_fat" stroke="var(--s1)" strokeWidth={2} fill="url(#gpar)" />
      </AreaChart>
    </ResponsiveContainer>
  )
}

/** Barras horizontais divergentes: quem mais ganhou e perdeu faturamento (R$). */
export function Divergente({ data, height, onSelect }) {
  const h = height || Math.max(180, data.length * 30 + 20)
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 0, bottom: 0 }} barCategoryGap="22%"
        onClick={onSelect && ((e) => { const d = e?.activePayload?.[0]?.payload; if (d) onSelect(d) })} style={onSelect ? { cursor: 'pointer' } : undefined}>
        <CartesianGrid horizontal={false} stroke="var(--grid)" />
        <XAxis type="number" {...axis} tickFormatter={(v) => 'R$' + compact(v)} />
        <YAxis type="category" dataKey="chave" {...axis} axisLine={false} width={108} tick={{ fill: 'var(--ink-2)', fontSize: 12 }} />
        <ReferenceLine x={0} stroke="var(--axis)" />
        <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<Tip title={(d) => `${d.chave} · ${d.descricao?.slice(0, 48) || ''}`} rows={[
          ['Diferença', (d) => (d.delta > 0 ? '+' : '−') + 'R$ ' + compact(Math.abs(d.delta))], ['Variação', (d) => pct(d.var)]]} />} />
        <Bar isAnimationActive={false} dataKey="delta" radius={3}>
          {data.map((d) => <Cell key={d.chave} fill={d.delta >= 0 ? 'var(--good)' : 'var(--critical)'} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Rosca: participação no faturamento (ex.: por faixa de preço). */
const ROSCA = ['#2a78d6', '#eb6834', '#0ca30c', '#8b5cf6', '#f0a54a', '#14b8a6', '#db2777', '#64748b', '#a3a3a3', '#0ea5e9']
export function Rosca({ data, dataKey, nome = 'rotulo', height = 240, fmt = (v) => 'R$ ' + compact(v) }) {
  const total = data.reduce((a, d) => a + (d[dataKey] || 0), 0) || 1
  return (
    <div className="rosca">
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Tooltip content={({ active, payload }) => (active && payload?.length ? (
            <div className="tt"><div className="tt-h">{payload[0].payload[nome]}</div>
              <div className="tt-r"><span>Faturamento</span><b>{fmt(payload[0].payload[dataKey])}</b></div>
              <div className="tt-r"><span>Participação</span><b>{Math.round(payload[0].payload[dataKey] / total * 1000) / 10}%</b></div></div>) : null)} />
          <Pie isAnimationActive={false} data={data} dataKey={dataKey} nameKey={nome} innerRadius="58%" outerRadius="88%" paddingAngle={1.5} stroke="var(--surface)">
            {data.map((d, i) => <Cell key={d[nome]} fill={ROSCA[i % ROSCA.length]} />)}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <ul className="rosca-leg">{data.map((d, i) => (
        <li key={d[nome]}><i className="sw" style={{ background: ROSCA[i % ROSCA.length] }} /><span>R$ {d[nome]}</span><b>{Math.round(d[dataKey] / total * 100)}%</b></li>))}</ul>
    </div>
  )
}

/** Ranking em barras horizontais (ex.: modelos mais comprados). */
export function RankingBarras({ data, dataKey, rotulo = 'chave', height, color = 'var(--s1)', fmt = n0, onSelect, titulo }) {
  const h = height || Math.max(200, data.length * 26 + 16)
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={data} layout="vertical" margin={{ top: 2, right: 44, left: 0, bottom: 0 }} barCategoryGap="20%"
        onClick={onSelect && ((e) => { const d = e?.activePayload?.[0]?.payload; if (d) onSelect(d) })} style={onSelect ? { cursor: 'pointer' } : undefined}>
        <XAxis type="number" hide />
        <YAxis type="category" dataKey={rotulo} {...axis} axisLine={false} width={96} tick={{ fill: 'var(--ink-2)', fontSize: 12 }} interval={0} />
        <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<Tip title={titulo || ((d) => d[rotulo])} rows={[['Pares', (d) => fmt(d[dataKey])]]} />} />
        <Bar isAnimationActive={false} dataKey={dataKey} fill={color} radius={[0, 4, 4, 0]}>
          <LabelList dataKey={dataKey} position="right" content={({ x, y, width, height: hh, value }) => (
            <text x={x + width + 6} y={y + hh / 2 + 4} fontSize={11.5} fill="var(--ink-2)">{fmt(value)}</text>)} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Pares comprados por mês, pronta-entrega x programado. */
export function ComprasMes({ data, height = 240 }) {
  return (
    <>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 10, right: 4, left: 0, bottom: 0 }} barCategoryGap="24%">
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="rotulo" {...axis} />
          <YAxis {...axis} axisLine={false} width={52} tickFormatter={compact} />
          <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<Tip rows={[['Programado', (d) => n0(d.prog), 'var(--s1)'], ['Pronta-entrega', (d) => n0(d.pe), 'var(--s2)'], ['Total', (d) => n0(d.pares)]]} />} />
          <Bar isAnimationActive={false} dataKey="prog" stackId="c" fill="var(--s1)" maxBarSize={38} />
          <Bar isAnimationActive={false} dataKey="pe" stackId="c" fill="var(--s2)" maxBarSize={38} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
      <Legenda itens={[['Programado', 'var(--s1)'], ['Pronta-entrega', 'var(--s2)']]} />
    </>
  )
}

/** Vendas por mês de um produto, empilhadas por marketplace (passe o mouse para ver cada canal). */
export function VendasCanalMes({ data, height = 210 }) {
  const temOutros = data.some((d) => d.unidades_outros)
  return (
    <>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 10, right: 4, left: 0, bottom: 0 }} barCategoryGap="22%">
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="rotulo" {...axis} />
          <YAxis {...axis} axisLine={false} width={40} tickFormatter={compact} />
          <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<Tip title={(d) => d.rotulo + (d.parcial ? ' (parcial)' : '')} rows={[
            ['Mercado Livre', (d) => `${n0(d.unidades_ml)} un.${d.unidades ? ` (${Math.round(d.unidades_ml / d.unidades * 100)}%)` : ''}`, CANAL_CORES.ml],
            ['Shopee', (d) => `${n0(d.unidades_shopee)} un.${d.unidades ? ` (${Math.round(d.unidades_shopee / d.unidades * 100)}%)` : ''}`, CANAL_CORES.sh],
            ...(temOutros ? [['Sem canal no arquivo', (d) => `${n0(d.unidades_outros)} un.`, CANAL_CORES.outros]] : []),
            ['Total', (d) => `${n0(d.unidades)} un.`], ['Faturamento', (d) => reais(d.faturamento)], ['Preço médio', (d) => (d.preco_medio ? 'R$ ' + d.preco_medio.toFixed(2).replace('.', ',') : '—')]]} />} />
          {[['unidades_ml', CANAL_CORES.ml], ['unidades_shopee', CANAL_CORES.sh], ...(temOutros ? [['unidades_outros', CANAL_CORES.outros]] : [])].map(([k, cor], i, arr) => (
            <Bar key={k} isAnimationActive={false} dataKey={k} stackId="c" fill={cor} radius={i === arr.length - 1 ? [3, 3, 0, 0] : 0}>
              {data.map((d) => <Cell key={d.mes} fillOpacity={d.parcial ? 0.5 : 1} />)}
            </Bar>))}
        </BarChart>
      </ResponsiveContainer>
      <Legenda itens={[['Mercado Livre', CANAL_CORES.ml], ['Shopee', CANAL_CORES.sh], ...(temOutros ? [['Sem canal', CANAL_CORES.outros]] : [])]} />
    </>
  )
}

/** Semanas do mês x mesmas semanas do mês anterior (unidades; tooltip com média por dia e variação). */
export function SemanasComparadas({ data, mes, anterior, height = 240 }) {
  const rows = data.map((s) => ({ ...s, atual_un: s.unidades, ant_un: s.anterior?.unidades ?? null }))
  return (
    <>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={rows} margin={{ top: 14, right: 4, left: 0, bottom: 0 }} barGap={3} barCategoryGap="24%">
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="rotulo" {...axis} />
          <YAxis {...axis} axisLine={false} width={56} tickFormatter={compact} />
          <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<Tip title={(d) => `${d.rotulo} (${d.periodo})`} rows={[
            [mes, (d) => (d.dias_com_dados ? `${n0(d.unidades)} un. · ${n0(d.media_dia)}/dia${d.completa ? '' : ` (${d.dias_com_dados} de ${d.dias} dias)`}` : 'sem planilha'), 'var(--s1)'],
            [anterior, (d) => (d.anterior?.dias_com_dados ? `${n0(d.anterior.unidades)} un. · ${n0(d.anterior.media_dia)}/dia` : 'sem planilha'), 'var(--s-prev)'],
            ['Variação (média/dia)', (d) => (d.var_media_dia === null || d.var_media_dia === undefined ? '—' : pct(d.var_media_dia))],
            ['Faturamento', (d) => reais(d.faturamento)]]} />} />
          <Bar isAnimationActive={false} dataKey="ant_un" fill="var(--s-prev)" radius={[4, 4, 0, 0]} maxBarSize={34} />
          <Bar isAnimationActive={false} dataKey="atual_un" fill="var(--s1)" radius={[4, 4, 0, 0]} maxBarSize={34}>
            {rows.map((d) => <Cell key={d.semana} fillOpacity={d.completa ? 1 : 0.5} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <Legenda itens={[[mes, 'var(--s1)'], [anterior, 'var(--s-prev)']]} />
    </>
  )
}

const COR_MARCA = { 'Vizzano': '#2a78d6', 'Modare': '#eb6834', 'Moleca': '#db2777', 'Molekinho': '#0ca30c', 'Molekinha': '#8b5cf6',
  'Molekinho/Molekinha': '#0ca30c', 'Actvitta': '#14b8a6', 'Beira Rio': '#f0a54a', 'Sem marca identificada': '#a3a3a3' }
export const corMarca = (m) => COR_MARCA[m] || '#64748b'

/** Barras empilhadas por marca, mês a mês (prefixo "v_" = vendas, "c_" = compras). */
export function MarcasMes({ data, marcas, prefixo = 'v_', height = 260, unidade = 'un.' }) {
  return (
    <>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 10, right: 4, left: 0, bottom: 0 }} barCategoryGap="22%">
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="rotulo" {...axis} />
          <YAxis {...axis} axisLine={false} width={62} tickFormatter={compact} />
          <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={<Tip title={(d) => d.rotulo + (d.parcial ? ' (parcial)' : '')} rows={[
            ...marcas.map((m) => [m, (d) => `${n0(d[prefixo + m])} ${unidade}`, corMarca(m)]),
            ['Total', (d) => `${n0(marcas.reduce((a, m) => a + (d[prefixo + m] || 0), 0))} ${unidade}`]]} />} />
          {marcas.map((m, i) => <Bar key={m} isAnimationActive={false} dataKey={prefixo + m} stackId="m" fill={corMarca(m)} maxBarSize={40} radius={i === marcas.length - 1 ? [4, 4, 0, 0] : 0} />)}
        </BarChart>
      </ResponsiveContainer>
      <Legenda itens={marcas.map((m) => [m, corMarca(m)])} />
    </>
  )
}
