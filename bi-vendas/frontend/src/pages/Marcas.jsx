import { Fragment, useState } from 'react'
import { api } from '../api'
import { MarcasMes, corMarca } from '../charts'
import { useCtx } from '../ctx'
import { money, money2, n0, pct } from '../fmt'
import { Box, Load, Stat, Stats, useApi } from '../ui'

const ler = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v) } catch { return d } }
const gravar = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* sem armazenamento */ } }

function Seta({ v }) {
  if (v === null || v === undefined) return <span style={{ color: 'var(--muted)' }}>—</span>
  return <span className={v >= 0 ? 'seta-up' : 'seta-down'} style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{v >= 0 ? '▲' : '▼'} {pct(v)}</span>
}

/** Marcas do grupo Beira Rio: o que vendeu e o que foi comprado de cada uma. */
export default function Marcas() {
  const { per, versao, bump, openProduto } = useCtx()
  const [agrupar, setAgrupar] = useState(() => ler('bi.marcas.agrupar', false))
  const [aberta, setAberta] = useState(null)
  const [graf, setGraf] = useState('v_')
  const [erro, setErro] = useState(null)
  const st = useApi('/api/marcas', { inicio: per[0], fim: per[1], agrupar: agrupar ? 'true' : 'false' }, [versao])
  const trocar = (v) => { setAgrupar(v); gravar('bi.marcas.agrupar', v) }
  const corrigir = async (modelo, marca) => { setErro(null); try { await api.put('/api/marcas/manual', { modelo, marca }); bump() } catch (e) { setErro(e.message) } }
  return (
    <Load state={st} height={600}>{(d) => {
      const t = d.totais
      const lider = [...d.marcas].sort((a, b) => (b.faturamento || 0) - (a.faturamento || 0))[0]
      return (
        <>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 14 }}>
            <p className="lead" style={{ margin: 0, flex: '1 1 400px' }}>Vendas e compras de cada marca do grupo Beira Rio em <b>{d.periodo}</b>, com variação contra {d.anterior || '—'}{d.base_comparacao === 'média por dia' ? ' (pela média por dia, porque há mês parcial)' : ''}.</p>
            <label className="check" style={{ display: 'inline-flex', gap: 8, alignItems: 'center', fontSize: 14 }}>
              <input type="checkbox" checked={agrupar} onChange={(e) => trocar(e.target.checked)} /> Agrupar Molekinho + Molekinha
            </label>
          </div>
          {erro && <div className="alert bad">{erro}</div>}
          <Stats>
            <Stat label="Faturamento" value={money(t.faturamento)} sub={`${n0(t.unidades)} pares vendidos`} />
            <Stat label="Comprado (notas)" value={money(t.comprado_valor)} sub={`${n0(t.comprado_pares)} pares`} />
            <Stat label="Vendido ÷ comprado" value={t.comprado_pares ? n0(t.unidades / t.comprado_pares * 100) + '%' : '—'} sub="pares vendidos sobre pares comprados no período" />
            {lider && <Stat label="Marca que mais faturou" value={lider.marca} sub={`${n0(lider.pct_faturamento)}% do faturamento`} />}
          </Stats>
          <Box title="Por marca" sub="Clique numa marca para ver os modelos que mais venderam. Estoque é o de hoje; a receber vem dos pedidos em aberto do Omie." flush="b">
            <div className="tscroll"><table className="dt">
              <thead><tr><th>Marca</th><th className="r">Faturamento</th><th className="r">vs anterior</th><th className="r">Pares vendidos</th><th className="r">vs anterior</th>
                <th className="r">Preço médio</th><th className="r">Pares comprados</th><th className="r">Valor comprado</th><th className="r">Custo médio</th><th className="r">PE</th>
                <th className="r">Vendido ÷ comprado</th><th className="r">Estoque</th><th className="r">Dura</th><th className="r">A receber</th></tr></thead>
              <tbody>{d.marcas.map((m) => (
                <Fragment key={m.marca}>
                  <tr onClick={() => setAberta(aberta === m.marca ? null : m.marca)} style={{ cursor: 'pointer' }}>
                    <td><i className="sw" style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: corMarca(m.marca), marginRight: 8 }} /><b>{m.marca}</b>
                      <span className="d">{n0(m.modelos_vendidos)} modelos com venda · {n0(m.pct_faturamento)}% do faturamento{m.pct_comprado !== null ? ` · ${n0(m.pct_comprado)}% das compras` : ''}</span></td>
                    <td className="r">{money(m.faturamento)}</td><td className="r"><Seta v={m.var_faturamento} /></td>
                    <td className="r">{n0(m.unidades)}</td><td className="r"><Seta v={m.var_unidades} /></td>
                    <td className="r">{money2(m.preco_medio)}</td>
                    <td className="r">{n0(m.comprado_pares)}</td><td className="r">{money(m.comprado_valor)}</td><td className="r">{money2(m.custo_medio)}</td>
                    <td className="r">{m.pe_pct === null ? '—' : n0(m.pe_pct) + '%'}</td>
                    <td className="r">{m.vendido_sobre_comprado === null ? '—' : n0(m.vendido_sobre_comprado) + '%'}</td>
                    <td className="r">{n0(m.estoque)}</td><td className="r">{m.cobertura === null ? '—' : n0(m.cobertura) + ' d'}</td>
                    <td className={'r ' + (m.a_receber > 0 ? 'in' : 'dim')}>{n0(m.a_receber)}</td>
                  </tr>
                  {aberta === m.marca && (
                    <tr><td colSpan={14} style={{ background: 'var(--surface-2)' }}>
                      {(d.top[m.marca] || []).length ? (
                        <ol style={{ margin: '4px 0', paddingLeft: 20, columns: 2, fontSize: 13 }}>
                          {d.top[m.marca].map((x) => <li key={x.modelo}><button className="link" onClick={(e) => { e.stopPropagation(); openProduto('modelo', x.modelo) }}>{x.modelo}</button> · {n0(x.unidades)} pares · {money(x.faturamento)}<span style={{ color: 'var(--muted)' }}> · {(x.descricao || '').slice(0, 50)}</span></li>)}
                        </ol>) : <span style={{ fontSize: 13, color: 'var(--muted)' }}>Sem vendas no período.</span>}
                    </td></tr>)}
                </Fragment>))}</tbody>
            </table></div>
          </Box>
          <div style={{ height: 16 }} />
          <Box title={graf === 'v_' ? 'Pares vendidos por marca, mês a mês' : 'Pares comprados por marca, mês a mês'} sub="Últimos 12 meses"
            right={<span className="seg" role="group" aria-label="Ver"><button aria-pressed={graf === 'v_'} onClick={() => setGraf('v_')}>Vendas</button><button aria-pressed={graf === 'c_'} onClick={() => setGraf('c_')}>Compras</button></span>}>
            <MarcasMes data={d.serie} marcas={d.ordem} prefixo={graf} />
          </Box>
          {(d.n_deduzidas > 0 || d.sem_marca.length > 0) && (
            <Box title="Marca dos modelos sem descrição" className="mt"
              sub={`${n0(d.n_deduzidas)} modelos sem descrição de venda receberam a marca pelo código (1/3/6 Vizzano, 2 Molekinho/Molekinha, 4/8/9 Beira Rio, 5 Moleca, 7 Modare). Corrija aqui se algum estiver errado.`}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {[...d.sem_marca.map((x) => x.modelo), ...d.deduzidas].slice(0, 80).map((mod) => (
                  <label key={mod} className="ctl" style={{ gap: 6 }}><b>{mod}</b>
                    <select defaultValue="" onChange={(e) => corrigir(mod, e.target.value)} aria-label={`Marca do modelo ${mod}`}>
                      <option value="">{d.sem_marca.some((x) => x.modelo === mod) ? 'sem marca' : 'pelo código'}</option>
                      {d.nomes.map((n) => <option key={n} value={n}>{n}</option>)}
                    </select></label>))}
              </div>
            </Box>
          )}
          <p className="note">{d.nota}</p>
        </>
      )
    }}</Load>
  )
}
