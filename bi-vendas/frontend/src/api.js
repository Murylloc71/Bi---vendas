const base = import.meta.env.VITE_API_URL || ''

// Filtro global (produtos em linha / fora de linha): vai em todas as consultas.
let global = {}
export const setFiltroGlobal = (g) => { global = { ...g } }
export const filtroGlobal = () => global
const comGlobal = (params) => ({ ...(params || {}), ...Object.fromEntries(Object.entries(global).filter(([, v]) => v)) })

async function req(path, opts = {}) {
  const r = await fetch(base + path, { credentials: 'same-origin', ...opts })
  let body = null
  try { body = await r.json() } catch { /* sem corpo */ }
  // sessão expirada ou sem login: avisa o App para mostrar a tela de login
  if (r.status === 401 && path !== '/api/login') window.dispatchEvent(new Event('bi:login'))
  if (!r.ok) throw new Error((body && body.detail) || `Erro ${r.status}`)
  return body
}

export const api = {
  get: (path, params) => {
    const p = comGlobal(params)
    const q = Object.keys(p).length ? '?' + new URLSearchParams(Object.entries(p).filter(([, v]) => v !== undefined && v !== null && v !== '')) : ''
    return req(path + q)
  },
  post: (path, body) => req(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }),
  put: (path, body) => req(path, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }),
  del: (path) => req(path, { method: 'DELETE' }),
  upload: (path, form) => req(path, { method: 'POST', body: form }),
}

/** URL completa de um endpoint (para links de download). */
export const urlApi = (path, params) => { const p = comGlobal(params); return base + path + (Object.keys(p).length ? '?' + new URLSearchParams(Object.entries(p).filter(([, v]) => v !== undefined && v !== null && v !== '')) : '') }
