import { useState } from 'react'
import { api } from '../api'
import { Pareto } from '../charts'
import { useCtx } from '../ctx'
import { money, n0, pct } from '../fmt'
import { Box, Empty, Load, Stat, Stats, useApi } from '../ui'

const COR = { A: 'var(--s1)', B: 'var(--s2)', C: 'var(--s-prev)' }

/** Seta + porcentagem de variação (verde subindo, vermelho caindo). */
function Seta({ v, grande }) {
  if (v === null || v === undefined) return <span style={{ color: 'var(--muted)' }}>—</span>
  const up = v > 0
  return <span className={v === 0 ? '' : up ? 'seta-up' : 'seta-down'} style={{ fontWeight: 600, fontSize: grande ? 15 : undefined, whiteSpace: 'nowrap' }}>{v === 0 ? '■' : up ? '▲' : '▼'} {pct(v)}</span>
}

/** Curva ABC (Pareto) por modelo, a partir das vendas; a mesma classificação do filtro "Curva" do topo. */
export default function CurvaABC() {
  const { f, per, versao, setFiltro, openProduto, bump } = useCtx()
  const cat = f.categoria === 'todos' ? 'calcado' : f.categoria
  const st = useApi('/api/curva', { categoria: cat, inicio: per[0], fim: per[1] }, [versao])
  const [classe, setClasse] = useState(null)
  const [busca, setBusca] = useState('')
  const [pag, setPag] = useState(0)
  const [erro, setErro] = useState(null)
  const salvar = async (mud) => {
    setErro(null)
    try { await api.put(`/api/curva/config?categoria=${cat}&inicio=${per[0]}&fim=${per[1]}`, { ...st.data.config, ...mud }); bump() } catch (e) { setErro(e.message) }
  }
  return (
    <Load state={st} height={600}>{(d) => {
      if (!d.itens.length) return <Empty>Sem vendas no período base para montar a curva.</Empty>
      const c = d.config
      const t = busca.trim().toLowerCase()
      const lista = d.itens.filter((x) => (!classe || x.classe === classe) && (!t || x.modelo.toLowerCase().includes(t) || (x.descricao || '').toLowerCase().includes(t)))
      const POR = 30
      const pagina = lista.slice(pag * POR, pag * POR + POR)
      return (
        <>
          <p className="lead">Modelos ordenados pelo {c.criterio === 'faturamento' ? 'faturamento' : 'número de unidades vendidas'} de {d.meses[0]} a {d.meses[1]} ({d.categoria === 'calcado' ? 'calçados' : 'outros produtos'}; cada categoria tem a sua curva).
            Curva A = os primeiros até somar {n0(c.limite_a)}%; B = até {n0(c.limite_b)}%; C = o resto. Use o seletor <b>Curva</b> no topo para ver qualquer tela só com uma curva.</p>
          {erro && <div className="alert bad">{erro}</div>}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginBottom: 16 }}>
            <label className="ctl">Base
              <select value={c.meses} onChange={(e) => salvar({ meses: Number(e.target.value) })} aria-label="Meses da base">
                {[1, 3, 6, 12].map((m) => <option key={m} value={m}>últimos {m} {m === 1 ? 'mês' : 'meses'}</option>)}
              </select></label>
            <label className="ctl">Critério
              <select value={c.criterio} onChange={(e) => salvar({ criterio: e.target.value })} aria-label="Critério">
                <option value="faturamento">Faturamento</option><option value="unidades">Unidades</option>
              </select></label>
            <label className="ctl">Curva A até
              <select value={c.limite_a} onChange={(e) => salvar({ limite_a: Number(e.target.value) })} aria-label="Limite da curva A">
                {[70, 75, 80, 85].map((v) => <option key={v} value={v}>{v}%</option>)}
              </select></label>
            <label className="ctl">Curva B até
              <select value={c.limite_b} onChange={(e) => salvar({ limite_b: Number(e.target.value) })} aria-label="Limite da curva B">
                {[90, 95, 97].map((v) => <option key={v} value={v}>{v}%</option>)}
              </select></label>
          </div>
          {d.comparacao && (
            <div className="strip" style={{ marginBottom: 12 }}>
              <span>Vendas de cada curva em <b>{d.comparacao.periodo}</b> comparadas com <b>{d.comparacao.anterior || '—'}</b> ({d.comparacao.criterio}{d.comparacao.base === 'média por dia' ? ', pela média por dia porque há mês parcial' : ''}). Troque o período no topo.</span>
            </div>
          )}
          <div className="row c3" style={{ marginBottom: 12 }}>
            {d.resumo.map((r) => (
              <div key={r.classe} className="box" style={{ padding: '14px 16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
                  <span style={{ fontSize: 13, color: 'var(--muted)' }}>Curva <b style={{ color: COR[r.classe] }}>{r.classe}</b> em {d.comparacao?.periodo}</span>
                  <Seta v={r.periodo_var} grande />
                </div>
                <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{c.criterio === 'faturamento' ? money(r.periodo_faturamento) : `${n0(r.periodo_unidades)} un.`}</div>
                <div style={{ fontSize: 12.5, color: 'var(--ink-2)' }}>{c.criterio === 'faturamento' ? `${n0(r.periodo_unidades)} unidades` : money(r.periodo_faturamento)} · vs {d.comparacao?.anterior || '—'}</div>
              </div>))}
          </div>
          <Stats>
            {d.resumo.map((r) => (
              <Stat key={r.classe} label={`Curva ${r.classe}`} value={`${n0(r.modelos)} modelos`}
                sub={`${n0(r.pct_modelos)}% dos modelos · ${n0(r.pct_faturamento)}% do faturamento · estoque ${n0(r.estoque)} (${r.cobertura === null ? '—' : n0(r.cobertura) + ' dias'})${r.zerados ? ` · ${n0(r.zerados)} zerados (${n0(r.zerados_sem_pedido)} sem pedido)` : ''}`} />))}
            <Stat label="Fora da curva" value={`${n0(d.sem_venda.modelos)} modelos`} sub={`com estoque (${n0(d.sem_venda.estoque)} un.) e sem venda na base`} />
          </Stats>
          <div className="row c-wide">
            <Box title="Princípio de Pareto" sub="% dos modelos (do que mais vende ao que menos vende) x % acumulado das vendas">
              <Pareto data={d.pareto} itens80={d.resumo[0].modelos} total={d.itens.length} />
            </Box>
            <Box title="O que fazer com cada curva">
              <ul className="msg-list" style={{ marginTop: 0 }}>
                <li><b style={{ color: COR.A }}>Curva A</b>: nunca pode faltar. {d.resumo[0].zerados ? <>Hoje {d.resumo[0].zerados === 1 ? 'há' : 'há'} <b>{n0(d.resumo[0].zerados)}</b> {d.resumo[0].zerados === 1 ? 'modelo A zerado' : 'modelos A zerados'}, {n0(d.resumo[0].zerados_sem_pedido)} sem pedido.</> : 'Nenhum modelo A zerado.'} Cobertura de {d.resumo[0].cobertura === null ? '—' : n0(d.resumo[0].cobertura) + ' dias'}.</li>
                <li><b>Curva B</b>: repor com prazo e grade enxuta; vale acompanhar quem está subindo para A.</li>
                <li><b>Curva C</b>: {n0(d.resumo[2].modelos)} modelos para só {n0(d.resumo[2].pct_faturamento)}% das vendas, com {n0(d.resumo[2].estoque)} un. em estoque ({d.resumo[2].cobertura === null ? '—' : n0(d.resumo[2].cobertura) + ' dias'}). Candidatos a não repor, liquidar ou marcar fora de linha.</li>
              </ul>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                {['A', 'B', 'C'].map((k) => <button key={k} className={`btn ${f.curva === k ? 'primary' : ''}`} onClick={() => setFiltro({ curva: f.curva === k ? '' : k })}>{f.curva === k ? `Mostrando só a curva ${k}` : `Ver o BI só com a curva ${k}`}</button>)}
              </div>
            </Box>
          </div>
          <Box title="Modelos na curva" sub={`${n0(lista.length)} modelos · estoque de hoje e pares a receber nos pedidos do Omie`} flush="b">
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', padding: '0 18px 12px' }}>
              <input type="search" placeholder="Buscar modelo ou descrição" value={busca} onChange={(e) => { setBusca(e.target.value); setPag(0) }} aria-label="Buscar modelo" style={{ width: 260 }} />
              <div className="pills" role="group" aria-label="Filtrar por curva" style={{ margin: 0 }}>
                {['A', 'B', 'C'].map((k) => <button key={k} className="pill" aria-pressed={classe === k} onClick={() => { setClasse(classe === k ? null : k); setPag(0) }}>
                  <i className="sw" style={{ background: COR[k], width: 9, height: 9, borderRadius: 2, display: 'inline-block' }} />Curva {k} <b className="num">{n0(d.resumo.find((r) => r.classe === k).modelos)}</b></button>)}
              </div>
            </div>
            <div className="tscroll"><table className="dt">
              <thead><tr><th className="r">#</th><th>Modelo</th><th>Curva</th><th className="r">Faturamento</th><th className="r">Unidades</th><th className="r">Part.</th><th className="r">Acumulado</th><th className="r">No período</th><th className="r">vs anterior</th><th className="r">Estoque</th><th className="r">Dura</th><th className="r">A receber</th></tr></thead>
              <tbody>{pagina.map((x) => (
                <tr key={x.modelo}>
                  <td className="r">{d.itens.indexOf(x) + 1}</td>
                  <td><button className="link" onClick={() => openProduto(x.categoria === 'calcado' ? 'modelo' : 'sku', x.modelo)}>{x.modelo}</button>{x.linha && <span className={`tag-linha ${x.linha}`}>{x.linha === 'em_linha' ? 'em linha' : 'fora de linha'}</span>}<span className="d">{x.descricao}</span></td>
                  <td><b style={{ color: COR[x.classe] }}>{x.classe}</b></td>
                  <td className="r">{money(x.faturamento)}</td><td className="r">{n0(x.unidades)}</td>
                  <td className="r">{x.participacao.toFixed(1).replace('.', ',')}%</td><td className="r">{x.acumulado.toFixed(1).replace('.', ',')}%</td>
                  <td className="r">{c.criterio === 'faturamento' ? money(x.periodo_valor) : n0(x.periodo_valor)}</td><td className="r"><Seta v={x.periodo_var} /></td>
                  <td className={'r ' + (x.estoque <= 0 ? 'z' : '')}>{n0(x.estoque)}</td>
                  <td className="r">{x.estoque <= 0 ? <b style={{ color: x.classe === 'A' ? 'var(--critical-ink)' : undefined }}>zerado</b> : x.cobertura === null ? '—' : n0(x.cobertura) + ' d'}</td>
                  <td className={'r ' + (x.a_receber > 0 ? 'in' : 'dim')}>{n0(x.a_receber)}</td>
                </tr>))}</tbody>
            </table></div>
            {lista.length > POR && (
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '12px 18px' }}>
                <button className="btn ghost" disabled={pag === 0} onClick={() => setPag(pag - 1)}>Anterior</button>
                <span style={{ fontSize: 13, color: 'var(--muted)' }}>Página {pag + 1} de {Math.ceil(lista.length / POR)}</span>
                <button className="btn ghost" disabled={(pag + 1) * POR >= lista.length} onClick={() => setPag(pag + 1)}>Próxima</button>
              </div>
            )}
          </Box>
        </>
      )
    }}</Load>
  )
}
