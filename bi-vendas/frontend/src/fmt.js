const nf0 = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1, minimumFractionDigits: 0 })
const brl = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 })
const brl2 = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 2, maximumFractionDigits: 2 })

export const isNum = (v) => v !== null && v !== undefined && !Number.isNaN(v)
export const n0 = (v) => (isNum(v) ? nf0.format(v) : '—')
export const n1 = (v) => (isNum(v) ? nf1.format(v) : '—')
export const money = (v) => (isNum(v) ? brl.format(v) : '—')
export const money2 = (v) => (isNum(v) ? brl2.format(v) : '—')
export const compact = (v) => {
  if (!isNum(v)) return '—'
  const a = Math.abs(v)
  if (a >= 1e6) return nf1.format(v / 1e6) + ' mi'
  if (a >= 1e3) return nf1.format(v / 1e3) + ' mil'
  return nf0.format(v)
}
export const moneyCompact = (v) => (isNum(v) ? 'R$ ' + compact(v) : '—')
export const pct = (v, digits = 1) => (isNum(v) ? (v > 0 ? '+' : '') + v.toFixed(digits).replace('.', ',') + '%' : '—')
export const dataBR = (iso) => (iso ? iso.slice(0, 10).split('-').reverse().join('/') : '—')

export const STATUS = {
  ruptura: 'Ruptura', critico: 'Crítico', ok: 'Saudável', excesso: 'Excesso', sem_giro: 'Sem giro',
  inativo: 'Sem venda', sem_cadastro: 'Sem código no estoque', externo: 'Estoque externo',
}
export const STATUS_REPO = {
  ruptura_sem_pedido: 'Zerado, sem pedido', ruptura_com_pedido: 'Zerado, pedido a caminho', critico_sem_pedido: 'Acabando, sem pedido',
  pedido_chega_tarde: 'Pedido chega depois', coberto: 'Acabando, pedido cobre', ok: 'Saudável', excesso: 'Excesso com pedidos',
  sem_demanda: 'Comprando sem venda',
}
export const dataCurta = (iso) => (iso ? iso.slice(8, 10) + '/' + iso.slice(5, 7) : '—')
export const diasAte = (iso) => {
  if (!iso) return null
  const d = new Date(iso + 'T00:00:00'); const h = new Date(); h.setHours(0, 0, 0, 0)
  return Math.round((d - h) / 86400000)
}
