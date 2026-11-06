import { useEffect, useState } from 'react'
import { api } from '../api'
import { useCtx } from '../ctx'
import { n0 } from '../fmt'
import { Box, Stat, Stats } from '../ui'

const ROT = { pendente: 'Pendentes', faturado: 'Faturados', recebido: 'Recebidos', faturado_parcial: 'Faturados parcialmente',
  recebido_parcial: 'Recebidos parcialmente', encerrado: 'Encerrados', cancelado: 'Cancelados' }

export default function Omie() {
  const { bump } = useCtx()
  const [st, setSt] = useState(null)
  const [msg, setMsg] = useState(null)
  const [cred, setCred] = useState({ app_key: '', app_secret: '' })
  const carregar = () => api.get('/api/omie/status').then(setSt, (e) => setMsg({ bad: true, t: e.message }))
  useEffect(() => { carregar() }, [])
  useEffect(() => {
    if (!st?.rodando) return undefined
    const t = setInterval(() => api.get('/api/omie/status').then((s) => { setSt(s); if (!s.rodando) { bump(); setMsg(s.erro ? { bad: true, t: 'A sincronização falhou: ' + s.erro } : { t: 'Sincronização concluída. Os indicadores já usam os pedidos atualizados.' }) } }), 2000)
    return () => clearInterval(t)
  }, [st?.rodando])
  const testar = async () => { setMsg(null); try { const r = await api.post('/api/omie/testar'); setMsg({ t: `Conexão funcionando: ${n0(r.pedidos_pendentes)} pedidos pendentes no Omie.` }) } catch (e) { setMsg({ bad: true, t: e.message }) } }
  const sincronizar = async () => { setMsg(null); try { setSt(await api.post('/api/omie/sincronizar')) } catch (e) { setMsg({ bad: true, t: e.message }) } }
  const salvar = async () => { try { setSt(await api.post('/api/omie/credenciais', cred)); setCred({ app_key: '', app_secret: '' }); setMsg({ t: 'Credenciais salvas.' }) } catch (e) { setMsg({ bad: true, t: e.message }) } }
  if (!st) return <div className="skel" style={{ height: 300 }} />
  const u = st.ultima_sync
  return (
    <>
      <AgendaOmie />
      <EstoqueOmie />
      <h2 style={{ fontSize: 16, margin: '24px 0 8px' }}>Pedidos de compra</h2>
      <p className="lead">Os pedidos de compra vêm do Omie (serviço PedidoCompra). A sincronização baixa todos os pedidos, de todos os status, com itens, grade e parcelas, e substitui a cópia local. Ela roda todo dia no horário da sincronização automática acima.</p>
      {msg && <div className={`alert ${msg.bad ? 'bad' : 'ok'}`} role="status">{msg.t}</div>}
      <Stats>
        <Stat label="Conexão" value={st.configurado ? 'Configurada' : 'Não configurada'} tone={st.configurado ? '' : 'alarm'}
          sub={st.configurado ? `chave terminada em ${st.app_key_final} · ${st.origem_credenciais === 'ambiente' ? 'variáveis de ambiente' : 'salva no banco'}` : 'informe as credenciais abaixo'} />
        <Stat label="Última sincronização" value={u ? <span style={{ fontSize: 18 }}>{new Date(u.quando + 'Z').toLocaleString('pt-BR')}</span> : '—'} sub={u ? `${n0(u.pedidos)} pedidos, ${n0(u.itens)} itens` : 'ainda não sincronizado'} />
        <Stat label="Agora" value={<span style={{ fontSize: 18 }}>{st.rodando ? 'Sincronizando…' : 'Parado'}</span>} sub={st.progresso || ''} />
      </Stats>
      <div className="row c2">
        <Box title="Ações">
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button className="btn primary" disabled={!st.configurado || st.rodando} onClick={sincronizar}>{st.rodando ? 'Sincronizando…' : 'Sincronizar agora'}</button>
            <button className="btn" disabled={!st.configurado} onClick={testar}>Testar conexão</button>
          </div>
          {u && <ul className="msgs" style={{ marginTop: 14 }}>{Object.entries(u.por_status).filter(([, v]) => v).map(([k, v]) => <li key={k}>{ROT[k] || k}: <b>{n0(v)}</b></li>)}</ul>}
        </Box>
        <Box title="Credenciais" sub="No Replit, prefira Secrets: OMIE_APP_KEY e OMIE_APP_SECRET">
          {st.origem_credenciais === 'ambiente' ? <p style={{ margin: 0 }}>As credenciais vêm das variáveis de ambiente do servidor. Para trocar, altere os Secrets e reinicie.</p> : (
            <>
              <div className="formrow"><label htmlFor="ok">App key</label><input id="ok" type="text" autoComplete="off" value={cred.app_key} onChange={(e) => setCred({ ...cred, app_key: e.target.value })} /></div>
              <div className="formrow"><label htmlFor="os">App secret</label><input id="os" type="password" autoComplete="off" value={cred.app_secret} onChange={(e) => setCred({ ...cred, app_secret: e.target.value })} /></div>
              <div style={{ marginTop: 10 }}><button className="btn" disabled={!cred.app_key || !cred.app_secret} onClick={salvar}>Salvar credenciais</button></div>
              <p className="note">Salvas no banco do BI. Qualquer pessoa com acesso ao servidor consegue lê-las; por isso Secrets é a opção recomendada.</p>
            </>
          )}
        </Box>
      </div>
    </>
  )
}

/** Estoque pelo Omie: local Geral do Omie 03 (Unlock) e do Omie 04 (Juatuba), no lugar das planilhas. */
function EstoqueOmie() {
  const { bump } = useCtx()
  const [st, setSt] = useState(null)
  const [msg, setMsg] = useState(null)
  const [cred, setCred] = useState({})
  const carregar = () => api.get('/api/omie/estoque').then(setSt, (e) => setMsg({ bad: true, t: e.message }))
  useEffect(() => { carregar() }, [])
  useEffect(() => {
    if (!st?.rodando) return undefined
    const t = setInterval(() => api.get('/api/omie/estoque').then((s) => {
      setSt(s)
      if (!s.rodando) { bump(); setMsg(s.erro ? { bad: true, t: 'Estoque: ' + s.erro } : { t: 'Estoque atualizado. Os indicadores já usam a posição de hoje.' }) }
    }), 2000)
    return () => clearInterval(t)
  }, [st?.rodando])
  const acao = async (fn, ok) => { setMsg(null); try { const r = await fn(); setSt(r); if (ok) setMsg({ t: typeof ok === 'function' ? ok(r) : ok }) } catch (e) { setMsg({ bad: true, t: e.message }) } }
  if (!st) return <div className="skel" style={{ height: 240 }} />
  const algum = st.contas.some((c) => c.configurado)
  return (
    <Box title="Estoque pelo Omie" sub={`Unlock = local Geral do Omie 03 · Juatuba = local Geral do Omie 04. Atualiza junto com os pedidos, no horário da sincronização automática acima; cada atualização vira a foto de estoque do dia.`}
      right={<button className="btn primary" disabled={!algum || st.rodando} onClick={() => acao(() => api.post('/api/omie/estoque/sincronizar'))}>{st.rodando ? 'Atualizando…' : 'Atualizar estoque agora'}</button>}>
      {msg && <div className={`alert ${msg.bad ? 'bad' : 'ok'}`} role="status">{msg.t}</div>}
      {st.rodando && <p className="note">{st.progresso}</p>}
      <div className="row c2" style={{ marginBottom: 0 }}>
        {st.contas.map((c) => {
          const cr = cred[c.id] || { app_key: '', app_secret: '' }
          const u = c.ultima
          return (
            <div key={c.id} style={{ border: '1px solid var(--line)', borderRadius: 'var(--r)', padding: 14 }}>
              <h3 style={{ margin: '0 0 2px', fontSize: 15 }}>{c.deposito} <span style={{ color: 'var(--muted)', fontWeight: 400 }}>· Omie {c.id}</span></h3>
              <p style={{ margin: '0 0 10px', fontSize: 12.5, color: 'var(--muted)' }}>{c.empresa}</p>
              <table className="dt"><tbody>
                <tr><td style={{ color: 'var(--muted)', width: 150 }}>Conexão</td><td style={!c.configurado ? { color: 'var(--critical-ink)', fontWeight: 600 } : undefined}>
                  {c.configurado ? `chave terminada em ${c.app_key_final} (${c.origem === 'ambiente' ? 'Secrets' : 'salva no banco'})` : 'não configurada'}</td></tr>
                <tr><td style={{ color: 'var(--muted)' }}>Local de estoque</td><td>{c.local ? c.local.descricao : 'procurado na 1ª atualização (Geral)'}</td></tr>
                <tr><td style={{ color: 'var(--muted)' }}>Última atualização</td><td>{u ? `${u.quando.split(' ')[0].split('-').reverse().join('/')} ${u.quando.split(' ')[1]} · ${n0(u.codigos)} códigos, ${n0(u.unidades)} un.` : '—'}</td></tr>
                {u?.sem_vinculo > 0 && <tr><td style={{ color: 'var(--muted)' }}>Sem vínculo</td><td>{n0(u.sem_vinculo)} códigos (ligue em Dados › Vínculos de estoque)</td></tr>}
                {c.erro && <tr><td style={{ color: 'var(--muted)' }}>Último erro</td><td style={{ color: 'var(--critical-ink)' }}>{c.erro.msg}</td></tr>}
              </tbody></table>
              <div className="formrow" style={{ marginTop: 10 }}><label htmlFor={`campo${c.id}`}>Quantidade</label>
                <select id={`campo${c.id}`} value={c.campo} onChange={(e) => acao(() => api.put(`/api/omie/estoque/${c.id}`, { campo: e.target.value }), 'Vale a partir da próxima atualização.')}>
                  {Object.entries(st.campos).map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                </select></div>
              {c.origem !== 'ambiente' && (
                <>
                  <div className="formrow"><label htmlFor={`k${c.id}`}>App key</label><input id={`k${c.id}`} type="text" autoComplete="off" value={cr.app_key} onChange={(e) => setCred({ ...cred, [c.id]: { ...cr, app_key: e.target.value } })} /></div>
                  <div className="formrow"><label htmlFor={`s${c.id}`}>App secret</label><input id={`s${c.id}`} type="password" autoComplete="off" value={cr.app_secret} onChange={(e) => setCred({ ...cred, [c.id]: { ...cr, app_secret: e.target.value } })} /></div>
                </>
              )}
              <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
                {c.origem !== 'ambiente' && <button className="btn" disabled={!cr.app_key || !cr.app_secret} onClick={() => acao(async () => { const r = await api.put(`/api/omie/estoque/${c.id}`, cr); setCred({ ...cred, [c.id]: { app_key: '', app_secret: '' } }); return r }, 'Credenciais salvas.')}>Salvar credenciais</button>}
                <button className="btn ghost" disabled={!c.configurado} onClick={() => acao(() => api.post(`/api/omie/estoque/${c.id}/testar`), (r) => `Conexão funcionando. Local usado: ${r.local.descricao} (locais no Omie ${c.id}: ${r.local.locais.join(', ')}).`)}>Testar conexão</button>
              </div>
              <p className="note" style={{ marginBottom: 0 }}>No Replit, prefira os Secrets <code>{c.secrets}</code>.</p>
            </div>
          )
        })}
      </div>
    </Box>
  )
}

/** Horário da sincronização automática com o Omie (pedidos + estoque). */
function AgendaOmie() {
  const [st, setSt] = useState(null)
  const [txt, setTxt] = useState('')
  const [msg, setMsg] = useState(null)
  useEffect(() => { api.get('/api/omie/agenda').then((s) => { setSt(s); setTxt(s.horarios.join(', ')) }, () => {}) }, [])
  if (!st) return null
  const fmt = (x) => (x ? `${x.slice(8, 10)}/${x.slice(5, 7)} às ${x.slice(11)}` : '—')
  const salvar = async () => {
    setMsg(null)
    try { const s = await api.put('/api/omie/agenda', { horarios: txt }); setSt(s); setTxt(s.horarios.join(', ')); setMsg({ t: 'Horário salvo.' }) } catch (e) { setMsg({ bad: true, t: e.message }) }
  }
  return (
    <Box title="Sincronização automática com o Omie" className="mb"
      sub={`Pedidos de compra e estoque (Omie 03 e 04) são atualizados todo dia às ${st.horarios.join(' e ')} (horário de Brasília). Se o servidor estiver fora do ar no horário, atualiza assim que voltar.`}>
      {msg && <div className={`alert ${msg.bad ? 'bad' : 'ok'}`} role="status">{msg.t}</div>}
      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div><div style={{ fontSize: 12, color: 'var(--muted)' }}>Última</div><b>{fmt(st.ultima)}</b></div>
        <div><div style={{ fontSize: 12, color: 'var(--muted)' }}>Próxima</div><b>{fmt(st.proxima)}</b></div>
        {st.fixo_por_variavel ? <p className="note" style={{ margin: 0 }}>Horário definido pela variável OMIE_HORARIOS no servidor.</p> : (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <label htmlFor="omie-h" style={{ fontSize: 13 }}>Todo dia às</label>
            <input id="omie-h" type="text" value={txt} onChange={(e) => setTxt(e.target.value)} style={{ width: 130 }} placeholder="12:00" aria-describedby="omie-h-dica" />
            <button className="btn" onClick={salvar}>Salvar</button>
            <span id="omie-h-dica" style={{ fontSize: 12, color: 'var(--muted)' }}>vários horários: 07:00, 12:00</span>
          </div>)}
      </div>
      {st.erros?.length > 0 && <p className="note" style={{ color: 'var(--critical-ink)' }}>Última rodada: {st.erros.join('; ')}</p>}
    </Box>
  )
}
