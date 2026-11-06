import { MonthBars, WeekBars } from '../charts'
import { useCtx } from '../ctx'
import { dataBR, money, money2, moneyCompact, n0, n1 } from '../fmt'
import Icon from '../icons'
import { Box, Delta, Empty, Load, Status, Summary, useApi } from '../ui'

export default function Overview() {
  const { f, go, openProduto, versao, irParaMes } = useCtx()
  const home = useApi('/api/home', { categoria: f.categoria }, [versao])
  const ped = useApi('/api/compras/pedidos', {}, [versao])
  const rep = useApi('/api/estoque/reposicao', { nivel: 'sku', categoria: f.categoria }, [versao])
  return (
    <Load state={home} height={520}>{(h) => {
      if (!h.tem_dados) return <Empty title="Nenhum dado ainda">Importe vendas, estoque e compras em Dados › Importar arquivos. <button className="btn primary" style={{ marginTop: 10 }} onClick={() => go('/dados/importar')}>Importar arquivos</button></Empty>
      const k = h.foco.kpis, c = k.comparacao, pc = h.parcial
      const te = h.tempo_estoque, est = h.estoque
      const cont = rep.data?.reposicao?.contagem || {}
      const r = ped.data?.resumo
      return (
        <>
          <section className="box hero" style={{ marginBottom: 16 }}>
            <div className="hero-l">
              <div>
                <h2>Faturamento de {h.foco.rotulo}</h2>
                <div className="hero-fig num" style={{ marginTop: 6 }}>{money(k.faturamento)}</div>
                <div className="hero-cap">{c ? <><Delta v={c.faturamento} /> em relação a {c.periodo[0]} ({moneyCompact(c.faturamento_ant)})</> : 'Sem mês anterior para comparar'}</div>
              </div>
              <div className="hero-kv">
                <div><b className="num">{n0(k.unidades)}</b><span>unidades {c && <Delta v={c.unidades} />}</span></div>
                <div><b className="num">{money2(k.preco_medio)}</b><span>preço médio {c && <Delta v={c.preco_medio} />}</span></div>
                <div><b className="num">{n0(k.skus_vendidos)}</b><span>SKUs com venda</span></div>
                <div><b className="num">{k.unidades ? n0((k.unidades_shopee / k.unidades) * 100) : '—'}%</b><span>das unidades pela Shopee</span></div>
              </div>
            </div>
            <div className="hero-r">
              <div style={{ fontSize: 12, color: 'var(--muted)', textAlign: 'right', marginBottom: -6 }}>Clique em um mês para abrir o resultado dele</div>
              <MonthBars data={h.serie} dataKey="faturamento" selected={h.foco.mes} height={250} onSelect={(x) => irParaMes(x.mes)}
                rows={[['Faturamento', (d) => money(d.faturamento)], ['Unidades', (d) => n0(d.unidades)], ['Preço médio', (d) => money2(d.preco_medio)]]} />
            </div>
          </section>

          {pc && (
            <div className="strip">
              <span className="lbl"><i aria-hidden="true" />{pc.rotulo} em andamento</span>
              <span><b>{pc.dias}</b> de {pc.dias_mes} dias</span>
              <span><b className="num">{money(pc.kpis.faturamento)}</b> e <b className="num">{n0(pc.kpis.unidades)}</b> unidades até agora</span>
              <span>Ritmo diário <b className="num">{money(pc.kpis.faturamento_dia)}</b> {pc.kpis.comparacao && <Delta v={pc.kpis.comparacao.faturamento} suffix={`vs ${pc.kpis.comparacao.periodo[0]}`} />}</span>
              <span title="Ritmo diário atual multiplicado pelos dias do mês">Se mantiver o ritmo: <b className="num">{moneyCompact(pc.kpis.projecao_faturamento)}</b></span>
            </div>
          )}

          <section className="box pulse" style={{ marginBottom: 16 }}>
            <section>
              <h3><Icon name="stock" />Estoque</h3>
              <div className="big num">{n0(est.total)} <span style={{ fontSize: 14, fontWeight: 400, color: 'var(--muted)' }}>unidades</span></div>
              <div className="cap">Posição de {dataBR(est.depositos?.[0]?.data)}</div>
              {est.depositos?.map((d) => <div className="kv" key={d.deposito}><span>{d.deposito}</span><b>{n0(d.unidades)}</b></div>)}
              {te.status === 'ok' && <div className="kv"><span>Cobertura no ritmo atual</span><b>{n0(te.dias)} dias</b></div>}
              <div className="go"><button className="btn ghost" onClick={() => go('/estoque/posicao')}>Ver posição</button></div>
            </section>
            <section>
              <h3><Icon name="restock" />Reposição</h3>
              <div className="big num" style={{ color: cont.ruptura_sem_pedido ? 'var(--critical-ink)' : undefined }}>{n0(cont.ruptura_sem_pedido?.itens || 0)} <span style={{ fontSize: 14, fontWeight: 400, color: 'var(--muted)' }}>zerados sem pedido</span></div>
              <div className="cap">SKUs que vendem, sem estoque e sem pedido em aberto</div>
              <div className="kv"><span>Acabando, sem pedido</span><b>{n0(cont.critico_sem_pedido?.itens || 0)}</b></div>
              <div className="kv"><span>Pedido chega depois de acabar</span><b>{n0(cont.pedido_chega_tarde?.itens || 0)}</b></div>
              <div className="kv"><span>Zerados com pedido a caminho</span><b>{n0(cont.ruptura_com_pedido?.itens || 0)}</b></div>
              <div className="go"><button className="btn ghost" onClick={() => go('/estoque/reposicao')}>Ver reposição</button></div>
            </section>
            <section>
              <h3><Icon name="orders" />Pedidos {ped.data?.fornecedor ? ped.data.fornecedor.split(' ').slice(0, 3).join(' ').replace(/^CALCADOS /, '') : ''}</h3>
              {!r || r.status !== 'ok' ? <Empty>{r?.motivo || 'Carregando pedidos…'}</Empty> : (
                <>
                  <div className="big num" style={{ color: 'var(--inbound)' }}>{n0(r.abertos.pares)} <span style={{ fontSize: 14, fontWeight: 400, color: 'var(--muted)' }}>pares a receber</span></div>
                  <div className="cap">{money(r.abertos.valor)} em {n0(r.abertos.pedidos)} pedidos</div>
                  <div className="kv"><span>Chegam nos próximos 30 dias</span><b>{n0(r.proximos_30.pares)}</b></div>
                  <div className="kv"><span>Faturado</span><b>{n0(r.previsao_vencida.pedidos)} pedidos</b></div>
                  <div className="kv"><span>Custo médio do par</span><b>{money2(r.abertos.preco_medio_par)}</b></div>
                  <div className="go"><button className="btn ghost" onClick={() => go('/compras/pedidos')}>Ver pedidos</button></div>
                </>
              )}
            </section>
          </section>

          <Box title={`Leitura de ${h.resumo.periodo}`}><Summary r={h.resumo} /></Box>
          <div style={{ height: 16 }} />

          <div className="row c-wide">
            <Box title="Modelos que mais faturaram" sub={`${h.top_periodo[0]} a ${h.top_periodo.at(-1)}`} flush="b">
              <ul className="list">
                {h.top_modelos.map((t) => (
                  <li key={t.chave}>
                    <div className="t"><button className="link" onClick={() => openProduto('modelo', t.chave)}>{t.chave}</button>
                      <span>{t.descricao} · {n0(t.unidades)} un. a {money2(t.preco_medio)}</span></div>
                    <div className="v">{money(t.faturamento)}<small><Status s={t.status_estoque} /></small></div>
                  </li>
                ))}
              </ul>
            </Box>
            <Box title="Entregas previstas" sub="Pares a receber por semana">
              {!r || r.status !== 'ok' ? <Empty>{r?.motivo || '…'}</Empty> : <WeekBars data={r.entregas.slice(0, 12)} height={260} />}
            </Box>
          </div>
        </>
      )
    }}</Load>
  )
}
