import { createContext, useContext } from 'react'

export const Ctx = createContext(null)
export const useCtx = () => useContext(Ctx)

/** Converte o preset de período em meses (YYYY-MM) a partir dos meses disponíveis. */
export function resolverPeriodo(per, meses) {
  const completos = meses.filter((m) => !m.parcial)
  const parcial = meses.find((m) => m.parcial)
  const ult = completos.at(-1)?.mes || meses.at(-1)?.mes
  const n = (k) => [completos.at(-k)?.mes || completos[0]?.mes, ult]
  switch (per.preset) {
    case 'atual': return parcial ? [parcial.mes, parcial.mes] : [ult, ult]
    case '3m': return n(3)
    case '6m': return n(6)
    case '12m': return [meses[0]?.mes, meses.at(-1)?.mes]
    case 'custom': return [per.ini || ult, per.fim || ult]
    default: return [ult, ult]
  }
}
