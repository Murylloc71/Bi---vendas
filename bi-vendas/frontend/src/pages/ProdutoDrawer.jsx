import { useEffect } from 'react'
import { VendasCanalMes } from '../charts'
import { useCtx } from '../ctx'
import { dataBR, money, money2, n0, n1 } from '../fmt'
import { Box, DataTable, Empty, Load, Stat, Stats, Status, useApi } from '../ui'
import { MarcarLinha, estadoDe, useMarcas } from '../linha'

export default function ProdutoDrawer({ alvo, onClose, anterior, onBack }) {
  const { openProduto } = useCtx()
  const st = useApi('/api/detalhe', { nivel: alvo.nivel, chave: alvo.chave })
  // Esc volta um nível (ou fecha, se não houver para onde voltar)
  useEffect(() => { const k = (e) => e.key === 'Escape' && (anterior ? onBack() : onClose()); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [onClose, onBack, anterior])
  const d = st.data
  const marcas = useMarcas()
  // a marcação de linha vale para o modelo (produtos fora do padrão: o próprio código)
  const chaveLinha = d ? (d.categoria === 'calcado' ? d.modelo : alvo.chave) : null
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={`Detalhe de ${alvo.chave}`}>
        <div className="drawer-h">
          <div>
            <h2>{alvo.chave}</h2>
            {d && <p>{d.descricao || (d.categoria === 'calcado' ? '' : 'Produto fora do padrão de modelo')}</p>}
            {chaveLinha && (
              <div style={{ margin: '8px 0 2px' }}>
                <MarcarLinha chaves={[chaveLinha]} atual={estadoDe(marcas, chaveLinha)} />
                {d.categoria === 'calcado' && alvo.nivel !== 'modelo' && <span style={{ fontSize: 12, color: 'var(--muted)', marginLeft: 8 }}>vale para o modelo {chaveLinha}</span>}
              </div>
            )}
            {d?.categoria === 'calcado' && (
              <div className="meta">
                <span>Modelo <b>{d.modelo}</b></span>
                {alvo.nivel !== 'modelo' && <span>Cabedal <b>{d.cabedal}</b></span>}
                {alvo.nivel === 'sku' && <span>Cor <b>{d.cor}</b></span>}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8, flex: 'none' }}>
            {anterior && <button className="btn" onClick={onBack} autoFocus title={`Voltar para ${anterior.chave}`}>← Voltar para {anterior.chave}</button>}
            <button className="btn ghost" onClick={onClose} autoFocus={!anterior}>Fechar</button>
          </div>
        </div>
        <div className="drawer-b">
          <Load state={st} height={500}>{(d) => {
            const deps = Object.keys(d.estoque_por_deposito)
            const ac = d.a_caminho
            return (
              <>
                <Stats>
                  <Stat label="Faturamento (histórico)" value={money(d.serie.reduce((a, s) => a + (s.faturamento || 0), 0))} sub={`${n0(d.serie.reduce((a, s) => a + (s.unidades || 0), 0))} unidades`} />
                  <Stat label="Estoque" value={n0(d.estoque)} sub={<Status s={d.status_estoque} />} />
                  <Stat label="Dura" value={d.cobertura_dias === null ? '—' : `${n0(d.cobertura_dias)} dias`} sub={`${n1(d.demanda_dia || 0)} un./dia nos últimos 3 meses`} />
                  <Stat label="A caminho" value={n0(ac?.pares || 0)} tone={ac?.pares ? 'inbound' : ''} sub={ac?.previsao ? `primeira previsão ${dataBR(ac.previsao)}` : 'sem pedido em aberto'} />
                  {d.categoria === 'calcado' && <Stat label="Compras na história" value={`${n0(d.compras_historico.notas)} notas`}
                    sub={d.compras_historico.notas ? `${n0(d.compras_historico.pares)} pares · ${dataBR(d.compras_historico.primeira)} a ${dataBR(d.compras_historico.ultima)}` : 'nenhuma compra registrada'} />}
                </Stats>
                <div style={{ display: 'grid', gap: 16 }}>
                  <Box title="Vendas por mês" sub="Por marketplace; passe o mouse sobre a barra para ver quanto vendeu em cada um">
                    <VendasCanalMes data={d.serie} />
                  </Box>
                  <Box title="Informações do produto">
                    <div className="info-grid">
                      {[
                        ['Categoria', d.info.categoria],
                        d.info.modelo && ['Modelo', d.info.modelo],
                        d.info.cabedal && ['Cabedal', d.info.cabedal],
                        d.info.cor && ['Cor', d.info.cor],
                        ['Curva ABC', d.info.curva === '–' ? 'sem venda na base' : `Curva ${d.info.curva}`],
                        ['Linha', d.info.linha],
                        alvo.nivel !== 'sku' && ['SKUs com venda', n0(d.info.skus)],
                        ['Primeira venda', d.info.primeira_venda ? d.info.primeira_venda.split('-').reverse().join('/') : '—'],
                        ['Última venda', d.info.ultima_venda ? d.info.ultima_venda.split('-').reverse().join('/') : '—'],
                        ['Meses com venda', n0(d.info.meses_com_venda)],
                        ['Preço médio de venda (3 meses)', money2(d.info.preco_venda_3m)],
                        ['Custo médio de compra (notas)', money2(d.info.custo_medio_compra)],
                        d.info.preco_venda_3m && d.info.custo_medio_compra && ['Venda ÷ custo', (d.info.preco_venda_3m / d.info.custo_medio_compra).toFixed(2).replace('.', ',') + '×'],
                        ['Fornecedor', d.info.fornecedor || '—'],
                        ['Tamanhos em estoque', d.info.tamanhos_em_estoque.length ? d.info.tamanhos_em_estoque.join(', ') : '—'],
                        ['Depósitos', Object.keys(d.estoque_por_deposito).length ? Object.entries(d.estoque_por_deposito).map(([k, v]) => `${k}: ${n0(v)}`).join(' · ') : '—'],
                      ].filter(Boolean).map(([k, v]) => <div key={k}><span>{k}</span><b>{v}</b></div>)}
                    </div>
                    {d.info.eans.length > 0 && <p className="note" style={{ marginBottom: 0 }}>EANs nas notas de compra{alvo.nivel === 'sku' ? ' do modelo' : ''}: {d.info.eans.join(', ')}</p>}
                    {d.info.codigos_estoque.length > 0 && <p className="note" style={{ marginBottom: 0 }}>Códigos no estoque: {d.info.codigos_estoque.join(', ')}</p>}
                    {d.info.excluido && <div className="alert bad" style={{ marginTop: 10 }}>Este SKU está excluído do BI (Dados › SKUs do BI).</div>}
                  </Box>
                  {d.estoque_por_tamanho.length > 0 && (
                    <Box title="Estoque por tamanho" sub="Em vermelho, tamanhos zerados; na última coluna, pares em pedidos abertos" flush="b">
                      <div className="tscroll"><table className="dt">
                        <thead><tr><th>Tamanho</th>{deps.map((x) => <th key={x} className="r">{x}</th>)}<th className="r">Total</th><th className="r">A caminho</th></tr></thead>
                        <tbody>{d.estoque_por_tamanho.map((t) => (
                          <tr key={t.tamanho}><td><b>{t.tamanho}</b></td>{deps.map((x) => <td key={x} className="r">{n0(t[x])}</td>)}
                            <td className={'r ' + (t.total <= 0 ? 'z' : '')}><b>{n0(t.total)}</b></td>
                            <td className={'r ' + (ac?.por_tamanho?.[t.tamanho] ? 'in' : 'dim')}>{ac?.por_tamanho?.[t.tamanho] ? n0(ac.por_tamanho[t.tamanho]) : '·'}</td></tr>))}</tbody>
                      </table></div>
                    </Box>
                  )}
                  {d.filhos.length > 0 && (
                    <Box title={alvo.nivel === 'modelo' ? 'SKUs do modelo' : 'SKUs do cabedal'} flush="b">
                      <DataTable rows={d.filhos.map((x) => ({ ...x, chave: x.sku }))} pageSize={10} initialSort={{ key: 'faturamento', dir: 'desc' }} columns={[
                        { key: 'sku', label: 'SKU', render: (r) => <button className="link" onClick={() => openProduto('sku', r.sku)}>{r.sku}</button> },
                        { key: 'unidades', label: 'Unidades', right: true, render: (r) => n0(r.unidades) },
                        { key: 'faturamento', label: 'Faturamento', right: true, render: (r) => money(r.faturamento) },
                        { key: 'preco_medio', label: 'Preço médio', right: true, render: (r) => money2(r.preco_medio) },
                      ]} />
                    </Box>
                  )}
                  {d.categoria === 'calcado' && (
                    <Box title={`Notas de compra do modelo ${d.modelo}`} sub="PE = pronta-entrega · PROG = programado (preço líquido com o desconto da nota)" flush="b">
                      {!d.compras.length ? <div className="box-b"><Empty>Nenhuma nota registrada para este modelo.</Empty></div> : (
                        <div className="tscroll"><table className="dt">
                          <thead><tr><th>Data</th><th>Tipo</th><th className="r">Preço unitário</th><th className="r">Preço líquido</th><th className="r">Pares</th></tr></thead>
                          <tbody>{[...d.compras].reverse().map((c, i) => (
                            <tr key={i}><td>{dataBR(c.data)}</td><td>{c.modalidade}</td><td className="r">{money2(c.preco_tabela)}</td>
                              <td className="r">{money2(c.preco_liquido)}</td><td className="r">{c.pares === null ? <span style={{ color: 'var(--muted)' }}>sem qtd.</span> : n0(c.pares)}</td></tr>))}</tbody>
                        </table></div>)}
                    </Box>
                  )}
                </div>
              </>
            )
          }}</Load>
        </div>
      </aside>
    </>
  )
}
