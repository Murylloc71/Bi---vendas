import { useEffect, useState } from 'react'
import { ComprasMes, MonthBars, RankingBarras, WeekBars } from '../charts'
import { useCtx } from '../ctx'
import { dataBR, dataCurta, diasAte, money, money2, n0, n1 } from '../fmt'
import { Box, DataTable, Empty, Load, Stat, Stats, Status, useApi } from '../ui'
import { TagLinha, useMarcas } from '../linha'

export function Pedidos() {
  const { f, versao, go, openPedido } = useCtx()
  const st = useApi('/api/compras/pedidos', { fornecedor: f.fornecedor ?? undefined }, [versao])
  const [filtro, setFiltro] = useState('abertos')
  return (
    <Load state={st} height={600}>{(d) => {
      const r = d.resumo
      if (r.status !== 'ok') return <Empty title="Sem pedidos do Omie">{r.motivo} <div style={{ marginTop: 10 }}><button className="btn primary" onClick={() => go('/dados/omie')}>Configurar Omie</button></div></Empty>
      const abertos = ['pendente', 'faturado_parcial', 'faturado', 'recebido_parcial']
      const rows = d.pedidos.filter((p) => filtro === 'todos' || (filtro === 'abertos' ? abertos.includes(p.status) : filtro === 'vencidos' ? (p.previsao_vencida || p.status === 'faturado') : p.status === filtro))
      const sync = d.sync?.ultima_sync
      return (
        <>
          <Stats>
            <Stat label="Pares a receber" value={n0(r.abertos.pares)} tone="inbound" sub={`${n0(r.abertos.pedidos)} pedidos em aberto`} />
            <Stat label="Valor em aberto" value={money(r.abertos.valor)} sub={`custo médio ${money2(r.abertos.preco_medio_par)} o par`} />
            <Stat label="Próximos 30 dias" value={n0(r.proximos_30.pares)} sub={`pares em ${n0(r.proximos_30.pedidos)} pedidos · ${money(r.proximos_30.valor)}`} />
            <Stat label="Faturado" value={n0(r.previsao_vencida.pedidos)} tone="inbound" sub={`pedidos · ${n0(r.previsao_vencida.pares)} pares ainda não recebidos`} />
            <Stat label="Variedade a caminho" value={n0(r.abertos.modelos)} sub={`modelos · ${n0(r.abertos.skus)} SKUs`} />
          </Stats>
          <div className="row c-wide">
            <Box title="Entregas previstas por semana" sub="Pares a receber, pela data de previsão do pedido">
              <WeekBars data={r.entregas} height={240} />
            </Box>
            <Box title="Vencimentos das parcelas" sub="Por mês, conforme as condições dos pedidos">
              {r.vencimentos.length ? <MonthBars data={r.vencimentos.map((v) => ({ ...v, mes: v.mes }))} dataKey="valor" color="var(--inbound)" height={240}
                rows={[['A pagar', (x) => money(x.valor)]]} /> : <Empty>Sem parcelas futuras.</Empty>}
            </Box>
          </div>
          <BuscaSku fornecedor={f.fornecedor ?? undefined} versao={versao} />
          <Box title="Pedidos de compra" sub={sync ? `Omie sincronizado em ${new Date(sync.quando + 'Z').toLocaleString('pt-BR')}` : 'Dados do Omie'} flush="b"
            right={<button className="btn ghost" onClick={() => go('/dados/omie')}>Sincronização</button>}>
            <div className="pills" role="group" aria-label="Filtrar pedidos">
              {[['abertos', 'Em aberto'], ['vencidos', 'Faturado'], ['pendente', 'Pendentes'], ['recebido', 'Recebidos'], ['todos', 'Todos']].map(([k, t]) => (
                <button key={k} className="pill" aria-pressed={filtro === k} onClick={() => setFiltro(k)}>{t}</button>))}
            </div>
            <DataTable rows={rows} rowKey={(p) => p.id} searchKeys={['numero', 'numero_fornecedor']} initialSort={{ key: 'previsao', dir: 'asc' }} pageSize={20} columns={[
              { key: 'numero', label: 'Pedido', sortValue: (p) => Number(p.numero) || 0, render: (p) => <><button className="link" onClick={() => openPedido(p.id)}>Nº {p.numero}</button><span className="d">Fornecedor: {p.numero_fornecedor || '—'}</span></> },
              { key: 'status', label: 'Situação', render: (p) => <Status s={p.previsao_vencida ? 'faturado' : p.status} label={p.previsao_vencida ? 'Faturado' : p.status_rotulo} /> },
              { key: 'data_inclusao', label: 'Incluído', render: (p) => dataBR(p.data_inclusao) },
              { key: 'previsao', label: 'Previsão', render: (p) => { const da = diasAte(p.previsao); return <>{dataBR(p.previsao)}{p.status !== 'recebido' && da !== null && <span className="d">{da < 0 ? `${-da} dias atrás` : da === 0 ? 'hoje' : `em ${da} dias`}</span>}</> } },
              { key: 'modelos', label: 'Modelos', right: true, render: (p) => n0(p.modelos) },
              { key: 'pares', label: 'Pares', right: true, render: (p) => n0(p.pares) },
              { key: 'a_receber', label: 'A receber', right: true, cls: (p) => (p.a_receber > 0 ? 'in' : 'dim'), render: (p) => n0(p.a_receber) },
              { key: 'valor_total', label: 'Valor', right: true, render: (p) => money(p.valor_total) },
            ]} />
            <p className="note" style={{ padding: '0 18px' }}>{r.nota}</p>
          </Box>
        </>
      )
    }}</Load>
  )
}

/** Busca por SKU: em quais pedidos de compra do Omie o produto aparece. */
function BuscaSku({ fornecedor, versao }) {
  const { openPedido, openProduto } = useCtx()
  const [q, setQ] = useState('')
  const [termo, setTermo] = useState('')
  useEffect(() => { const t = setTimeout(() => setTermo(q.trim()), 350); return () => clearTimeout(t) }, [q])
  const st = useApi(termo.length >= 2 ? '/api/compras/pedidos-por-sku' : null, { q: termo, fornecedor }, [versao])
  const d = st.data
  return (
    <div style={{ marginBottom: 16 }}>
      <Box title="Buscar SKU nos pedidos" sub="Digite o SKU inteiro ou um trecho (ex.: o código do modelo) para ver em quais pedidos ele foi comprado. Respeita o fornecedor escolhido no topo." flush={termo.length >= 2 ? 'b' : undefined}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', padding: termo.length >= 2 ? '0 18px 12px' : 0 }}>
          <input type="search" placeholder="SKU ou trecho, ex.: 8367.875" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar SKU nos pedidos" style={{ width: 320, maxWidth: '100%' }} />
          {termo.length >= 2 && d && d.total > 0 && <span style={{ color: 'var(--muted)', fontSize: 13 }}>{n0(d.skus)} {d.skus === 1 ? 'SKU' : 'SKUs'} em {n0(d.pedidos)} {d.pedidos === 1 ? 'pedido' : 'pedidos'} · {n0(d.a_receber)} pares a receber</span>}
          {q && <button className="btn ghost" onClick={() => { setQ(''); setTermo('') }}>Limpar</button>}
        </div>
        {termo.length >= 2 && (
          st.loading && !d ? <div className="skel" style={{ height: 120, margin: '0 18px 18px' }} />
            : st.error ? <div className="err" style={{ margin: '0 18px 18px' }}>{st.error.message}</div>
              : !d || d.total === 0 ? <div style={{ padding: '0 18px 18px' }}><Empty>Nenhum pedido com SKU contendo “{termo}”.</Empty></div>
                : (
                  <DataTable rows={d.itens} rowKey={(x) => x.pedido_id + x.sku} initialSort={{ key: 'previsao', dir: 'desc' }} pageSize={15} columns={[
                    { key: 'sku', label: 'SKU', render: (x) => <><button className="link" onClick={() => openProduto('sku', x.sku)}>{x.sku}</button><span className="d">{x.descricao}</span></> },
                    { key: 'numero', label: 'Pedido', sortValue: (x) => Number(x.numero) || 0, render: (x) => <><button className="link" onClick={() => openPedido(x.pedido_id)}>Nº {x.numero}</button><span className="d">Fornecedor: {x.numero_fornecedor || '—'}</span></> },
                    { key: 'status', label: 'Situação', render: (x) => <Status s={x.previsao_vencida ? 'faturado' : x.status} label={x.previsao_vencida ? 'Faturado' : x.status_rotulo} /> },
                    { key: 'previsao', label: 'Previsão', render: (x) => dataBR(x.previsao) },
                    { key: 'grade', label: 'Grade', render: (x) => <span style={{ fontSize: 12.5, color: 'var(--ink-2)', display: 'inline-block', minWidth: 210, lineHeight: 1.5 }}>{x.grade ? x.grade.split(', ').map((g) => <span key={g} style={{ whiteSpace: 'nowrap', marginRight: 10 }}>{g}</span>) : '—'}</span> },
                    { key: 'pares', label: 'Pares', right: true, render: (x) => n0(x.pares) },
                    { key: 'a_receber', label: 'A receber', right: true, cls: (x) => (x.a_receber > 0 ? 'in' : 'dim'), render: (x) => n0(x.a_receber) },
                    { key: 'valor_unitario', label: 'Preço', right: true, render: (x) => money2(x.valor_unitario) },
                    { key: 'valor_total', label: 'Total', right: true, render: (x) => money(x.valor_total) },
                  ]} />
                )
        )}
      </Box>
    </div>
  )
}

export function PedidoDrawer({ id, onClose }) {
  const { openProduto } = useCtx()
  const st = useApi(`/api/compras/pedidos/${id}`)
  useEffect(() => { const k = (e) => e.key === 'Escape' && onClose(); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [onClose])
  const d = st.data
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Pedido de compra">
        <div className="drawer-h">
          <div>
            <h2>Pedido {d ? `nº ${d.numero}` : ''}</h2>
            {d && <div className="meta"><span>{d.fornecedor}</span><span>Nº no fornecedor <b>{d.numero_fornecedor || '—'}</b></span><Status s={d.status} label={d.status_rotulo} /></div>}
          </div>
          <button className="btn" onClick={onClose} autoFocus>Fechar</button>
        </div>
        <div className="drawer-b">
          <Load state={st} height={400}>{(p) => (
            <>
              <Stats>
                <Stat label="Pares" value={n0(p.pares)} />
                <Stat label="Valor" value={money(p.valor_total)} sub={p.frete ? `frete ${money(p.frete)}` : null} />
                <Stat label="Incluído" value={<span style={{ fontSize: 18 }}>{dataBR(p.data_inclusao)}</span>} />
                <Stat label="Previsão" value={<span style={{ fontSize: 18 }}>{dataBR(p.previsao)}</span>} />
              </Stats>
              {p.observacao && <p className="lead" style={{ fontSize: 13.5 }}>{p.observacao}</p>}
              <Box title="Grade do pedido" sub="Pares por tamanho" flush="b">
                <div className="tscroll"><table className="dt">
                  <thead><tr><th>SKU</th>{p.tamanhos.map((t) => <th key={t} className="r">{t}</th>)}<th className="r">Pares</th><th className="r">Preço</th><th className="r">Total</th></tr></thead>
                  <tbody>{p.grade.map((g) => (
                    <tr key={g.sku}><td><button className="link" onClick={() => openProduto('sku', g.sku)}>{g.sku}</button><span className="d">{g.descricao}</span></td>
                      {p.tamanhos.map((t) => <td key={t} className={'r ' + (g.tamanhos[t] ? '' : 'dim')}>{g.tamanhos[t] ? n0(g.tamanhos[t]) : '·'}</td>)}
                      <td className="r"><b>{n0(g.pares)}</b></td><td className="r">{money2(g.valor_unitario)}</td><td className="r">{money(g.valor_total)}</td></tr>))}</tbody>
                </table></div>
              </Box>
              {p.parcelas.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <Box title="Parcelas" flush="b">
                    <ul className="list">{p.parcelas.map((x) => (
                      <li key={x.parcela}><div className="t"><b>{x.parcela}ª parcela</b><span>vence {dataBR(x.vencimento)} ({x.dias} dias)</span></div><div className="v">{money2(x.valor)}</div></li>))}</ul>
                  </Box>
                </div>
              )}
            </>
          )}</Load>
        </div>
      </aside>
    </>
  )
}

export function ProntaEntrega() {
  const { f, per, versao, openProduto } = useCtx()
  const st = useApi('/api/compras/pronta-entrega', { inicio: per[0], fim: per[1], categoria: f.categoria === 'outro' ? 'calcado' : f.categoria }, [versao])
  return (
    <Load state={st} height={500}>{(d) => {
      const e = d.economia_pe
      if (e.status !== 'ok' || !e.pares_pe) return <Empty title="Sem economia calculável no período">{e.motivo || 'Sem compras pronta-entrega com quantidade.'}</Empty>
      return (
        <>
          <p className="lead">Compara cada compra pronta-entrega com o preço líquido do programado do mesmo modelo, na compra programada mais próxima no tempo. Base: notas de entrada importadas ({d.periodo.rotulo}).</p>
          <Stats>
            <Stat label="Economia" value={money(e.economia)} sub={`${n1(e.economia_pct)}% abaixo do programado`} />
            <Stat label="Pago no pronta-entrega" value={money(e.valor_pago_calculado)} sub={`${n0(e.pares_calculados)} pares com cálculo`} />
            <Stat label="Custaria no programado" value={money(e.valor_programado_equivalente)} />
            <Stat label="Fora do cálculo" value={n0(e.pares_sem_referencia)} sub={`pares sem referência · ${n0(e.notas_sem_quantidade)} notas sem quantidade`} />
          </Stats>
          <div className="row c-narrow">
            <Box title="Economia por mês">
              {e.por_mes.length ? <MonthBars data={e.por_mes} dataKey="economia" height={240} rows={[['Economia', (x) => money(x.economia)], ['Pares', (x) => n0(x.pares)]]} /> : <Empty>Sem dados.</Empty>}
            </Box>
            <Box title="Por modelo" flush="b">
              <DataTable rows={e.por_modelo.map((m) => ({ ...m, chave: m.modelo }))} pageSize={10} initialSort={{ key: 'economia', dir: 'desc' }} columns={[
                { key: 'modelo', label: 'Modelo', render: (m) => <button className="link" onClick={() => openProduto('modelo', m.modelo)}>{m.modelo}</button> },
                { key: 'pares', label: 'Pares', right: true, render: (m) => n0(m.pares) },
                { key: 'preco_pe', label: 'Pago (PE)', right: true, render: (m) => money2(m.preco_pe) },
                { key: 'preco_ref', label: 'Programado', right: true, render: (m) => money2(m.preco_ref) },
                { key: 'economia', label: 'Economia', right: true, render: (m) => <b>{money(m.economia)}</b> },
              ]} />
            </Box>
          </div>
          {e.modelos_sem_referencia?.length > 0 && <p className="note">Modelos comprados em pronta-entrega sem nenhuma compra programada para comparar: {e.modelos_sem_referencia.join(', ')}.</p>}
          <p className="note">{e.nota}</p>
        </>
      )
    }}</Load>
  )
}

/** Modelos mais comprados nos relatórios de compras, com venda, estoque e o que ainda vai chegar. */
export function MaisComprados() {
  const { per, versao, openProduto, go } = useCtx()
  const st = useApi('/api/compras/mais-comprados', { inicio: per[0], fim: per[1] }, [versao])
  const marcas = useMarcas()
  return (
    <Load state={st} height={600}>{(d) => {
      if (d.status !== 'ok') return <Box title="Mais comprados"><Empty>{d.motivo} <button className="link" onClick={() => go('/dados/importar')}>Importar relatório de compras</button></Empty></Box>
      const t = d.totais
      const top = d.itens.filter((x) => x.pares > 0).slice(0, 15)
      return (
        <>
          <Stats>
            <Stat label="Pares comprados" value={n0(t.pares)} sub={`${n0(t.modelos)} modelos em ${n0(t.notas)} notas`} />
            <Stat label="Valor comprado" value={money(t.valor)} sub={`preço médio ${money2(t.preco_medio)} o par`} />
            <Stat label="Pronta-entrega" value={t.pe_pct === null ? '—' : n0(t.pe_pct) + '%'} sub="dos pares comprados" />
            <Stat label="Mais comprado" value={d.itens[0]?.modelo || '—'} sub={d.itens[0] ? `${n0(d.itens[0].pares)} pares · ${n0(d.itens[0].historico_compras)} compras na história` : ''} />
            {t.linhas_sem_quantidade > 0 && <Stat label="Linhas sem quantidade" value={n0(t.linhas_sem_quantidade)} sub={`de ${n0(t.linhas)}; não entram nos pares`} />}
          </Stats>
          <div className="row c-wide">
            <Box title="Top 15 modelos mais comprados" sub={`${d.periodo.rotulo} · em pares. Clique para abrir o modelo.`}>
              {top.length ? <RankingBarras data={top} dataKey="pares" rotulo="modelo" onSelect={(x) => openProduto('modelo', x.modelo)}
                titulo={(x) => `${x.modelo} · ${(x.descricao || '').slice(0, 50)}`} /> : <Empty>Sem quantidades no período.</Empty>}
            </Box>
            <Box title="Compras por mês" sub="Pares de programado e de pronta-entrega">
              {d.serie.length ? <ComprasMes data={d.serie} /> : <Empty>Sem quantidades no período.</Empty>}
            </Box>
          </div>
          <Box title="Todos os modelos comprados" sub={`Ordenado por pares comprados no período. “Na história” conta todas as compras importadas (${dataBR(d.historico.de)} a ${dataBR(d.historico.ate)}). Vendidos = vendas do período; estoque é o de hoje; a receber vem dos pedidos em aberto do Omie.`} flush="b">
            <DataTable rows={d.itens} rowKey={(x) => x.modelo} searchKeys={['modelo', 'descricao']} initialSort={{ key: 'pares', dir: 'desc' }} pageSize={25} columns={[
              { key: 'posicao', label: '#', right: true, render: (x) => x.posicao },
              { key: 'modelo', label: 'Modelo', sortValue: (x) => x.modelo, render: (x) => <><button className="link" onClick={() => openProduto('modelo', x.modelo)}>{x.modelo}</button><TagLinha marcas={marcas} chave={x.modelo} /><span className="d">{x.todos_cabedais ? 'todos os cabedais · ' : ''}{x.descricao}</span></> },
              { key: 'pares', label: 'Pares', right: true, render: (x) => <>{n0(x.pares)}{x.linhas_sem_quantidade > 0 && <span className="d">+{n0(x.linhas_sem_quantidade)} linhas sem qtd.</span>}</> },
              { key: 'valor', label: 'Valor', right: true, render: (x) => money(x.valor) },
              { key: 'preco_medio', label: 'Preço médio', right: true, render: (x) => <>{money2(x.preco_medio)}{x.preco_min !== x.preco_max && <span className="d">{money2(x.preco_min)}–{money2(x.preco_max)}</span>}</> },
              { key: 'pe_pct', label: 'PE', right: true, render: (x) => (x.pe_pct === null ? '—' : n0(x.pe_pct) + '%') },
              { key: 'notas', label: 'Notas', right: true, render: (x) => n0(x.notas) },
              { key: 'ultima_compra', label: 'Última compra', render: (x) => dataBR(x.ultima_compra) },
              { key: 'historico_compras', label: 'Na história', right: true, render: (x) => <>{n0(x.historico_compras)} {x.historico_compras === 1 ? 'compra' : 'compras'}<span className="d">{n0(x.historico_pares)} pares · {n0(x.historico_meses)} {x.historico_meses === 1 ? 'mês' : 'meses'}</span></> },
              { key: 'vendidos', label: 'Vendidos', right: true, render: (x) => <>{n0(x.vendidos)}{x.vendido_pct !== null && <span className="d">{n0(x.vendido_pct)}% do comprado</span>}</> },
              { key: 'estoque', label: 'Estoque', right: true, cls: (x) => (x.estoque <= 0 ? 'z' : ''), render: (x) => n0(x.estoque) },
              { key: 'a_receber', label: 'A receber', right: true, cls: (x) => (x.a_receber > 0 ? 'in' : 'dim'), render: (x) => n0(x.a_receber) },
            ]} />
          </Box>
          <p className="note">{d.nota}</p>
        </>
      )
    }}</Load>
  )
}
