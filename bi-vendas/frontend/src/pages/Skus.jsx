import { useState } from 'react'
import { api } from '../api'
import { useCtx } from '../ctx'
import { money, n0 } from '../fmt'
import { Box, Empty, Load, useApi } from '../ui'

/** Todos os SKUs lidos pelo BI; os excluídos somem de vendas, estoque, compras e pedidos. */
export default function Skus() {
  const { versao, bump, openProduto } = useCtx()
  const st = useApi('/api/skus-bi', null, [versao])
  const [busca, setBusca] = useState('')
  const [vista, setVista] = useState('incluidos')
  const [cat, setCat] = useState('todos')
  const [fonte, setFonte] = useState('')
  const [sel, setSel] = useState(new Set())
  const [pag, setPag] = useState(0)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const aplicar = async (skus, excluir) => {
    if (!skus.length) return
    if (excluir && skus.length > 50 && !window.confirm(`Excluir ${skus.length} SKUs do BI? Dá para incluir de volta depois.`)) return
    setBusy(true); setMsg(null)
    try {
      await api.put('/api/skus-bi/excluidos', { skus, excluir })
      setSel(new Set()); bump()
      setMsg({ t: `${n0(skus.length)} SKU${skus.length > 1 ? 's' : ''} ${excluir ? 'excluído' : 'incluído'}${skus.length > 1 ? 's' : ''}. Os indicadores já foram recalculados.` })
    } catch (e) { setMsg({ bad: true, t: e.message }) } finally { setBusy(false) }
  }
  return (
    <Load state={st} height={500}>{(d) => {
      const t = busca.trim().toLowerCase()
      const lista = d.itens.filter((x) => (vista === 'excluidos' ? x.excluido : !x.excluido)
        && (cat === 'todos' || x.categoria === cat) && (!fonte || x.fontes.includes(fonte))
        && (!t || x.sku.toLowerCase().includes(t) || (x.descricao || '').toLowerCase().includes(t)))
      const POR = 50
      const pagina = lista.slice(pag * POR, pag * POR + POR)
      const todosPag = pagina.length > 0 && pagina.every((x) => sel.has(x.sku))
      const alterna = (sku) => { const n = new Set(sel); n.has(sku) ? n.delete(sku) : n.add(sku); setSel(n) }
      const marcarPag = () => { const n = new Set(sel); pagina.forEach((x) => (todosPag ? n.delete(x.sku) : n.add(x.sku))); setSel(n) }
      const selLista = [...sel]
      const excluir = vista !== 'excluidos'
      return (
        <>
          <p className="lead">Todos os SKUs que o BI está lendo das planilhas e APIs ({n0(d.total - d.excluidos)} considerados, {n0(d.excluidos)} excluídos). Exclua os que não quer ver: eles somem de vendas, estoque, compras, pedidos, curva ABC e relatórios. Nada é apagado; dá para incluir de volta.</p>
          {msg && <div className={`alert ${msg.bad ? 'bad' : 'ok'}`} role="status">{msg.t}</div>}
          <Box flush="b" title={vista === 'excluidos' ? 'SKUs excluídos' : 'SKUs considerados'}
            right={<span className="seg" role="group" aria-label="Ver">
              <button aria-pressed={vista === 'incluidos'} onClick={() => { setVista('incluidos'); setSel(new Set()); setPag(0) }}>Considerados</button>
              <button aria-pressed={vista === 'excluidos'} onClick={() => { setVista('excluidos'); setSel(new Set()); setPag(0) }}>Excluídos ({n0(d.excluidos)})</button>
            </span>}>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', padding: '0 18px 12px' }}>
              <input type="search" placeholder="Buscar SKU ou descrição" value={busca} onChange={(e) => { setBusca(e.target.value); setPag(0) }} aria-label="Buscar SKU" style={{ width: 260 }} />
              <select value={cat} onChange={(e) => { setCat(e.target.value); setPag(0) }} aria-label="Categoria">
                <option value="todos">Todas as categorias</option><option value="calcado">Calçados</option><option value="outro">Outros produtos</option>
              </select>
              {vista !== 'excluidos' && <select value={fonte} onChange={(e) => { setFonte(e.target.value); setPag(0) }} aria-label="Fonte">
                <option value="">Qualquer fonte</option><option value="vendas">Aparece nas vendas</option><option value="estoque">Aparece no estoque</option>
                <option value="compras">Aparece nas compras</option><option value="listas do dia">Aparece nas planilhas semanais/diárias</option>
              </select>}
              <span style={{ color: 'var(--muted)', fontSize: 13 }}>{n0(lista.length)} SKUs</span>
              <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 8, flexWrap: 'wrap' }}>
                <button className={`btn ${excluir ? 'danger' : 'primary'}`} disabled={busy || !selLista.length} onClick={() => aplicar(selLista, excluir)}>
                  {excluir ? 'Excluir' : 'Incluir de volta'} selecionados ({n0(selLista.length)})</button>
                {lista.length > 0 && lista.length <= 2000 && (t || cat !== 'todos' || fonte) && (
                  <button className="btn ghost" disabled={busy} onClick={() => aplicar(lista.map((x) => x.sku), excluir)}>{excluir ? 'Excluir' : 'Incluir'} os {n0(lista.length)} listados</button>)}
              </span>
            </div>
            {!lista.length ? <div style={{ padding: '0 18px 18px' }}><Empty>Nenhum SKU {vista === 'excluidos' ? 'excluído' : 'encontrado'}.</Empty></div> : (
              <div className="tscroll"><table className="dt">
                <thead><tr><th style={{ width: 34 }}><input type="checkbox" checked={todosPag} onChange={marcarPag} aria-label="Selecionar a página" /></th>
                  <th>SKU</th><th>Fontes</th><th className="r">Vendeu (3 meses)</th><th className="r">Faturamento (3 meses)</th><th className="r">Total vendido</th><th>Última venda</th><th className="r">Estoque</th></tr></thead>
                <tbody>{pagina.map((x) => (
                  <tr key={x.sku} onClick={(e) => e.target.tagName !== 'BUTTON' && e.target.tagName !== 'INPUT' && alterna(x.sku)} style={{ cursor: 'pointer', background: sel.has(x.sku) ? 'var(--primary-soft, #e8efff)' : undefined }}>
                    <td><input type="checkbox" checked={sel.has(x.sku)} onChange={() => alterna(x.sku)} aria-label={`Selecionar ${x.sku}`} /></td>
                    <td>{x.excluido ? <b>{x.sku}</b> : <button className="link" onClick={() => openProduto(x.categoria === 'calcado' ? 'sku' : 'sku', x.sku)}>{x.sku}</button>}<span className="d">{x.descricao}</span></td>
                    <td style={{ fontSize: 12, color: 'var(--ink-2)' }}>{x.excluido ? `excluído em ${(x.excluido_em || '').split(' ')[0].split('-').reverse().join('/')}` : x.fontes.join(', ')}</td>
                    <td className="r">{n0(x.vendas_3m)}</td><td className="r">{money(x.faturamento_3m)}</td><td className="r">{n0(x.vendas_total)}</td>
                    <td>{x.ultima_venda ? x.ultima_venda.split('-').reverse().join('/') : '—'}</td><td className="r">{n0(x.estoque)}</td>
                  </tr>))}</tbody>
              </table></div>)}
            {lista.length > POR && (
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '12px 18px' }}>
                <button className="btn ghost" disabled={pag === 0} onClick={() => setPag(pag - 1)}>Anterior</button>
                <span style={{ fontSize: 13, color: 'var(--muted)' }}>Página {pag + 1} de {Math.ceil(lista.length / POR)}</span>
                <button className="btn ghost" disabled={(pag + 1) * POR >= lista.length} onClick={() => setPag(pag + 1)}>Próxima</button>
              </div>)}
          </Box>
        </>
      )
    }}</Load>
  )
}
