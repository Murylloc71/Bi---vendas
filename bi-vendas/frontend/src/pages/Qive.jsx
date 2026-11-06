import { useEffect, useState } from 'react'
import { api } from '../api'
import { useCtx } from '../ctx'
import { n0 } from '../fmt'
import { Box, Stat, Stats } from '../ui'

/** Compras pela API do Qive (NF-e recebidas), no lugar das planilhas de compras. */
export default function Qive() {
  const { bump } = useCtx()
  const [st, setSt] = useState(null)
  const [msg, setMsg] = useState(null)
  const [cred, setCred] = useState({ api_id: '', api_key: '' })
  const [desde, setDesde] = useState('')
  const [forn, setForn] = useState('')
  const carregar = () => api.get('/api/qive').then((s) => { setSt(s); setDesde(s.desde); setForn(s.fornecedores) }, (e) => setMsg({ bad: true, t: e.message }))
  useEffect(() => { carregar() }, [])
  useEffect(() => {
    if (!st?.rodando) return undefined
    const t = setInterval(() => api.get('/api/qive').then((s) => {
      setSt(s)
      if (!s.rodando) { bump(); setMsg(s.erro ? { bad: true, t: 'Qive: ' + s.erro } : { t: `Compras atualizadas: ${n0(s.ultima?.notas_novas)} notas novas, ${n0(s.ultima?.pares)} pares.` }) }
    }), 2000)
    return () => clearInterval(t)
  }, [st?.rodando])
  const acao = async (fn, ok) => { setMsg(null); try { const r = await fn(); setSt(r); if (ok) setMsg({ t: typeof ok === 'function' ? ok(r) : ok }) } catch (e) { setMsg({ bad: true, t: e.message }) } }
  if (!st) return <div className="skel" style={{ height: 300 }} />
  const u = st.ultima
  return (
    <>
      <p className="lead">As compras vêm das NF-e recebidas no Qive (todos os CNPJs Uai Comprei, sem transferências entre as empresas). Cada item vira uma linha de compras com SKU, quantidade, preço e pronta-entrega/programado, pela mesma regra da planilha. Atualiza ao iniciar o servidor e a cada {st.horas || 6} horas (variável <code>QIVE_SYNC_HORAS</code>).</p>
      {msg && <div className={`alert ${msg.bad ? 'bad' : 'ok'}`} role="status">{msg.t}</div>}
      <Stats>
        <Stat label="Conexão" value={st.configurado ? 'Configurada' : 'Não configurada'} tone={st.configurado ? '' : 'alarm'}
          sub={st.configurado ? `API ID terminado em ${st.api_id_final} · ${st.origem === 'ambiente' ? 'Secrets' : 'salvo no banco'}` : 'informe as credenciais abaixo'} />
        <Stat label="Compras vindas do Qive" value={n0(st.linhas)} sub={st.linhas ? `itens de nota de ${st.de?.split('-').reverse().join('/')} a ${st.ate?.split('-').reverse().join('/')}` : 'nenhuma ainda'} />
        <Stat label="Última sincronização" value={<span style={{ fontSize: 18 }}>{u ? u.quando.split(' ')[0].split('-').reverse().join('/') + ' ' + u.quando.split(' ')[1] : '—'}</span>}
          sub={u ? `${n0(u.notas_novas)} notas novas · ${n0(u.pares)} pares` : (st.rodando ? st.progresso : 'ainda não sincronizado')} />
      </Stats>
      <div className="row c2">
        <Box title="Ações">
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button className="btn primary" disabled={!st.configurado || st.rodando} onClick={() => acao(() => api.post('/api/qive/sincronizar'))}>{st.rodando ? 'Sincronizando…' : 'Sincronizar agora'}</button>
            <button className="btn" disabled={!st.configurado} onClick={() => acao(() => api.post('/api/qive/testar'), (r) => `Conexão funcionando: ${n0(r.notas_na_primeira_pagina)} notas na primeira página.`)}>Testar conexão</button>
          </div>
          {u?.ignoradas && Object.keys(u.ignoradas).length > 0 && (
            <ul className="msgs" style={{ marginTop: 14 }}>{Object.entries(u.ignoradas).map(([k, v]) => <li key={k}>Ignoradas ({k}): <b>{n0(v)}</b></li>)}</ul>)}
          {st.erro && <p className="note" style={{ color: 'var(--critical-ink)' }}>Último erro ({st.erro.quando}): {st.erro.msg}</p>}
          <h3 style={{ fontSize: 14, margin: '16px 0 6px' }}>O que entra</h3>
          <div className="formrow"><label htmlFor="qd">Notas emitidas a partir de</label><input id="qd" type="date" value={desde} onChange={(e) => setDesde(e.target.value)} /></div>
          <div className="formrow"><label htmlFor="qf">Só destes fornecedores</label><input id="qf" type="text" placeholder="vazio = todos (ex.: Beira Rio)" value={forn} onChange={(e) => setForn(e.target.value)} /></div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
            <button className="btn" onClick={() => acao(() => api.put('/api/qive', { desde, fornecedores: forn }), 'Salvo. Vale para as próximas notas lidas.')}>Salvar</button>
            <button className="btn ghost" onClick={() => acao(() => api.put('/api/qive', { desde, fornecedores: forn, recomecar: true }), 'Na próxima sincronização o BI relê o Qive desde o começo (notas já gravadas não duplicam).')}>Reler desde o começo</button>
          </div>
          <p className="note">Notas iguais às das planilhas de compras (mesma data e valor total) contam uma vez só, pela do Qive.</p>
        </Box>
        <Box title="Credenciais" sub="No Replit, prefira Secrets: QIVE_API_ID e QIVE_API_KEY">
          {st.origem === 'ambiente' ? <p style={{ margin: 0 }}>As credenciais vêm dos Secrets do servidor. Para trocar, altere os Secrets e reinicie.</p> : (
            <>
              <div className="formrow"><label htmlFor="qi">API ID</label><input id="qi" type="text" autoComplete="off" value={cred.api_id} onChange={(e) => setCred({ ...cred, api_id: e.target.value })} /></div>
              <div className="formrow"><label htmlFor="qk">API Key</label><input id="qk" type="password" autoComplete="off" value={cred.api_key} onChange={(e) => setCred({ ...cred, api_key: e.target.value })} /></div>
              <div style={{ marginTop: 10 }}><button className="btn" disabled={!cred.api_id || !cred.api_key} onClick={() => acao(async () => { const r = await api.put('/api/qive', cred); setCred({ api_id: '', api_key: '' }); return r }, 'Credenciais salvas.')}>Salvar credenciais</button></div>
              <p className="note">Salvas no banco do BI; Secrets é a opção recomendada. Endereço da API: {st.base} (variável QIVE_API_URL).</p>
            </>
          )}
        </Box>
      </div>
    </>
  )
}
