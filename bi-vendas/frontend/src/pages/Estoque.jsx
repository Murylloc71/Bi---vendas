import { useState } from 'react'
import { MonthLine, StackBar } from '../charts'
import { urlApi } from '../api'
import Icon from '../icons'
import { useCtx } from '../ctx'
import { STATUS_REPO, dataBR, dataCurta, diasAte, money, n0, n1, pct } from '../fmt'
import { Box, DataTable, Empty, Load, Stat, Stats, Status, useApi } from '../ui'

const NIVEL = { modelo: 'Modelo', cabedal: 'Cabedal', sku: 'SKU' }
const COR = { critico: 'var(--serious)', ok: 'var(--good)', excesso: 'var(--warning)', sem_giro: 'var(--s-prev)' }

export function Posicao() {
  const { f, versao, openProduto } = useCtx()
  const st = useApi('/api/estoque/posicao', { nivel: f.nivel, categoria: f.categoria }, [versao])
  return (
    <Load state={st} height={600}>{(d) => {
      const e = d.estoque, te = d.tempo_estoque
      if (e.status !== 'ok') return <Empty title="Sem estoque">{e.motivo}</Empty>
      const rup = te.faixas?.find((x) => x.status === 'ruptura')
      return (
        <>
          <Stats>
            <Stat label="Unidades em estoque" value={n0(e.total)} sub={`${n0(e.skus_com_saldo)} SKUs com saldo`} />
            {e.depositos.map((dp) => <Stat key={dp.deposito} label={dp.deposito} value={n0(dp.unidades)} sub={`posição de ${dataBR(dp.data)}`} />)}
            <Stat label="Cobertura geral" value={te.dias === null ? '—' : `${n0(te.dias)} dias`} sub={`demanda de ${d.base[0]} a ${d.base[1]}`} />
            <Stat label="Sem estoque e com venda" value={n0(rup?.skus)} tone={rup?.skus ? 'alarm' : ''} sub="SKUs" />
          </Stats>
          <div className="row">
            <Box title="Unidades por cobertura" sub="Quanto tempo o estoque de cada SKU dura no ritmo atual">
              <StackBar parts={te.faixas.filter((x) => x.status !== 'ruptura').map((x) => ({ label: x.rotulo, value: x.unidades, color: COR[x.status], extra: `${n0(x.skus)} SKUs` }))} unit=" un." />
              <p className="note">{te.nota}</p>
            </Box>
            <Box title={`Estoque por ${NIVEL[f.nivel].toLowerCase()}`} sub="Saldo atual, demanda e cobertura" flush="b" right={<BotaoRelatorio />}>
              <DataTable rows={d.tabela} pageSize={20} searchKeys={['chave', 'descricao']} initialSort={{ key: 'estoque', dir: 'desc' }} columns={[
                { key: 'chave', label: NIVEL[f.nivel], sortValue: (r) => r.chave, render: (r) => <><button className="link" onClick={() => openProduto(f.nivel, r.chave)}>{r.chave}</button><span className="d">{r.descricao}</span></> },
                ...e.depositos.map((dp) => ({ key: 'dep_' + dp.deposito, label: dp.deposito, right: true, sortValue: (r) => r.estoque_depositos?.[dp.deposito] ?? null, render: (r) => n0(r.estoque_depositos?.[dp.deposito]) })),
                { key: 'estoque', label: 'Total', right: true, render: (r) => <b>{n0(r.estoque)}</b> },
                { key: 'demanda_dia', label: 'Venda/dia', right: true, render: (r) => n1(r.demanda_dia) },
                { key: 'cobertura_dias', label: 'Cobertura', right: true, render: (r) => (r.cobertura_dias === null ? '—' : n0(r.cobertura_dias) + ' d') },
                { key: 'status_estoque', label: 'Situação', render: (r) => <Status s={r.status_estoque} /> },
              ]} />
            </Box>
          </div>
        </>
      )
    }}</Load>
  )
}

const ORDEM = ['ruptura_sem_pedido', 'critico_sem_pedido', 'pedido_chega_tarde', 'ruptura_com_pedido', 'coberto', 'excesso', 'sem_demanda', 'ok']

export function Reposicao() {
  const { f, versao, openProduto } = useCtx()
  const st = useApi('/api/estoque/reposicao', { nivel: f.nivel, categoria: f.categoria }, [versao])
  const [sit, setSit] = useState('ruptura_sem_pedido')
  return (
    <Load state={st} height={600}>{(d) => {
      const r = d.reposicao
      if (r.status !== 'ok') return <Empty>{r.motivo}</Empty>
      const c = r.contagem
      const rows = r.itens.filter((x) => !sit || x.situacao === sit)
      const g = d.grade
      return (
        <>
          <p className="lead">Cruza o estoque de hoje, a venda dos últimos 3 meses ({r.base[0]} a {r.base[1]}) e os pedidos em aberto no Omie{d.fornecedor ? ` (${d.fornecedor})` : ''}. Comece pelos itens zerados sem pedido.</p>
          <Box title="Situação de reposição" sub={`Por ${NIVEL[f.nivel].toLowerCase()}`} flush="b" right={<BotaoRelatorio />}>
            <div className="pills" role="group" aria-label="Filtrar por situação">
              {ORDEM.filter((s) => c[s]).map((s) => (
                <button key={s} className="pill" aria-pressed={sit === s} onClick={() => setSit(sit === s ? null : s)}>
                  <Status s={s} label="" />{STATUS_REPO[s]} <b className="num">{n0(c[s].itens)}</b>
                </button>
              ))}
            </div>
            <DataTable rows={rows} searchKeys={['chave', 'descricao']} initialSort={{ key: 'demanda_mes', dir: 'desc' }} pageSize={20} columns={[
              { key: 'chave', label: NIVEL[f.nivel], sortValue: (x) => x.chave, render: (x) => <><button className="link" onClick={() => openProduto(f.nivel, x.chave)}>{x.chave}</button><span className="d">{x.descricao}</span></> },
              { key: 'demanda_mes', label: 'Vende/mês', right: true, render: (x) => n0(x.demanda_mes) },
              { key: 'estoque', label: 'Estoque', right: true, cls: (x) => (x.estoque <= 0 ? 'z' : ''), render: (x) => n0(x.estoque) },
              { key: 'cobertura', label: 'Dura', right: true, render: (x) => (x.cobertura === null ? '—' : n0(x.cobertura) + ' d') },
              { key: 'a_receber', label: 'A receber', right: true, cls: (x) => (x.a_receber > 0 ? 'in' : 'dim'), render: (x) => n0(x.a_receber) },
              { key: 'previsao', label: 'Previsão', sortValue: (x) => x.previsao, render: (x) => {
                if (!x.previsao) return <span style={{ color: 'var(--muted)' }}>—</span>
                const da = diasAte(x.previsao)
                return <span style={{ color: da < 0 ? 'var(--inbound)' : undefined }}>{dataCurta(x.previsao)}{da < 0 ? ' (faturado)' : ` (${da} d)`}</span>
              } },
              { key: 'cobertura_com_pedidos', label: 'Dura c/ pedidos', right: true, render: (x) => (x.cobertura_com_pedidos === null ? '—' : n0(x.cobertura_com_pedidos) + ' d') },
              { key: 'situacao', label: 'Situação', render: (x) => <Status s={x.situacao} /> },
            ]} />
            <p className="note" style={{ padding: '0 18px' }}>{r.nota} A base de 3 meses não capta sazonalidade: compras para a próxima estação podem aparecer como excesso.</p>
          </Box>
          <div style={{ height: 16 }} />
          <Box title="Grade quebrada" sub={g.status === 'ok' ? `${n0(g.skus)} SKUs que vendem com algum tamanho zerado; ${n0(g.sem_reposicao)} têm tamanhos sem nenhum pedido` : ''} flush="b">
            {g.status !== 'ok' ? <div className="box-b"><Empty>{g.motivo}</Empty></div> : (
              <DataTable rows={g.itens.map((x) => ({ ...x, chave: x.sku }))} searchKeys={['sku']} pageSize={15} initialSort={{ key: 'pares_mes', dir: 'desc' }} columns={[
                { key: 'sku', label: 'SKU', render: (x) => <button className="link" onClick={() => openProduto('sku', x.sku)}>{x.sku}</button> },
                { key: 'pares_mes', label: 'Vende/mês', right: true, render: (x) => n0(x.pares_mes) },
                { key: 'estoque', label: 'Estoque', right: true, render: (x) => n0(x.estoque) },
                { key: 'disponivel_pct', label: 'Grade disponível', right: true, render: (x) => n0(x.disponivel_pct) + '%' },
                { key: 'tamanhos_sem_pedido', label: 'Zerados sem pedido', sortValue: (x) => x.tamanhos_sem_pedido.length, render: (x) => x.tamanhos_sem_pedido.length ? <b style={{ color: 'var(--critical-ink)' }}>{x.tamanhos_sem_pedido.join(', ')}</b> : <span style={{ color: 'var(--muted)' }}>nenhum</span> },
                { key: 'a_caminho', label: 'Zerados com pedido', sortable: false, render: (x) => Object.keys(x.a_caminho).length ? <span style={{ color: 'var(--inbound)' }}>{Object.entries(x.a_caminho).map(([t, q]) => `${t} (${n0(q)})`).join(', ')}</span> : <span style={{ color: 'var(--muted)' }}>—</span> },
              ]} />
            )}
          </Box>
        </>
      )
    }}</Load>
  )
}

export function Parado() {
  const { f, versao, openProduto } = useCtx()
  const st = useApi('/api/estoque/parado', { nivel: f.nivel, categoria: f.categoria }, [versao])
  const [tab, setTab] = useState('parado')
  return (
    <Load state={st} height={600}>{(d) => {
      const p = d.parado
      const exc = d.tempo_estoque?.faixas?.find((x) => x.status === 'excesso')
      return (
        <>
          <Stats>
            <Stat label="Sem venda em 3 meses" value={n0(p.unidades)} sub={`unidades em ${n0(p.skus)} SKUs`} />
            <Stat label="Mais de 120 dias de cobertura" value={n0(exc?.unidades)} sub={`unidades em ${n0(exc?.skus)} SKUs`} />
          </Stats>
          <div className="tabs" role="tablist">
            <button role="tab" aria-selected={tab === 'parado'} onClick={() => setTab('parado')}>Sem venda</button>
            <button role="tab" aria-selected={tab === 'excesso'} onClick={() => setTab('excesso')}>Excesso de cobertura</button>
          </div>
          {tab === 'parado' ? (
            <Box title="Estoque sem venda" sub={p.base ? `Sem venda de ${p.base[0]} a ${p.base[1]}: candidatos a promoção ou liquidação` : ''} flush="b">
              <DataTable rows={p.itens || []} searchKeys={['chave', 'descricao']} initialSort={{ key: 'estoque', dir: 'desc' }} columns={[
                { key: 'chave', label: NIVEL[f.nivel], render: (x) => <><button className="link" onClick={() => openProduto(f.nivel, x.chave)}>{x.chave}</button><span className="d">{x.descricao || 'Sem venda no histórico importado'}</span></> },
                { key: 'estoque', label: 'Unidades', right: true, render: (x) => n0(x.estoque) },
                { key: 'ultima_venda', label: 'Última venda', render: (x) => x.ultima_venda },
              ]} />
            </Box>
          ) : (
            <Box title="Excesso de cobertura" sub="Estoque para mais de 120 dias no ritmo do período" flush="b">
              <DataTable rows={d.excesso} searchKeys={['chave', 'descricao']} initialSort={{ key: 'cobertura_dias', dir: 'desc' }} columns={[
                { key: 'chave', label: NIVEL[f.nivel], render: (x) => <><button className="link" onClick={() => openProduto(f.nivel, x.chave)}>{x.chave}</button><span className="d">{x.descricao}</span></> },
                { key: 'estoque', label: 'Estoque', right: true, render: (x) => n0(x.estoque) },
                { key: 'demanda_dia', label: 'Venda/dia', right: true, render: (x) => n1(x.demanda_dia) },
                { key: 'cobertura_dias', label: 'Cobertura', right: true, render: (x) => n0(x.cobertura_dias) + ' d' },
              ]} />
            </Box>
          )}
        </>
      )
    }}</Load>
  )
}

export function Perdidas() {
  const { f, per, versao, openProduto } = useCtx()
  const st = useApi('/api/estoque/perdidas', { inicio: per[0], fim: per[1], nivel: f.nivel, categoria: f.categoria }, [versao])
  return (
    <Load state={st} height={500}>{(d) => {
      const v = d.vendas_perdidas, r = d.rupturas
      return (
        <>
          {v.status !== 'ok' ? (
            <div style={{ marginBottom: 16 }}><Empty title="Ainda sem histórico para este período">{v.motivo}</Empty></div>
          ) : (
            <Stats>
              <Stat label="Unidades perdidas" value={n1(v.pares)} tone="alarm" sub={`${n0(v.skus)} SKUs afetados`} />
              <Stat label="Faturamento perdido (estimado)" value={money(v.valor)} sub="pelo preço médio de cada SKU" />
              <Stat label="Dias monitorados" value={n0(v.dias_monitorados)} sub={`de ${dataBR(v.primeira_foto)} a ${dataBR(v.ultima_foto)}`} />
            </Stats>
          )}
          <div className="row c2">
            <Box title="Onde as vendas foram perdidas" sub={v.status === 'ok' ? v.nota : ''} flush="b">
              {v.status !== 'ok' || !v.itens.length ? <div className="box-b"><Empty>{v.nota || 'Nenhuma perda registrada.'}</Empty></div> : (
                <ul className="list">{v.itens.slice(0, 20).map((i) => (
                  <li key={i.chave}><div className="t"><button className="link" onClick={() => openProduto(f.nivel, i.chave)}>{i.chave}</button><span>{i.descricao} · {i.dias} dia(s) zerado</span></div>
                    <div className="v">{n1(i.pares)}<small>{money(i.valor)}</small></div></li>))}</ul>)}
            </Box>
            <Box title="Zerados agora" sub={r.status === 'ok' ? `≈ ${n0(r.pares_mes)} unidades/mês de demanda sem estoque` : ''} flush="b">
              {r.status !== 'ok' ? <div className="box-b"><Empty>{r.motivo}</Empty></div> : (
                <ul className="list">{r.itens.slice(0, 20).map((i) => (
                  <li key={i.chave}><div className="t"><button className="link" onClick={() => openProduto(f.nivel, i.chave)}>{i.chave}</button><span>{i.descricao}</span></div>
                    <div className="v">{n0(i.pares_mes)}<small>un./mês</small></div></li>))}</ul>)}
            </Box>
          </div>
          <p className="note">Perda do dia = demanda diária do SKU (vendas dos últimos 3 meses ÷ dias com estoque) em cada dia em que ele ficou zerado na soma dos depósitos. Importe o estoque todos os dias para acumular o histórico.</p>
        </>
      )
    }}</Load>
  )
}

/** Link para baixar o relatório de estoque em Excel com os filtros atuais. */
export function BotaoRelatorio({ fornecedor = '__todos', dias = 7, limite, primario }) {
  const { f } = useCtx()
  const href = urlApi('/api/relatorios/estoque.xlsx', { nivel: f.nivel, categoria: f.categoria, fornecedor, dias, limite })
  return <a className={`btn ${primario ? 'primary' : 'ghost'}`} href={href} download><Icon name="download" />Baixar relatório (Excel)</a>
}

const LIMITES = [7, 15, 30, 45, 60]

/** Compara pedidos de compra com o estoque: o que está baixo sem pedido e o que foi comprado e está chegando. */
export function PedidosXEstoque() {
  const { f, versao, openProduto, go } = useCtx()
  const [forn, setForn] = useState('__todos')
  const [limite, setLimite] = useState(15)
  const [aba, setAba] = useState('sem')
  const [filtroCheg, setFiltroCheg] = useState(null)
  const ped = useApi('/api/compras/pedidos', {}, [versao])
  const st = useApi('/api/estoque/reposicao', { nivel: f.nivel, categoria: f.categoria, fornecedor: forn }, [versao])
  const fornecedores = ped.data?.fornecedores || []
  return (
    <Load state={st} height={600}>{(d) => {
      const r = d.reposicao
      if (r.status !== 'ok') return <Empty>{r.motivo}</Empty>
      const vende = (x) => (x.demanda_mes || 0) > 0
      const baixo = r.itens.filter((x) => (x.a_receber || 0) <= 0 && vende(x) && ((x.estoque || 0) <= 0 || (x.cobertura !== null && x.cobertura < limite)))
      const chegando = r.itens.filter((x) => (x.a_receber || 0) > 0).map((x) => {
        const da = diasAte(x.previsao)
        const tempo = !vende(x) ? 'sem_venda' : (x.estoque || 0) <= 0 ? 'ja_zerado'
          : (da !== null && da < 0) ? 'atrasado'
            : (da !== null && x.cobertura !== null && da > x.cobertura) ? 'nao_chega' : 'chega'
        return { ...x, chega_em: da, tempo }
      })
      const zerados = baixo.filter((x) => (x.estoque || 0) <= 0)
      const cont = (t) => chegando.filter((x) => x.tempo === t).length
      const ROT_T = { chega: 'Chega antes de acabar', nao_chega: 'Chega depois de acabar', atrasado: 'Faturado', ja_zerado: 'Já está zerado', sem_venda: 'Sem venda recente' }
      const rowsCheg = chegando.filter((x) => !filtroCheg || x.tempo === filtroCheg)
      const colChave = { key: 'chave', label: NIVEL[f.nivel], sortValue: (x) => x.chave, render: (x) => <><button className="link" onClick={() => openProduto(f.nivel, x.chave)}>{x.chave}</button><span className="d">{x.descricao}</span></> }
      return (
        <>
          <p className="lead">Cruza o estoque de hoje, a venda dos últimos 3 meses ({r.base[0]} a {r.base[1]}) e os pedidos de compra em aberto no Omie. Estoque baixo = zerado ou durando menos de {limite} dias no ritmo atual.</p>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginBottom: 16 }}>
            <label className="ctl"><Icon name="truck" /><span className="sr-only">Pedidos de</span>
              <select value={forn} onChange={(e) => setForn(e.target.value)} aria-label="Pedidos de qual fornecedor">
                <option value="__todos">Todos os fornecedores</option>
                {fornecedores.map((x) => <option key={x.fornecedor} value={x.fornecedor}>{x.fornecedor}</option>)}
              </select>
            </label>
            <label className="ctl">Estoque baixo: menos de
              <select value={limite} onChange={(e) => setLimite(Number(e.target.value))} aria-label="Limite de estoque baixo">
                {LIMITES.map((n) => <option key={n} value={n}>{n} dias</option>)}
              </select>
            </label>
            <span style={{ marginLeft: 'auto' }}><BotaoRelatorio fornecedor={forn} limite={limite} /></span>
          </div>
          <Stats>
            <Stat label="Baixo e sem pedido" value={n0(baixo.length)} tone={baixo.length ? 'alarm' : ''} sub={`${n0(zerados.length)} já zerados · ${n0(baixo.reduce((a, x) => a + (x.demanda_mes || 0), 0))} un./mês de venda em risco`} />
            <Stat label="Comprado, chegando" value={n0(chegando.length)} tone="inbound" sub={`${n0(chegando.reduce((a, x) => a + (x.a_receber || 0), 0))} unidades a receber`} />
            <Stat label="Chega depois de acabar" value={n0(cont('nao_chega'))} tone={cont('nao_chega') ? 'alarm' : ''} sub="previsão posterior ao fim do estoque" />
            <Stat label="Faturado" value={n0(cont('atrasado'))} tone="inbound" sub="tem estoque e o pedido já foi faturado" />
            <Stat label="Zerado, pedido a caminho" value={n0(cont('ja_zerado'))} sub="vende, está zerado e tem pedido" />
            <Stat label="Comprado sem venda recente" value={n0(cont('sem_venda'))} sub="pedido em aberto sem venda em 3 meses" />
          </Stats>
          <div className="tabs" role="tablist">
            <button role="tab" aria-selected={aba === 'sem'} onClick={() => setAba('sem')}>Estoque baixo sem pedido ({n0(baixo.length)})</button>
            <button role="tab" aria-selected={aba === 'com'} onClick={() => setAba('com')}>Comprado e chegando ({n0(chegando.length)})</button>
          </div>
          {aba === 'sem' ? (
            <Box title="Estoque baixo e sem pedido de compra" sub="Vendem, estão acabando e não há pedido em aberto. Ordenado pela venda: os primeiros são os mais urgentes." flush="b">
              <DataTable rows={baixo} searchKeys={['chave', 'descricao']} initialSort={{ key: 'demanda_mes', dir: 'desc' }} pageSize={25} empty="Nenhum item com estoque baixo sem pedido." columns={[
                colChave,
                { key: 'demanda_mes', label: 'Vende/mês', right: true, render: (x) => n0(x.demanda_mes) },
                { key: 'estoque', label: 'Estoque', right: true, cls: (x) => (x.estoque <= 0 ? 'z' : ''), render: (x) => n0(x.estoque) },
                { key: 'cobertura', label: 'Dura', right: true, sortValue: (x) => (x.estoque <= 0 ? -1 : x.cobertura), render: (x) => (x.estoque <= 0 ? <b style={{ color: 'var(--critical-ink)' }}>zerado</b> : x.cobertura === null ? '—' : n0(x.cobertura) + ' d') },
                { key: 'acaba', label: 'Acaba em', sortValue: (x) => (x.estoque <= 0 ? -1 : x.cobertura), render: (x) => { if (x.estoque <= 0 || x.cobertura === null) return '—'; const dt = new Date(); dt.setDate(dt.getDate() + x.cobertura); return dt.toLocaleDateString('pt-BR') } },
                { key: 'situacao', label: 'Situação', render: (x) => <Status s={x.situacao} /> },
              ]} />
            </Box>
          ) : (
            <Box title="Comprado e com estoque chegando" sub="Itens com pares a receber em pedidos em aberto. 'Chega a tempo' compara a previsão com quanto o estoque atual dura." flush="b"
              right={<button className="btn ghost" onClick={() => go('/compras/pedidos')}>Ver pedidos</button>}>
              <div className="pills" role="group" aria-label="Filtrar por chegada">
                {['nao_chega', 'atrasado', 'ja_zerado', 'chega', 'sem_venda'].filter((t) => cont(t)).map((t) => (
                  <button key={t} className="pill" aria-pressed={filtroCheg === t} onClick={() => setFiltroCheg(filtroCheg === t ? null : t)}>
                    <Status s={t} label="" />{ROT_T[t]} <b className="num">{n0(cont(t))}</b></button>))}
              </div>
              <DataTable rows={rowsCheg} searchKeys={['chave', 'descricao']} initialSort={{ key: 'previsao', dir: 'asc' }} pageSize={25} empty="Nenhum item com pedido em aberto." columns={[
                colChave,
                { key: 'demanda_mes', label: 'Vende/mês', right: true, render: (x) => n0(x.demanda_mes) },
                { key: 'estoque', label: 'Estoque', right: true, cls: (x) => (x.estoque <= 0 ? 'z' : ''), render: (x) => n0(x.estoque) },
                { key: 'cobertura', label: 'Dura', right: true, render: (x) => (x.cobertura === null ? '—' : n0(x.cobertura) + ' d') },
                { key: 'a_receber', label: 'A receber', right: true, cls: () => 'in', render: (x) => n0(x.a_receber) },
                { key: 'previsao', label: 'Previsão', sortValue: (x) => x.previsao, render: (x) => {
                  if (!x.previsao) return '—'
                  return <span style={{ color: x.chega_em < 0 ? 'var(--inbound)' : undefined }}>{dataCurta(x.previsao)}{x.chega_em < 0 ? ' (faturado)' : ` (${x.chega_em} d)`}</span>
                } },
                { key: 'cobertura_com_pedidos', label: 'Dura c/ pedido', right: true, render: (x) => (x.cobertura_com_pedidos === null ? '—' : n0(x.cobertura_com_pedidos) + ' d') },
                { key: 'tempo', label: 'Chega a tempo?', render: (x) => <Status s={x.tempo} label={ROT_T[x.tempo]} /> },
              ]} />
            </Box>
          )}
          <p className="note">{r.nota}</p>
        </>
      )
    }}</Load>
  )
}

const ROT_TEND = { baixando: 'Baixando', zerou: 'Zerou', subindo: 'Subindo', entrou: 'Entrou', estavel: 'Estável', sem_historico: 'Sem histórico' }

/** Relatórios para baixar e leitura da tendência do estoque. */
export function Relatorios() {
  const { f, versao, openProduto } = useCtx()
  const [dias, setDias] = useState(7)
  const [forn, setForn] = useState('__todos')
  const [limite, setLimite] = useState(15)
  const [tend, setTend] = useState(null)
  const ped = useApi('/api/compras/pedidos', {}, [versao])
  const st = useApi('/api/estoque/tendencia', { nivel: f.nivel, categoria: f.categoria, dias }, [versao])
  const fornecedores = ped.data?.fornecedores || []
  return (
    <>
      <Box title="Relatório de estoque em Excel" sub={`Usa os filtros do topo: ${f.categoria === 'calcado' ? 'calçados' : f.categoria === 'outro' ? 'outros produtos' : 'todos os produtos'}, agrupado por ${NIVEL[f.nivel].toLowerCase()}.`}>
        <div className="row c2" style={{ marginBottom: 0 }}>
          <div>
            <p style={{ margin: '0 0 8px', fontWeight: 500 }}>O arquivo traz uma aba para cada leitura:</p>
            <ul className="lista-rel">
              <li><b>Resumo</b>: os números principais, em fórmulas que leem as outras abas</li>
              <li><b>Posição</b>: estoque por depósito, venda/dia, cobertura e situação</li>
              <li><b>Tendência</b>: se o estoque está baixando, subindo ou zerou, e quando zera</li>
              <li><b>Reposição</b>: estoque x venda x pedidos em aberto</li>
              <li><b>Sem pedido e baixo</b> e <b>Comprado chegando</b>, com "chega a tempo?"</li>
              <li><b>Grade quebrada</b>, <b>Parado</b> e <b>Evolução</b> do estoque total</li>
            </ul>
          </div>
          <div>
            <div className="formrow" style={{ gridTemplateColumns: '170px minmax(0, 1fr)' }}><label htmlFor="rel-forn">Pedidos considerados</label>
              <select id="rel-forn" value={forn} onChange={(e) => setForn(e.target.value)}>
                <option value="__todos">Todos os fornecedores</option>
                {fornecedores.map((x) => <option key={x.fornecedor} value={x.fornecedor}>{x.fornecedor}</option>)}
              </select></div>
            <div className="formrow" style={{ gridTemplateColumns: '170px minmax(0, 1fr)' }}><label htmlFor="rel-dias">Comparar estoque com</label>
              <select id="rel-dias" value={dias} onChange={(e) => setDias(Number(e.target.value))}>
                {[7, 15, 30, 60, 90].map((n) => <option key={n} value={n}>{n} dias atrás</option>)}
              </select></div>
            <div className="formrow" style={{ gridTemplateColumns: '170px minmax(0, 1fr)' }}><label htmlFor="rel-lim">Estoque baixo</label>
              <select id="rel-lim" value={limite} onChange={(e) => setLimite(Number(e.target.value))}>
                {LIMITES.map((n) => <option key={n} value={n}>menos de {n} dias</option>)}
              </select></div>
            <div style={{ marginTop: 12 }}><BotaoRelatorio fornecedor={forn} dias={dias} limite={limite} primario /></div>
          </div>
        </div>
      </Box>
      <div style={{ height: 16 }} />
      <Load state={st} height={400}>{(t) => {
        if (t.status !== 'ok') return <Empty>{t.motivo}</Empty>
        const c = t.contagem
        const rows = t.itens.filter((x) => !tend || x.tendencia === tend)
        const varTot = t.tem_historico ? t.total_atual - t.total_antes : null
        return (
          <>
            <Stats>
              <Stat label="Estoque hoje" value={n0(t.total_atual)} sub={`foto de ${dataBR(t.data_atual)}`} />
              {t.tem_historico ? <>
                <Stat label={`Desde ${dataBR(t.data_anterior)}`} value={(varTot > 0 ? '+' : '') + n0(varTot)} tone={varTot < 0 ? 'alarm' : 'inbound'} sub={t.total_antes ? pct((varTot / t.total_antes) * 100) + ' no total' : ''} />
                <Stat label="Itens baixando" value={n0(c.baixando)} sub={`${n0(c.zerou)} zeraram no período`} />
                <Stat label="Itens subindo" value={n0((c.subindo || 0) + (c.entrou || 0))} sub={`${n0(c.estavel)} estáveis`} />
              </> : <Stat label="Histórico" na value="Uma data só" sub="importe o estoque todo dia para ver a evolução" />}
            </Stats>
            {t.evolucao.length > 1 && (
              <Box title="Estoque total ao longo do tempo" sub="Soma dos depósitos em cada data importada">
                <MonthLine data={t.evolucao} dataKey="unidades" rows={[['Unidades', (x) => n0(x.unidades)]]} height={220} />
              </Box>
            )}
            {t.evolucao.length > 1 && <div style={{ height: 16 }} />}
            <Box title="Está baixando?" sub={t.tem_historico ? `Estoque de ${dataBR(t.data_anterior)} comparado com ${dataBR(t.data_atual)}, por ${NIVEL[f.nivel].toLowerCase()}` : 'Ordenado por quem zera primeiro no ritmo de venda atual'} flush="b">
              {t.tem_historico && (
                <div className="pills" role="group" aria-label="Filtrar por tendência">
                  {['baixando', 'zerou', 'subindo', 'entrou', 'estavel'].filter((k) => c[k]).map((k) => (
                    <button key={k} className="pill" aria-pressed={tend === k} onClick={() => setTend(tend === k ? null : k)}>
                      <Status s={k} label="" />{ROT_TEND[k]} <b className="num">{n0(c[k])}</b></button>))}
                </div>
              )}
              <DataTable rows={rows} searchKeys={['chave', 'descricao']} pageSize={20}
                initialSort={t.tem_historico ? { key: 'variacao', dir: 'asc' } : { key: 'dias_para_zerar', dir: 'asc' }} columns={[
                { key: 'chave', label: NIVEL[f.nivel], sortValue: (x) => x.chave, render: (x) => <><button className="link" onClick={() => openProduto(f.nivel, x.chave)}>{x.chave}</button><span className="d">{x.descricao}</span></> },
                ...(t.tem_historico ? [
                  { key: 'estoque_antes', label: `Em ${dataCurta(t.data_anterior)}`, right: true, render: (x) => n0(x.estoque_antes) },
                ] : []),
                { key: 'estoque', label: t.tem_historico ? `Em ${dataCurta(t.data_atual)}` : 'Estoque', right: true, cls: (x) => (x.estoque <= 0 ? 'z' : ''), render: (x) => n0(x.estoque) },
                ...(t.tem_historico ? [
                  { key: 'variacao', label: 'Variação', right: true, render: (x) => <span style={{ color: x.variacao < 0 ? 'var(--critical-ink)' : x.variacao > 0 ? 'var(--good-ink)' : undefined }}>{x.variacao > 0 ? '+' : ''}{n0(x.variacao)}{x.variacao_pct !== null && <span className="d">{pct(x.variacao_pct)}</span>}</span> },
                  { key: 'tendencia', label: 'Tendência', render: (x) => <Status s={x.tendencia} label={ROT_TEND[x.tendencia]} /> },
                ] : []),
                { key: 'venda_mes', label: 'Vende/mês', right: true, render: (x) => n0(x.venda_mes) },
                { key: 'dias_para_zerar', label: 'Zera em', sortValue: (x) => x.dias_para_zerar ?? 99999, render: (x) => (x.zera_em ? <>{dataBR(x.zera_em)}<span className="d">{n0(x.dias_para_zerar)} dias</span></> : <span style={{ color: 'var(--muted)' }}>{x.estoque <= 0 ? 'zerado' : 'sem venda'}</span>) },
              ]} />
              <p className="note" style={{ padding: '0 18px' }}>{t.nota}</p>
            </Box>
          </>
        )
      }}</Load>
    </>
  )
}
