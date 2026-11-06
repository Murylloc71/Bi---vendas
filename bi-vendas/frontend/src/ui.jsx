import { useEffect, useMemo, useState } from 'react'
import { api, filtroGlobal } from './api'
import { STATUS, STATUS_REPO, pct } from './fmt'

export function useApi(path, params, deps = []) {
  const [state, set] = useState({ data: null, error: null, loading: true })
  const key = JSON.stringify([path, params, filtroGlobal()])
  useEffect(() => {
    if (!path) return undefined
    let vivo = true
    set((s) => ({ ...s, loading: true, error: null }))
    api.get(path, params).then(
      (data) => vivo && set({ data, error: null, loading: false }),
      (error) => vivo && set({ data: null, error, loading: false }),
    )
    return () => { vivo = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ...deps])
  return state
}

/** Renderiza estados de carregamento/erro e entrega os dados ao filho. */
export function Load({ state, children, height = 320 }) {
  if (state.error) return <div className="err" role="alert">{state.error.message}</div>
  if (!state.data) return <div className="skel" style={{ height }} aria-label="Carregando" />
  return <div className={state.loading ? 'busy' : undefined}>{children(state.data)}</div>
}

export function Delta({ v, invert = false, suffix }) {
  if (v === null || v === undefined) return null
  const good = invert ? v < 0 : v > 0
  const cls = v === 0 ? '' : good ? 'up' : 'down'
  return <span className={`delta ${cls}`}>{v > 0 ? '▲' : v < 0 ? '▼' : ''} {pct(v)}{suffix ? ' ' + suffix : ''}</span>
}

export function Stats({ children }) { return <dl className="stats">{children}</dl> }
export function Stat({ label, value, sub, na, tone }) {
  return (
    <div className={`stat ${tone || ''}`}>
      <dt>{label}</dt>
      <dd className={na ? 'na' : 'num'}>{value}</dd>
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
}

export function Box({ title, sub, right, children, flush, className = '' }) {
  return (
    <section className={`box ${className}`}>
      {(title || right) && (
        <header className="box-h">
          <div>{title && <h2>{title}</h2>}{sub && <p>{sub}</p>}</div>
          {right}
        </header>
      )}
      <div className={flush === 'b' ? 'box-b flush-b' : flush ? 'box-b flush' : 'box-b'}>{children}</div>
    </section>
  )
}

export function Seg({ value, onChange, options, label }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map(([v, t]) => <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)}>{t}</button>)}
    </div>
  )
}

export function Empty({ title, children }) { return <div className="empty">{title && <b>{title}</b>}{children}</div> }

export function Status({ s, label }) {
  return <span className={`st ${s}`}><i aria-hidden="true" />{label !== undefined ? label : STATUS[s] || STATUS_REPO[s] || s}</span>
}

export function Summary({ r }) {
  if (!r) return null
  const col = (t, color, items) => (
    <section>
      <h3><i style={{ background: color }} aria-hidden="true" />{t}</h3>
      {items.length ? <ul>{items.map((x, i) => <li key={i}>{x}</li>)}</ul> : <div className="none">Nada a destacar.</div>}
    </section>
  )
  return (
    <>
      <div className="summary">
        {col('Pontos positivos', 'var(--good)', r.positivos)}
        {col('Problemas', 'var(--critical)', r.problemas)}
        {col('Oportunidades', 'var(--s1)', r.oportunidades)}
      </div>
      {r.notas?.length > 0 && <div className="summary-notes">{r.notas.map((n, i) => <div key={i}>{n}</div>)}</div>}
    </>
  )
}

/** Tabela com busca, ordenação e paginação. columns: {key, label, render?, right?, sortValue?, sortable?} */
export function DataTable({ rows, columns, searchKeys = [], initialSort, pageSize = 25, onRow, toolbar, empty = 'Nenhum registro.', rowKey }) {
  const [q, setQ] = useState('')
  const [sort, setSort] = useState(initialSort || { key: columns[0].key, dir: 'desc' })
  const [page, setPage] = useState(0)
  useEffect(() => setPage(0), [q, rows])
  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase()
    let r = rows || []
    if (t) r = r.filter((x) => searchKeys.some((k) => String(x[k] ?? '').toLowerCase().includes(t)))
    const col = columns.find((c) => c.key === sort.key)
    const val = col?.sortValue || ((x) => x[sort.key])
    return [...r].sort((a, b) => {
      const va = val(a), vb = val(b)
      if (va === vb) return 0
      if (va === null || va === undefined) return 1
      if (vb === null || vb === undefined) return -1
      const c = typeof va === 'number' && typeof vb === 'number' ? va - vb : String(va).localeCompare(String(vb), 'pt-BR')
      return sort.dir === 'asc' ? c : -c
    })
  }, [rows, q, sort, columns, searchKeys])
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const vis = filtered.slice(page * pageSize, (page + 1) * pageSize)
  const toggle = (k) => setSort((s) => (s.key === k ? { key: k, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key: k, dir: 'desc' }))
  return (
    <div>
      <div className="tbar">
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          {searchKeys.length > 0 && <input type="search" placeholder="Buscar código ou descrição" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar na tabela" style={{ width: 260 }} />}
          {toolbar}
        </div>
        <span className="count">{filtered.length.toLocaleString('pt-BR')} linhas</span>
      </div>
      <div className="tscroll">
        <table className="dt">
          <thead>
            <tr>{columns.map((c) => (
              <th key={c.key} className={c.right ? 'r' : ''} aria-sort={sort.key === c.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                {c.sortable === false ? c.label : <button type="button" onClick={() => toggle(c.key)}>{c.label}{sort.key === c.key ? (sort.dir === 'asc' ? ' ↑' : ' ↓') : ''}</button>}
              </th>))}
            </tr>
          </thead>
          <tbody>
            {vis.length === 0 && <tr><td colSpan={columns.length} style={{ color: 'var(--muted)', padding: 18 }}>{empty}</td></tr>}
            {vis.map((r, i) => (
              <tr key={rowKey ? rowKey(r) : r.chave || r.id || i}>
                {columns.map((c) => <td key={c.key} className={(c.right ? 'r ' : '') + (c.cls ? c.cls(r) : '')}>{c.render ? c.render(r, onRow) : r[c.key]}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="pager">
          <button className="btn" disabled={page === 0} onClick={() => setPage(page - 1)}>Anterior</button>
          <span>Página {page + 1} de {pages}</span>
          <button className="btn" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Próxima</button>
        </div>
      )}
    </div>
  )
}
