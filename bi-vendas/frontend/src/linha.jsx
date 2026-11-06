import { useState } from 'react'
import { api } from './api'
import { useCtx } from './ctx'
import { useApi } from './ui'

export const ESTADOS = [['em_linha', 'Em linha'], ['fora', 'Fora de linha'], ['sem_marcacao', 'Sem marcação']]

/** Marcações atuais: chave do modelo -> true (em linha) / false (fora de linha). */
export function useMarcas() {
  const { versao } = useCtx()
  return useApi('/api/linha', null, [versao]).data?.marcas || {}
}

export const estadoDe = (marcas, chave) => (marcas[chave] === true ? 'em_linha' : marcas[chave] === false ? 'fora' : 'sem_marcacao')

/** Etiqueta pequena ao lado do código (só aparece se o produto estiver marcado). */
export function TagLinha({ marcas, chave }) {
  const e = estadoDe(marcas, chave)
  if (e === 'sem_marcacao') return null
  return <span className={`tag-linha ${e}`}>{e === 'em_linha' ? 'em linha' : 'fora de linha'}</span>
}

/** Botões Em linha / Fora de linha / Sem marcação para um produto (ou vários). */
export function MarcarLinha({ chaves, atual, onMudou, rotulo = true }) {
  const { bump } = useCtx()
  const [busy, setBusy] = useState(false)
  const [erro, setErro] = useState(null)
  const definir = async (e) => {
    if (e === atual) return
    setBusy(true); setErro(null)
    try {
      await api.put('/api/linha', { chaves, em_linha: e === 'em_linha' ? true : e === 'fora' ? false : null })
      onMudou?.(e); bump()
    } catch (x) { setErro(x.message) } finally { setBusy(false) }
  }
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      {rotulo && <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>Linha:</span>}
      <span className="linha-seg" role="group" aria-label="Produto em linha">
        {ESTADOS.map(([v, t]) => (
          <button key={v} type="button" className={v} aria-pressed={atual === v} disabled={busy} onClick={() => definir(v)}>{t}</button>))}
      </span>
      {erro && <span style={{ color: 'var(--critical-ink)', fontSize: 12.5 }}>{erro}</span>}
    </span>
  )
}
