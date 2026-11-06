import { useRef, useState } from 'react'
import { api } from '../api'
import { dataBR, n0 } from '../fmt'
import { useCtx } from '../ctx'
import { VERSAO as VERSAO_INTERFACE } from '../versao'
import { Box, DataTable, Empty, useApi } from '../ui'
import { ESTADOS, MarcarLinha } from '../linha'

const ErrorBox = ({ error }) => <div className="err">{error.message}</div>
const Loading = () => <div className="skel" style={{ height: 200 }} />

const TIPOS = { vendas: 'Vendas mensais', vendas_dia: 'Vendas por período (SKU x quantidade)', estoque: 'Posição de estoque', compras: 'Compras (notas de entrada)', itens_compra: 'Itens comprados (notas, sem preço)' }
const CANAIS = [['shopee', 'Shopee'], ['ml', 'Mercado Livre'], ['nao_informado', 'Não informar']]
const CAMPOS = {
  vendas: [['unidades', 'Unidades (total)', true], ['faturamento', 'Faturamento (total)', true], ['unidades_ml', 'Unidades Mercado Livre'],
    ['unidades_shopee', 'Unidades Shopee'], ['pecas', 'Unidades em peças (visão compra)']],
  vendas_dia: [['codigo', 'SKU', true], ['quantidade', 'Quantidade vendida', true], ['ticket_medio', 'Ticket médio']],
  itens_compra: [['fornecedor', 'Emitente', true], ['data', 'Data de emissão', true], ['numero', 'Número da nota', true], ['ean', 'EAN do item', true], ['valor_nota', 'Valor total da nota (só para não duplicar)']],
  estoque: [['codigo', 'Código do produto', true], ['quantidade', 'Quantidade disponível', true]],
  compras: [['data', 'Data (de emissão)', true], ['sku', 'SKU', true], ['valor_unitario', 'Valor unitário', true], ['quantidade', 'Quantidade'],
    ['preco_desconto', 'Preço com desconto'], ['valor_nota', 'Valor total da nota'], ['valor_produtos', 'Valor total dos produtos'],
    ['ean', 'EAN'], ['fornecedor', 'Fornecedor'], ['numero_nota', 'Número da nota']],
}
const hoje = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10)

function Contagens({ r }) {
  return (
    <div className="counts">
      {[['adicionados', 'Adicionados'], ['atualizados', 'Atualizados'], ['duplicados', 'Duplicados (ignorados)'], ['rejeitados', 'Rejeitados'], ['ignorados', 'Linhas sem código/total']].map(([k, t]) => (
        <div key={k}><b>{n0(r[k])}</b><span>{t}</span></div>))}
    </div>
  )
}

function Mapeamento({ prev, setPrev }) {
  const t = prev.tipo, m = prev.mapeamento || {}
  const abas = Object.keys(prev.colunas)
  if (t === 'vendas') {
    const abaU = m.abas?.unidades || abas[0]
    const cols = prev.colunas[abaU] || []
    const setAba = (k, v) => setPrev({ ...prev, mapeamento: { ...m, abas: { ...m.abas, [k]: v || undefined } } })
    return (
      <>
        {CAMPOS.vendas.map(([k, t2, obr]) => (
          <div className="formrow" key={k}><label>{t2}{obr ? ' *' : ''}</label>
            <select value={m.abas?.[k] || ''} onChange={(e) => setAba(k, e.target.value)}>
              <option value="">Não usar</option>{abas.map((a) => <option key={a}>{a}</option>)}
            </select></div>))}
        <div className="formrow"><label>Coluna do SKU *</label>
          <select value={m.coluna_sku || ''} onChange={(e) => setPrev({ ...prev, mapeamento: { ...m, coluna_sku: e.target.value } })}>
            {cols.map((c) => <option key={c}>{c}</option>)}</select></div>
        <p className="note">Colunas de mês são reconhecidas pelo nome (ex.: “jan/26”); “parcial” no nome marca o mês em andamento.</p>
      </>
    )
  }
  const aba = m.aba || abas[0]
  const cols = prev.colunas[aba] || []
  const setCol = (k, v) => setPrev({ ...prev, mapeamento: { ...m, colunas: { ...m.colunas, [k]: v || null } } })
  return (
    <>
      {abas.length > 1 && <div className="formrow"><label>Aba</label>
        <select value={aba} onChange={(e) => setPrev({ ...prev, mapeamento: { ...m, aba: e.target.value } })}>{abas.map((a) => <option key={a}>{a}</option>)}</select></div>}
      {CAMPOS[t].map(([k, t2, obr]) => (
        <div className="formrow" key={k}><label>{t2}{obr ? ' *' : ''}</label>
          <select value={m.colunas?.[k] || ''} onChange={(e) => setCol(k, e.target.value)}>
            <option value="">Não usar</option>{cols.map((c) => <option key={c}>{c}</option>)}
          </select></div>))}
    </>
  )
}

export function Importar() {
  const { bump: onImported, setFiltro, go } = useCtx()
  return <ImportarInner onImported={onImported} setFiltro={setFiltro} go={go} />
}

function ImportarInner({ onImported, setFiltro, go }) {
  // fila de prévias: cada arquivo enviado tem a sua, com parâmetros próprios
  const [fila, setFila] = useState([])
  const [feitos, setFeitos] = useState([])
  const [erro, setErro] = useState(null)
  const [lendo, setLendo] = useState(0)
  const [lote, setLote] = useState(false)
  const [over, setOver] = useState(false)
  const input = useRef()
  const seq = useRef(0)

  const enviar = async (files) => {
    const lista = Array.from(files || []).filter(Boolean)
    if (!lista.length) return
    setErro(null); setFeitos([]); setLendo((n) => n + lista.length)
    for (const file of lista) {
      const f = new FormData()
      f.append('arquivo', file)
      f.append('data_referencia', hoje())
      try {
        const prev = await api.upload('/api/importar/previa', f)
        setFila((q) => [...q, { id: ++seq.current, prev }])
      } catch (e) { setErro(new Error(`${file.name}: ${e.message}`)) }
      finally { setLendo((n) => n - 1) }
    }
    if (input.current) input.current.value = ''
  }
  const atualizar = (id, prev) => setFila((q) => q.map((x) => (x.id === id ? { ...x, prev } : x)))
  const remover = (id) => setFila((q) => q.filter((x) => x.id !== id))
  const confirmarUm = async (item) => {
    const p = item.prev
    const r = await api.post('/api/importar/confirmar', { token: p.token, tipo: p.tipo, mapeamento: p.mapeamento, parametros: p.parametros || {} })
    setFeitos((f) => [...f, r]); remover(item.id)
    // vendas do dia caem no mês em andamento: o resultado passa a mostrar o mês atual
    if (r.tipo === 'vendas_dia') setFiltro({ periodo: { preset: 'atual' } })
    return r
  }
  const confirmarTodas = async () => {
    setLote(true); setErro(null)
    const prontos = fila.filter((x) => x.prev.tipo)
    for (const item of prontos) {
      try { await confirmarUm(item) } catch (e) { setErro(new Error(`${item.prev.arquivo}: ${e.message}`)); break }
    }
    setLote(false); onImported()
  }
  // vendas por período com o mesmo canal, conta e período: a segunda substituiria a primeira
  const chave = (p) => (p.tipo === 'vendas_dia' ? [p.parametros?.canal, p.parametros?.conta || '', p.parametros?.periodo_inicio, p.parametros?.periodo_fim].join('|') : null)
  const repetidos = new Set()
  const vistos = new Set()
  fila.forEach((x) => { const k = chave(x.prev); if (k) { if (vistos.has(k)) repetidos.add(k); vistos.add(k) } })
  return (
    <>
      <div className={`drop ${over ? 'over' : ''}`} role="button" tabIndex={0} style={fila.length ? { padding: '18px 20px' } : undefined}
        onClick={() => input.current.click()} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && input.current.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); enviar(e.dataTransfer.files) }}>
        <strong>{lendo ? `Lendo ${lendo} arquivo${lendo > 1 ? 's' : ''}…` : fila.length ? 'Adicionar mais arquivos' : 'Arraste um ou mais arquivos .xlsx ou .csv, ou clique para escolher'}</strong>
        {!fila.length && <span>Vendas (relatório mensal ou lista de vendidos do dia), estoque ou compras: o tipo é reconhecido automaticamente e nada é gravado antes da sua confirmação. Dá para enviar várias planilhas de uma vez.</span>}
        <input ref={input} type="file" accept=".xlsx,.xls,.csv" multiple hidden onChange={(e) => enviar(e.target.files)} />
      </div>
      {erro && <div className="alert err">{erro.message}</div>}
      {feitos.length > 0 && (
        <div className="alert">
          <b>{feitos.length === 1 ? `Importação #${feitos[0].importacao_id} concluída` : `${feitos.length} importações concluídas`}</b>. Indicadores atualizados.
          {feitos.some((f) => f.tipo === 'vendas_dia') && <> O período foi ajustado para o mês atual. <button className="link" onClick={() => go('/vendas/resultado')}>Ver o resultado</button></>}
          {feitos.map((f) => (
            <div key={f.importacao_id} style={{ marginTop: 8 }}>
              <span style={{ fontSize: 13 }}>#{f.importacao_id} · {TIPOS[f.tipo]}{f.parametros?.deposito ? ` · ${f.parametros.deposito}` : ''} · {f.arquivo}</span>
              <Contagens r={f.resumo} />
            </div>))}
        </div>
      )}
      <VendasSemanais />
      {fila.length > 1 && (
        <div className="strip" style={{ marginBottom: 12, alignItems: 'center' }}>
          <span><b>{fila.length}</b> arquivos aguardando confirmação</span>
          {repetidos.size > 0 && <span style={{ color: 'var(--critical-ink)' }}>Há planilhas com o mesmo canal, conta e período: a última substituiria as outras. Informe a conta em cada uma.</span>}
          <button className="btn primary" style={{ marginLeft: 'auto' }} disabled={lote || lendo > 0 || fila.some((x) => !x.prev.tipo)} onClick={confirmarTodas}>
            {lote ? 'Importando…' : `Confirmar todas (${fila.length})`}</button>
        </div>
      )}
      {fila.map((item) => (
        <Previa key={item.id} prev={item.prev} setPrev={(p) => atualizar(item.id, p)} onCancel={() => remover(item.id)}
          repetido={repetidos.has(chave(item.prev))} bloqueado={lote}
          onConfirm={async () => { await confirmarUm(item); onImported() }} />
      ))}
      <Box title="Rotina recomendada" className="mt" sub="Para manter o BI atualizado">
        <ul className="msg-list" style={{ marginTop: 0 }}>
          <li><b>Estoque (Unlock e Juatuba): automático pelo Omie.</b> O estoque vem do local Geral do Omie 03 e do Omie 04 (Dados › Omie). Planilha de estoque só se a API estiver fora do ar.</li>
          <li><b>Vendas: quando quiser atualizar.</b> Reimportar o mesmo relatório só atualiza os meses alterados (o mês parcial, por exemplo).</li>
          <li><b>Vendas do dia: se quiser alimentar diariamente.</b> Suba as listas de produtos vendidos (SKU, quantidade e, se tiver, ticket médio), uma por canal ou conta, e escolha o canal e o dia de cada uma. Reenviar o mesmo canal, conta e dia substitui o anterior.</li>
          <li><b>Compras: ao receber notas.</b> Para reenviar um período com a coluna de quantidade, use o modo “Substituir o período”.</li>
        </ul>
      </Box>
    </>
  )
}

/** Prévia de um arquivo: tipo, parâmetros, colunas e validação. Nada é gravado até confirmar. */
function Previa({ prev, setPrev, onCancel, onConfirm, repetido, bloqueado }) {
  const [erro, setErro] = useState(null)
  const [busy, setBusy] = useState(false)
  const [conta, setConta] = useState(prev.parametros?.conta || '')
  const params = prev?.parametros || {}
  const setParam = (k, v) => setPrev({ ...prev, parametros: { ...params, [k]: v } })
  const rodar = async (corpo) => {
    setBusy(true); setErro(null)
    try { setPrev(await api.post('/api/importar/simular', corpo)) } catch (e) { setErro(e) } finally { setBusy(false) }
  }
  const simular = () => rodar({ token: prev.token, tipo: prev.tipo, mapeamento: prev.mapeamento, parametros: params })
  // muda parâmetros e já refaz a prévia (canal, conta e período das vendas por período)
  const ajustar = (novos) => {
    const p2 = { ...params, ...novos }
    setPrev({ ...prev, parametros: p2 })
    rodar({ token: prev.token, tipo: prev.tipo, mapeamento: prev.mapeamento, parametros: p2 })
  }
  const trocarTipo = (t) => rodar({ token: prev.token, tipo: t, mapeamento: null, parametros: params })
  const confirmar = async () => {
    setBusy(true); setErro(null)
    try { await onConfirm() } catch (e) { setErro(e); setBusy(false) }
  }
  const r = prev?.resumo
  const dt = r?.detalhes || {}
  const ocupado = busy || bloqueado
  return (
    <Box title={`Prévia: ${prev.arquivo}`} sub="Nada foi gravado ainda. Ajuste e confirme." className="mb"
      right={<button className="btn" onClick={onCancel} disabled={ocupado}>Cancelar</button>}>
      {erro && <div className="alert err">{erro.message}</div>}
      {repetido && <div className="alert bad">Outra planilha na fila tem o mesmo canal, conta e período. Se forem contas diferentes, informe a conta abaixo; senão, a última importada substitui a outra.</div>}
      <div className="formrow"><label>Tipo de arquivo</label>
        <select value={prev.tipo || ''} onChange={(e) => trocarTipo(e.target.value)} disabled={ocupado}>
          <option value="" disabled>Escolha…</option>{Object.entries(TIPOS).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
        </select></div>
      {prev.tipo === 'vendas_dia' && <>
        <div className="formrow"><label>Canal</label>
          <div className="seg" role="group" aria-label="Canal das vendas">
            {CANAIS.map(([v, t]) => <button key={v} type="button" disabled={ocupado} aria-pressed={(params.canal || 'nao_informado') === v} onClick={() => ajustar({ canal: v })}>{t}</button>)}
          </div></div>
        <div className="formrow"><label>Conta / loja <span style={{ color: 'var(--muted)', fontWeight: 400 }}>(opcional)</span></label>
          <input type="text" placeholder="ex.: Uai 03" maxLength={40} value={conta} disabled={ocupado} onChange={(e) => setConta(e.target.value)}
            onBlur={() => conta.trim() !== (params.conta || '') && ajustar({ conta: conta.trim() })}
            onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()} /></div>
        <div className="formrow"><label>Semana do mês</label>
          <SeletorSemana params={params} disabled={ocupado} onEscolher={(ini, fim) => ajustar({ periodo_inicio: ini, periodo_fim: fim })} /></div>
        <div className="formrow"><label>Vendas de</label>
          <input type="date" disabled={ocupado} value={params.periodo_inicio || params.data_referencia || ''} onChange={(e) => e.target.value && ajustar({ periodo_inicio: e.target.value, periodo_fim: (params.periodo_fim && params.periodo_fim >= e.target.value) ? params.periodo_fim : e.target.value })} /></div>
        <div className="formrow"><label>até</label>
          <input type="date" disabled={ocupado} value={params.periodo_fim || params.periodo_inicio || params.data_referencia || ''} min={params.periodo_inicio || undefined} onChange={(e) => e.target.value && ajustar({ periodo_fim: e.target.value })} /></div>
        <p className="note">Para um dia só, deixe as duas datas iguais. Os dias que o relatório mensal de vendas já cobre não são somados de novo. Com a coluna Ticket médio, o faturamento é Vendas x Ticket médio; sem ela (ou com a célula vazia), é estimado pelo preço médio de cada produto.</p>
        {dt.dias_ja_no_relatorio_mensal > 0 && (
          <label className="check" style={{ display: 'flex', gap: 10, alignItems: 'flex-start', margin: '4px 0 10px', padding: '10px 12px', background: 'var(--surface-2)', borderRadius: 'var(--r)' }}>
            <input type="checkbox" checked={!!(params.somar_sempre ?? dt.somar_sempre)} disabled={ocupado} onChange={(e) => ajustar({ somar_sempre: e.target.checked })} style={{ marginTop: 3 }} />
            <span><b>Somar mesmo assim</b><br /><span style={{ fontSize: 13, color: 'var(--ink-2)' }}>
              O relatório mensal de vendas importado vai até {dataBR(dt.relatorio_mensal_ate)}. Marque se ele ainda não tem as vendas {dt.dias_ja_no_relatorio_mensal === 1 ? 'deste dia' : 'destes dias'}; senão, a venda seria contada duas vezes.</span></span>
          </label>
        )}
        {dt.unidades !== undefined && <div className="counts">
          <div><b>{n0(dt.unidades)}</b><span>unidades</span></div>
          <div><b>{dt.codigos_com_ticket ? 'R$ ' + n0(dt.faturamento_informado) : '—'}</b><span>{dt.codigos_com_ticket ? `faturamento pelo ticket (${n0(dt.codigos_com_ticket)} de ${n0(dt.codigos)} códigos)` : 'sem ticket médio: faturamento estimado'}</span></div>
          <div><b>{dt.ticket_medio ? 'R$ ' + dt.ticket_medio.toFixed(2).replace('.', ',') : '—'}</b><span>ticket médio da planilha</span></div>
          <div><b>{n0(dt.somar_sempre ? dt.dias : dt.dias - dt.dias_ja_no_relatorio_mensal)} de {n0(dt.dias)}</b><span>dias que mudam o resultado do mês</span></div>
        </div>}
      </>}
      {prev.tipo && <>
        {prev.tipo !== 'vendas_dia' && <div className="formrow"><label>{prev.tipo === 'vendas' ? 'Data de extração (dias do mês parcial)' : prev.tipo === 'estoque' ? 'Data da posição de estoque' : 'Data de referência'}</label>
          <input type="date" value={params.data_referencia || ''} onChange={(e) => setParam('data_referencia', e.target.value)} /></div>}
        {prev.tipo === 'estoque' && <div className="formrow"><label>Depósito</label>
          <input type="text" value={params.deposito || ''} onChange={(e) => setParam('deposito', e.target.value)} /></div>}
        {prev.tipo === 'compras' && <div className="formrow"><label>Modo</label>
          <select value={params.modo || 'acrescentar'} onChange={(e) => setParam('modo', e.target.value)}>
            <option value="acrescentar">Acrescentar (ignora linhas já importadas)</option>
            <option value="substituir">Substituir o período do arquivo (para reexportações)</option>
          </select></div>}
        <h3 style={{ fontSize: 14, margin: '16px 0 6px' }}>Colunas</h3>
        <Mapeamento prev={prev} setPrev={setPrev} />
      </>}
      {r && <>
        <h3 style={{ fontSize: 14, margin: '16px 0 0' }}>Resultado da validação</h3>
        <Contagens r={r} />
        {r.avisos.length > 0 && <ul className="msg-list">{r.avisos.map((a, i) => <li key={i}>{a}</li>)}</ul>}
        {r.erros.length > 0 && <>
          <h3 style={{ fontSize: 14, margin: '14px 0 6px' }}>Linhas rejeitadas</h3>
          <div className="tscroll"><table className="dt"><thead><tr><th>Linha</th><th>Aba</th><th>Motivo</th><th>Valor</th></tr></thead>
            <tbody>{r.erros.slice(0, 50).map((e, i) => <tr key={i}><td>{e.linha}</td><td>{e.aba || '—'}</td><td>{e.motivo}</td><td>{String(e.valor ?? '')}</td></tr>)}</tbody></table></div>
        </>}
      </>}
      {prev.mensagem && <div className="alert">{prev.mensagem}</div>}
      <div style={{ display: 'flex', gap: 10, marginTop: 16 }}>
        <button className="btn" onClick={simular} disabled={ocupado || !prev.tipo}>Revalidar</button>
        <button className="btn primary" onClick={confirmar} disabled={ocupado || !prev.tipo}>{busy ? 'Processando…' : 'Confirmar importação'}</button>
      </div>
    </Box>
  )
}

export function Historico() {
  const { bump: onChange } = useCtx()
  return <HistoricoInner onChange={onChange} />
}

function HistoricoInner({ onChange }) {
  const [v, setV] = useState(0)
  const { data, error } = useApi('/api/importacoes', null, [v])
  const [msg, setMsg] = useState(null)
  const desfazer = async (i) => {
    if (!window.confirm(`Desfazer a importação #${i.id} (${i.arquivo})? Os dados voltam ao estado anterior.`)) return
    try { const r = await api.post(`/api/importacoes/${i.id}/desfazer`); setMsg(`Importação #${i.id} desfeita (${n0(r.registros_revertidos)} registros revertidos).`); setV(v + 1); onChange() }
    catch (e) { setMsg(e.message) }
  }
  if (error) return <ErrorBox error={error} />
  if (!data) return <Loading />
  return (
    <>
      {msg && <div className="alert">{msg}</div>}
      <DataTable rows={data} pageSize={20} initialSort={{ key: 'id', dir: 'desc' }} columns={[
        { key: 'id', label: '#', render: (r) => r.id },
        { key: 'criado_em', label: 'Quando', render: (r) => dataBR(r.criado_em) },
        { key: 'tipo', label: 'Tipo', render: (r) => <>{TIPOS[r.tipo]}{r.deposito ? ` · ${r.deposito}` : ''}</> },
        { key: 'arquivo', label: 'Arquivo', render: (r) => <a href={`/api/importacoes/${r.id}/arquivo`}>{r.arquivo}</a> },
        { key: 'data_referencia', label: 'Referência', render: (r) => dataBR(r.data_referencia) },
        { key: 'res', label: 'Adic. / atual. / dup. / rej.', sortable: false, render: (r) => r.resumo ? `${n0(r.resumo.adicionados)} / ${n0(r.resumo.atualizados)} / ${n0(r.resumo.duplicados)} / ${n0(r.resumo.rejeitados)}` : '—' },
        { key: 'status', label: 'Situação', render: (r) => <span className={`tag ${r.status === 'ok' ? 'ok' : 'off'}`}>{r.status === 'ok' ? 'ativa' : 'desfeita'}</span> },
        { key: 'acao', label: '', sortable: false, render: (r) => r.status === 'ok' && <button className="btn danger" onClick={() => desfazer(r)}>Desfazer</button> },
      ]} />
      <p className="note">Desfazer restaura exatamente o estado anterior. Se houver uma importação mais recente do mesmo tipo, desfaça-a primeiro.</p>
    </>
  )
}

export function Vinculos() {
  const { bump: onChange } = useCtx()
  return <VinculosInner onChange={onChange} />
}

function VinculosInner({ onChange }) {
  const [busca, setBusca] = useState('')
  const [v, setV] = useState(0)
  const { data, error } = useApi('/api/vinculos/pendentes', { busca }, [v])
  const [sel, setSel] = useState({})
  const [sug, setSug] = useState([])
  const salvar = async (codigo) => {
    const s = sel[codigo]
    if (!s) return
    await api.post('/api/vinculos', { codigo, sku: s.sku, tamanho: s.tamanho }); setV(v + 1); onChange()
  }
  const remover = async (codigo) => { await api.del(`/api/vinculos/${encodeURIComponent(codigo)}`); setV(v + 1); onChange() }
  const buscarSku = async (t) => setSug(t.length >= 2 ? await api.get('/api/skus', { busca: t }) : [])
  if (error) return <ErrorBox error={error} />
  return (
    <>
      <p style={{ marginTop: 0, color: 'var(--ink-2)' }}>Códigos de estoque que não correspondem a nenhum SKU vendido entram como produtos próprios.
        Se um deles for uma variação (tamanho) de um SKU vendido, vincule aqui: o estoque passa a contar para aquele SKU.</p>
      <datalist id="skus">{sug.map((s) => <option key={s} value={s} />)}</datalist>
      <input type="search" placeholder="Filtrar códigos" value={busca} onChange={(e) => setBusca(e.target.value)} style={{ minWidth: 240, marginBottom: 10 }} />
      {!data ? <Loading /> : (
        <>
          <p className="p-sub">{n0(data.total)} códigos · {n0(data.quantidade)} unidades</p>
          <div className="tscroll"><table className="dt">
            <thead><tr><th>Código no estoque</th><th>Depósitos</th><th className="r">Quantidade</th><th>Vincular ao SKU</th><th>Tamanho</th><th /></tr></thead>
            <tbody>{data.itens.slice(0, 60).map((i) => (
              <tr key={i.codigo}><td><b>{i.codigo}</b></td><td>{i.depositos.join(', ')}</td><td className="r">{n0(i.quantidade)}</td>
                <td><input type="text" list="skus" placeholder="SKU vendido" value={sel[i.codigo]?.sku || ''}
                  onChange={(e) => { setSel({ ...sel, [i.codigo]: { ...sel[i.codigo], sku: e.target.value } }); buscarSku(e.target.value) }} /></td>
                <td><input type="text" style={{ width: 70 }} value={sel[i.codigo]?.tamanho || ''} onChange={(e) => setSel({ ...sel, [i.codigo]: { ...sel[i.codigo], tamanho: e.target.value } })} /></td>
                <td><button className="btn" disabled={!sel[i.codigo]?.sku} onClick={() => salvar(i.codigo)}>Vincular</button></td></tr>))}</tbody>
          </table></div>
          {data.manuais.length > 0 && <>
            <h3 style={{ fontSize: 14, margin: '18px 0 6px' }}>Vínculos manuais</h3>
            <ul className="rows">{data.manuais.map((m) => (
              <li key={m.codigo}><div className="r-main"><b>{m.codigo}</b> → {m.sku}{m.tamanho ? ` (tam. ${m.tamanho})` : ''}</div>
                <div><button className="btn danger" onClick={() => remover(m.codigo)}>Remover</button></div></li>))}</ul>
          </>}
        </>
      )}
    </>
  )
}

export function Externo() {
  const { bump: onChange } = useCtx()
  return <ExternoInner onChange={onChange} />
}

function ExternoInner({ onChange }) {
  const [v, setV] = useState(0)
  const { data } = useApi('/api/estoque-externo', null, [v])
  const [novo, setNovo] = useState('')
  const [sug, setSug] = useState([])
  const salvar = async (skus) => { await api.put('/api/estoque-externo', { skus }); setV(v + 1); onChange() }
  if (!data) return <Loading />
  return (
    <>
      <p style={{ marginTop: 0, color: 'var(--ink-2)' }}>SKUs cujo estoque fica fora dos depósitos importados (por exemplo, no Full do Mercado Livre ou com o fornecedor).
        Eles continuam nas vendas, mas saem dos cálculos de ruptura, cobertura e vendas perdidas, para não aparecerem como zerados.</p>
      <datalist id="skus-ext">{sug.map((s) => <option key={s} value={s} />)}</datalist>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input type="text" list="skus-ext" placeholder="SKU (peça)" value={novo} onChange={async (e) => { setNovo(e.target.value); setSug(e.target.value.length >= 2 ? await api.get('/api/skus', { busca: e.target.value }) : []) }} />
        <button className="btn primary" disabled={!novo} onClick={() => { salvar([...data.map((d) => d.sku), novo]); setNovo('') }}>Adicionar</button>
      </div>
      {!data.length ? <Empty>Nenhum SKU marcado.</Empty> : (
        <ul className="rows">{data.map((d) => (
          <li key={d.sku}><div className="r-main"><b>{d.sku}</b><span>{d.descricao}</span></div>
            <div><button className="btn danger" onClick={() => salvar(data.filter((x) => x.sku !== d.sku).map((x) => x.sku))}>Remover</button></div></li>))}</ul>)}
    </>
  )
}

export function Qualidade() {
  const { data, error } = useApi('/api/qualidade')
  const regras = useApi('/api/regras')
  if (error) return <ErrorBox error={error} />
  if (!data) return <Loading />
  return (
    <>
      {!data.length && <Empty>Nenhuma inconsistência encontrada.</Empty>}
      {data.map((q, i) => (
        <div className="alert" key={i}><b>{q.titulo}</b>
          <ul className="msg-list">{q.itens.map((x, j) => <li key={j}>{x}</li>)}</ul></div>))}
      {regras.data && (
        <Box title="Regra de identificação dos produtos" className="mt">
          <p style={{ marginTop: 0 }}>{regras.data.produto}</p>
          <div className="tscroll"><table className="dt"><thead><tr><th>Código</th><th>Modelo</th><th>Cabedal</th><th>Cor</th><th>Tamanho</th><th>SKU canônico</th></tr></thead>
            <tbody>{Object.entries(regras.data.exemplo).map(([k, p]) => (
              <tr key={k}><td>{k}</td><td>{p.modelo}</td><td>{p.cabedal || 'não informado'}</td><td>{p.cor}</td><td>{p.tamanho}</td><td>{p.sku}</td></tr>))}</tbody></table></div>
        </Box>)}
      <ModelosPorCabedal />
    </>
  )
}


/** Modelos em que cada cabedal vira um modelo separado (ex.: 7208.101-29516 e 7208.101-31337). */
function ModelosPorCabedal() {
  const { bump } = useCtx()
  const [v, setV] = useState(0)
  const { data, error } = useApi('/api/modelos-por-cabedal', null, [v])
  const [novo, setNovo] = useState('')
  const [msg, setMsg] = useState(null)
  const salvar = async (modelos) => {
    setMsg(null)
    try { await api.put('/api/modelos-por-cabedal', { modelos }); setV(v + 1); bump() } catch (e) { setMsg(e.message) }
  }
  return (
    <Box title="Modelos separados por cabedal" className="mt"
      sub="Nesses modelos, cada cabedal é tratado como um modelo diferente em vendas, estoque, compras e pedidos. O SKU não muda.">
      {error ? <ErrorBox error={error} /> : !data ? <Loading /> : <>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
          <input type="text" placeholder="Modelo, ex.: 7208.101" value={novo} onChange={(e) => setNovo(e.target.value.trim())} aria-label="Modelo para separar por cabedal" />
          <button className="btn primary" disabled={!novo} onClick={() => { salvar([...data.modelos.map((m) => m.modelo), novo]); setNovo('') }}>Separar por cabedal</button>
        </div>
        {msg && <div className="alert err">{msg}</div>}
        {!data.modelos.length ? <Empty>Nenhum modelo separado por cabedal.</Empty> : (
          <ul className="rows">{data.modelos.map((m) => (
            <li key={m.modelo}><div className="r-main"><b>{m.modelo}</b>
              <span>{m.separados.length ? `vira ${m.separados.length} modelos: ${m.separados.join(', ')}` : 'sem vendas com cabedal informado'}</span></div>
              <div><button className="btn danger" onClick={() => salvar(data.modelos.filter((x) => x.modelo !== m.modelo).map((x) => x.modelo))}>Juntar de novo</button></div></li>))}</ul>)}
      </>}
    </Box>
  )
}

/** Diagnóstico: versão, banco e ambiente. Ajuda a entender por que uma importação não aparece. */
export function Sistema() {
  const { versao, go } = useCtx()
  const { data: d, error } = useApi('/api/sistema', null, [versao])
  if (error) return <ErrorBox error={error} />
  if (!d) return <Loading />
  const linha = (rot, val, ruim) => <tr><td style={{ color: 'var(--muted)', width: 260 }}>{rot}</td><td style={ruim ? { color: 'var(--critical-ink)', fontWeight: 600 } : undefined}>{val ?? '—'}</td></tr>
  const imp = (x) => (x ? `${x.arquivo || ''}${x.detalhe ? ' · ' + x.detalhe : ''} (importado em ${x.em ? x.em.replace('T', ' ') : '—'})` : 'nenhuma')
  return (
    <>
      {d.avisos.map((a, i) => <div key={i} className="alert bad">{a}</div>)}
      <Box title="Situação do sistema" sub="Se uma importação não aparece, confira aqui se você está no mesmo ambiente e banco em que importou.">
        <div className="tscroll"><table className="dt"><tbody>
          {linha('Versão do BI (servidor)', d.versao)}
          {linha('Versão da interface aberta', VERSAO_INTERFACE, VERSAO_INTERFACE !== d.versao)}
          {linha('Ambiente', d.ambiente)}
          {linha('Banco de dados', d.banco + (d.banco_persistente ? ' (guarda os dados entre publicações)' : ' (apagado ao republicar o app)'), !d.banco_persistente && d.ambiente !== 'Local')}
          {linha('Servidor iniciado em', dataBR(d.servidor_iniciado_em) + ' ' + d.servidor_iniciado_em.slice(11))}
          {linha('Importações registradas', n0(d.importacoes))}
          {linha('Listas de vendas do dia', d.lancamentos_diarios ? `${n0(d.lancamentos_diarios)} linhas, de ${dataBR(d.listas_dia_de)} a ${dataBR(d.listas_dia_ate)}` : 'nenhuma importada neste banco', !d.lancamentos_diarios)}
          {linha('Última lista do dia', imp(d.ultima_lista_dia))}
          {linha('Último relatório mensal de vendas', imp(d.ultimo_relatorio_mensal) + (d.ultimo_relatorio_mensal?.data_referencia ? ` · cobre até ${dataBR(d.ultimo_relatorio_mensal.data_referencia)}` : ''))}
          {linha('Último estoque', imp(d.ultimo_estoque))}
        </tbody></table></div>
        <div style={{ display: 'flex', gap: 10, marginTop: 14, flexWrap: 'wrap' }}>
          <button className="btn" onClick={() => go('/dados/importar')}>Importar arquivos</button>
          <button className="btn ghost" onClick={() => go('/dados/historico')}>Histórico de importações</button>
        </div>
      </Box>
      <Box title="De onde vem cada dado" className="mt" sub="O objetivo é usar o mínimo de planilha: o que já tem API é atualizado sozinho." flush="b">
        <div className="tscroll"><table className="dt"><thead><tr><th>Dado</th><th>Origem hoje</th><th>Detalhe</th><th>API disponível</th></tr></thead>
          <tbody>{(d.fontes || []).map((x) => (
            <tr key={x.dado}><td><b>{x.dado}</b></td>
              <td style={{ color: x.ok === false ? 'var(--critical-ink)' : x.ok ? 'var(--good-ink)' : undefined, fontWeight: 600 }}>{x.origem}</td>
              <td>{x.detalhe}</td><td style={{ color: 'var(--ink-2)' }}>{x.api}</td></tr>))}</tbody></table></div>
      </Box>
      <Box title="Como manter os dados no Replit" className="mt">
        <ul className="msg-list" style={{ marginTop: 0 }}>
          <li><b>Use o PostgreSQL.</b> No Replit, abra a aba Database e crie o banco; o BI passa a usá-lo sozinho (variável DATABASE_URL). Sem ele, os dados ficam num arquivo que é apagado ao republicar.</li>
          <li><b>Importe onde você consulta.</b> O Repl de desenvolvimento (botão Run) e o app publicado podem ter bancos diferentes: importe sempre pelo mesmo endereço que você usa para ver o BI.</li>
          <li><b>Depois de enviar uma versão nova,</b> rode o Repl (ou republique) e recarregue a página com Ctrl+F5. A versão da interface e a do servidor devem ser iguais na tabela acima.</li>
        </ul>
      </Box>
    </>
  )
}

/** Marcar produtos (modelos) como em linha ou fora de linha, um a um ou vários de uma vez. */
export function ProdutosLinha() {
  const { versao, openProduto } = useCtx()
  const st = useApi('/api/linha/produtos', null, [versao])
  const [busca, setBusca] = useState('')
  const [estado, setEstado] = useState('')
  const [cat, setCat] = useState('calcado')
  const [pag, setPag] = useState(0)
  if (st.error) return <ErrorBox error={st.error} />
  if (!st.data) return <Loading />
  const t = busca.trim().toLowerCase()
  const lista = st.data.itens.filter((x) => (!estado || x.estado === estado) && (cat === 'todos' || x.categoria === cat)
    && (!t || x.chave.toLowerCase().includes(t) || (x.descricao || '').toLowerCase().includes(t)))
  const POR = 40
  const pagina = lista.slice(pag * POR, pag * POR + POR)
  const c = st.data.contagem
  return (
    <>
      <div className="strip" style={{ marginBottom: 16 }}>
        <span><b>{n0(c.em_linha)}</b> em linha</span><span><b>{n0(c.fora)}</b> fora de linha</span><span><b>{n0(c.sem_marcacao)}</b> sem marcação</span>
        <span style={{ color: 'var(--muted)' }}>Use o seletor “Linha” no topo de qualquer tela para ver só um grupo. A marcação também pode ser feita na ficha de qualquer produto.</span>
      </div>
      <Box title="Produtos em linha" sub="Marcação por modelo (calçados) ou pelo código (outros produtos). Ordenado pelo que mais vendeu nos últimos 3 meses." flush="b">
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', padding: '0 18px 12px' }}>
          <input type="search" placeholder="Buscar código ou descrição" value={busca} onChange={(e) => { setBusca(e.target.value); setPag(0) }} aria-label="Buscar produto" style={{ width: 260 }} />
          <select value={estado} onChange={(e) => { setEstado(e.target.value); setPag(0) }} aria-label="Situação">
            <option value="">Todas as situações</option>{ESTADOS.map(([v, tx]) => <option key={v} value={v}>{tx}</option>)}
          </select>
          <select value={cat} onChange={(e) => { setCat(e.target.value); setPag(0) }} aria-label="Categoria">
            <option value="calcado">Calçados</option><option value="outro">Outros produtos</option><option value="todos">Todos</option>
          </select>
          <span style={{ color: 'var(--muted)', fontSize: 13 }}>{n0(lista.length)} produtos</span>
          {lista.length > 0 && lista.length <= 1000 && (
            <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>Marcar os {n0(lista.length)} listados:</span>
              <MarcarLinha rotulo={false} chaves={lista.map((x) => x.chave)} atual={null} />
            </span>
          )}
        </div>
        <div className="tscroll"><table className="dt">
          <thead><tr><th>Produto</th><th className="r">Vendeu (3 meses)</th><th className="r">Estoque</th><th>Última venda</th><th>Última compra</th><th>Linha</th></tr></thead>
          <tbody>{pagina.map((x) => (
            <tr key={x.chave}>
              <td><button className="link" onClick={() => openProduto(x.categoria === 'calcado' ? 'modelo' : 'sku', x.chave)}>{x.chave}</button><span className="d">{x.descricao}</span></td>
              <td className="r">{n0(x.vendas_3m)}</td><td className={'r ' + (x.estoque <= 0 ? 'z' : '')}>{n0(x.estoque)}</td>
              <td>{x.ultima_venda ? x.ultima_venda.split('-').reverse().join('/') : '—'}</td><td>{x.ultima_compra ? dataBR(x.ultima_compra) : '—'}</td>
              <td><MarcarLinha rotulo={false} chaves={[x.chave]} atual={x.estado} /></td>
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
}

const pad = (n) => String(n).padStart(2, '0')
const ultimoDia = (a, m) => new Date(a, m, 0).getDate()
/** Faixa de uma semana do mês: 1 = 1–7, 2 = 8–14, 3 = 15–21, 4 = 22–28, 5 = 29 ao fim. */
export function faixaSemana(mes, n) {
  const [a, m] = mes.split('-').map(Number)
  const ini = (n - 1) * 7 + 1
  const fim = n === 5 ? ultimoDia(a, m) : ini + 6
  return [`${mes}-${pad(ini)}`, `${mes}-${pad(fim)}`]
}

/** Atalho: escolher o mês e a semana preenche o período da planilha. */
function SeletorSemana({ params, onEscolher, disabled }) {
  const hoje = new Date()
  const meses = [0, 1, 2, 3].map((k) => { const d = new Date(hoje.getFullYear(), hoje.getMonth() - k, 1); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}` })
  const atual = (params.periodo_inicio || '').slice(0, 7)
  const [mes, setMes] = useState(meses.includes(atual) ? atual : meses[0])
  const sel = [1, 2, 3, 4, 5].find((n) => { const [a, b] = faixaSemana(mes, n); return params.periodo_inicio === a && params.periodo_fim === b })
  return (
    <span style={{ display: 'inline-flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      <select value={mes} onChange={(e) => setMes(e.target.value)} disabled={disabled} aria-label="Mês da semana">
        {meses.map((m) => <option key={m} value={m}>{m.split('-').reverse().join('/')}</option>)}
      </select>
      <span className="seg" role="group" aria-label="Semana">
        {[1, 2, 3, 4, 5].map((n) => { const [a, b] = faixaSemana(mes, n); return (
          <button key={n} type="button" disabled={disabled} aria-pressed={sel === n} title={`${a.slice(8)}/${a.slice(5, 7)} a ${b.slice(8)}/${b.slice(5, 7)}`} onClick={() => onEscolher(a, b)}>Semana {n}</button>) })}
      </span>
    </span>
  )
}

/** Vendas por semana: a partir de qual mês valem só as planilhas semanais, e quais semanas já foram enviadas. */
function VendasSemanais() {
  const { versao, bump, meta } = useCtx()
  const { data, error } = useApi('/api/vendas/semanal', null, [versao])
  const [erro, setErro] = useState(null)
  if (error || !data) return null
  const salvar = async (desde) => { setErro(null); try { await api.put('/api/vendas/semanal', { desde: desde || null }); bump() } catch (e) { setErro(e.message) } }
  const hoje = new Date()
  const opcoes = [0, 1, 2, 3, 4, 5].map((k) => { const d = new Date(hoje.getFullYear(), hoje.getMonth() - k, 1); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}` })
  return (
    <Box title="Vendas por semana" className="mb"
      sub="A partir do mês escolhido, as vendas vêm só das planilhas semanais (uma por semana e por canal); o relatório mensal desses meses deixa de valer, mas não é apagado.">
      {erro && <div className="alert bad">{erro}</div>}
      <div className="formrow"><label htmlFor="sem-desde">Vendas por semana a partir de</label>
        <select id="sem-desde" value={data.desde || ''} onChange={(e) => salvar(e.target.value)}>
          <option value="">Desligado (vale o relatório mensal)</option>
          {opcoes.map((m) => <option key={m} value={m}>{m.split('-').reverse().join('/')}</option>)}
        </select></div>
      {data.desde && (
        <>
          <p className="note" style={{ margin: '6px 0 10px' }}>Semanas já enviadas (dias com planilha de cada canal). Verde = semana completa nos dois canais.</p>
          {data.importadas.filter((m) => m.mes >= data.desde).map((m) => (
            <div key={m.mes} style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>{m.rotulo}</div>
              <div className="sem-grid">
                {m.semanas.map((x) => {
                  const ok = x.ml >= x.dias && x.shopee >= x.dias
                  const parte = !ok && (x.ml || x.shopee || x.sem_canal)
                  return (
                    <div key={x.semana} className={ok ? 'ok' : parte ? 'parte' : ''}>
                      <b>Semana {x.semana}</b> <span style={{ color: 'var(--muted)' }}>{x.periodo}{x.em_andamento ? ' (em andamento)' : ''}</span><br />
                      ML {x.ml ? `${x.ml}/${x.dias} d` : '—'} · Shopee {x.shopee ? `${x.shopee}/${x.dias} d` : '—'}{x.sem_canal ? ` · sem canal ${x.sem_canal} d` : ''}
                    </div>)
                })}
              </div>
            </div>))}
        </>
      )}
    </Box>
  )
}
