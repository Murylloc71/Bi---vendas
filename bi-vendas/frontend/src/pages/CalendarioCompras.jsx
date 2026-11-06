import { useState } from 'react'
import { MarcasMes, corMarca } from '../charts'
import { useCtx } from '../ctx'
import { dataBR, n0 } from '../fmt'
import { Box, Empty, Load, Stat, Stats, useApi } from '../ui'

const ler = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v) } catch { return d } }
const gravar = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* sem armazenamento */ } }
const STATUS = { novo: 'Novo no período', sem_recompra: 'Sem recompra', recorrente: 'Recorrente' }
const COR_STATUS = { novo: 'var(--s1)', sem_recompra: 'var(--critical-ink)', recorrente: 'var(--good-ink)' }

/** Qual modelo da Beira Rio foi comprado em cada mês (sem preço). */
export default function CalendarioCompras() {
  const { versao, openProduto, go } = useCtx()
  const [ini, setIni] = useState('')
  const [fim, setFim] = useState('')
  const [agrupar, setAgrupar] = useState(() => ler('bi.marcas.agrupar', false))
  const [marca, setMarca] = useState('')
  const [status, setStatus] = useState('')
  const [busca, setBusca] = useState('')
  const [pag, setPag] = useState(0)
  const st = useApi('/api/compras/calendario', { inicio: ini || undefined, fim: fim || undefined, agrupar: agrupar ? 'true' : 'false' }, [versao])
  return (
    <Load state={st} height={600}>{(d) => {
      if (d.status !== 'ok') return <Box title="Calendário de compras"><Empty>{d.motivo} <button className="link" onClick={() => go('/dados/importar')}>Importar</button></Empty></Box>
      const t = d.totais
      const mesBR = (m) => m.split('-').reverse().join('/')
      const tq = busca.trim().toLowerCase()
      const lista = d.itens.filter((x) => (!marca || x.marca === marca) && (!status || x.status === status)
        && (!tq || x.modelo.toLowerCase().includes(tq) || (x.descricao || '').toLowerCase().includes(tq)))
      const POR = 40
      const pagina = lista.slice(pag * POR, pag * POR + POR)
      const maxCel = Math.max(1, ...d.itens.flatMap((x) => Object.values(x.meses)))
      const serie = d.resumo.map((r) => ({ ...r, ...Object.fromEntries(Object.entries(r.modelos_por_marca).map(([k, v]) => ['v_' + k, v])) }))
      const marcasSerie = d.marcas.filter((m) => d.resumo.some((r) => r.modelos_por_marca[m]))
      return (
        <>
          <p className="lead">Quais modelos foram comprados em cada mês, pelas notas da Beira Rio. Cada número é <b>em quantas notas</b> o modelo apareceu no mês (o relatório não traz quantidade nem precisa de preço).</p>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginBottom: 14 }}>
            <label className="ctl">De <select value={ini || d.meses[0]} onChange={(e) => { setIni(e.target.value); setPag(0) }} aria-label="Mês inicial">{d.meses_disponiveis.map((m) => <option key={m} value={m}>{mesBR(m)}</option>)}</select></label>
            <label className="ctl">até <select value={fim || d.meses[d.meses.length - 1]} onChange={(e) => { setFim(e.target.value); setPag(0) }} aria-label="Mês final">{d.meses_disponiveis.map((m) => <option key={m} value={m}>{mesBR(m)}</option>)}</select></label>
            <label className="check" style={{ display: 'inline-flex', gap: 8, alignItems: 'center', fontSize: 14 }}>
              <input type="checkbox" checked={agrupar} onChange={(e) => { setAgrupar(e.target.checked); gravar('bi.marcas.agrupar', e.target.checked); setMarca('') }} /> Agrupar Molekinho + Molekinha
            </label>
          </div>
          <Stats>
            <Stat label="Notas" value={n0(t.notas)} sub={`${n0(t.itens)} itens nas notas`} />
            <Stat label="Modelos comprados" value={n0(t.modelos)} sub={`${n0(t.skus)} SKUs`} />
            <Stat label="Modelos novos" value={n0(t.novos)} tone="inbound" sub={`primeira compra no período (dados desde ${mesBR(d.desde)})`} />
            <Stat label="Sem recompra" value={n0(t.sem_recompra)} tone={t.sem_recompra ? 'alarm' : ''} sub="vendem e não são comprados há mais de 60 dias" />
          </Stats>
          <div className="row c-wide">
            <Box title="Modelos comprados por mês" sub="Por marca">
              <MarcasMes data={serie} marcas={marcasSerie} prefixo="v_" unidade="modelos" />
            </Box>
            <Box title="Mês a mês">
              <div className="tscroll"><table className="dt">
                <thead><tr><th>Mês</th><th className="r">Notas</th><th className="r">Modelos</th><th className="r">Novos</th></tr></thead>
                <tbody>{d.resumo.map((r) => (
                  <tr key={r.mes}><td><b>{r.rotulo}</b></td><td className="r">{n0(r.notas)}</td><td className="r">{n0(r.modelos)}</td>
                    <td className="r">{r.modelos_novos === null ? <span style={{ color: 'var(--muted)' }} title="primeiro mês com dados">—</span> : n0(r.modelos_novos)}</td></tr>))}</tbody>
              </table></div>
            </Box>
          </div>
          <Box title="Modelo a modelo" sub="Os quadrinhos mostram em quantas notas o modelo veio em cada mês. Clique no modelo para abrir a ficha." flush="b">
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', padding: '0 18px 12px' }}>
              <input type="search" placeholder="Buscar modelo ou descrição" value={busca} onChange={(e) => { setBusca(e.target.value); setPag(0) }} aria-label="Buscar modelo" style={{ width: 240 }} />
              <select value={marca} onChange={(e) => { setMarca(e.target.value); setPag(0) }} aria-label="Marca">
                <option value="">Todas as marcas</option>{d.marcas.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
              <span className="seg" role="group" aria-label="Situação">
                <button aria-pressed={!status} onClick={() => { setStatus(''); setPag(0) }}>Todos</button>
                {Object.entries(STATUS).map(([k, v]) => <button key={k} aria-pressed={status === k} onClick={() => { setStatus(k); setPag(0) }}>{v}</button>)}
              </span>
              <span style={{ color: 'var(--muted)', fontSize: 13 }}>{n0(lista.length)} modelos</span>
            </div>
            <div className="tscroll"><table className="dt cal">
              <thead><tr><th>Modelo</th>{d.meses.map((m) => <th key={m} className="c">{d.rotulos[m]}</th>)}<th>Última compra</th><th className="r">Vendeu (3m)</th><th className="r">Estoque</th><th className="r">A receber</th></tr></thead>
              <tbody>{pagina.map((x) => (
                <tr key={x.modelo}>
                  <td style={{ minWidth: 220 }}>
                    {x.modelo === 'EAN não identificado' ? <b>{x.modelo}</b> : <button className="link" onClick={() => openProduto('modelo', x.modelo)}>{x.modelo}</button>}
                    <span className="d"><i className="sw" style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: corMarca(x.marca), marginRight: 5 }} />{x.marca}
                      {' · '}<span style={{ color: COR_STATUS[x.status], fontWeight: 600 }}>{STATUS[x.status]}</span>{x.descricao ? ' · ' + x.descricao.slice(0, 40) : ''}</span></td>
                  {d.meses.map((m) => { const v = x.meses[m] || 0; return (
                    <td key={m} className="c"><span className={`cel${v ? ' on' : ''}`} style={v ? { opacity: 0.35 + 0.65 * Math.min(1, v / maxCel) } : undefined} title={v ? `${v} nota${v > 1 ? 's' : ''} em ${d.rotulos[m]}` : `sem compra em ${d.rotulos[m]}`}>{v || ''}</span></td>) })}
                  <td>{dataBR(x.ultima_compra)}<span className="d">{x.dias_desde_ultima === null ? '' : `há ${n0(x.dias_desde_ultima)} dias`}</span></td>
                  <td className="r">{n0(x.vendas_3m)}</td><td className={'r ' + (x.estoque <= 0 ? 'z' : '')}>{n0(x.estoque)}</td>
                  <td className={'r ' + (x.a_receber > 0 ? 'in' : 'dim')}>{n0(x.a_receber)}</td>
                </tr>))}</tbody>
            </table></div>
            {lista.length > POR && (
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '12px 18px' }}>
                <button className="btn ghost" disabled={pag === 0} onClick={() => setPag(pag - 1)}>Anterior</button>
                <span style={{ fontSize: 13, color: 'var(--muted)' }}>Página {pag + 1} de {Math.ceil(lista.length / POR)}</span>
                <button className="btn ghost" disabled={(pag + 1) * POR >= lista.length} onClick={() => setPag(pag + 1)}>Próxima</button>
              </div>)}
          </Box>
          {d.sem_sku.itens > 0 && <p className="note">{n0(d.sem_sku.itens)} itens com EAN ainda sem SKU conhecido aparecem como “EAN não identificado” (ex.: {d.sem_sku.eans.slice(0, 6).join(', ')}). São reconhecidos sozinhos quando o EAN aparecer numa planilha de compras completa, no Qive ou num pedido do Omie.</p>}
          <p className="note">{d.nota}</p>
        </>
      )
    }}</Load>
  )
}
