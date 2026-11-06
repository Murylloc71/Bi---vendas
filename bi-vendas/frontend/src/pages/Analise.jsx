import { useState } from 'react'
import { urlApi } from '../api'
import { useCtx } from '../ctx'
import { n0 } from '../fmt'
import Icon from '../icons'
import { Box, Load, useApi } from '../ui'

/** Gera um texto com todos os números do BI para colar numa conversa com o Claude (analista). */
export default function Analise() {
  const { f, per, versao } = useCtx()
  const [detalhe, setDetalhe] = useState('completo')
  const [copiado, setCopiado] = useState(false)
  const st = useApi('/api/analise/prompt', { inicio: per[0], fim: per[1], categoria: f.categoria, detalhe }, [versao])
  const copiar = async (texto) => {
    try { await navigator.clipboard.writeText(texto) } catch {
      const t = document.getElementById('prompt-analise'); t.select(); document.execCommand('copy')
    }
    setCopiado(true); setTimeout(() => setCopiado(false), 2500)
  }
  const baixar = (texto) => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([texto], { type: 'text/markdown;charset=utf-8' }))
    a.download = `analise-bi-${new Date().toISOString().slice(0, 10)}.md`
    a.click(); URL.revokeObjectURL(a.href)
  }
  return (
    <>
      <Box title="Pedir uma análise ao Claude" sub="O BI junta os números de vendas, estoque, reposição, compras e pedidos num texto pronto. Copie e cole numa conversa com o Claude para receber a leitura do analista.">
        <ol className="msg-list" style={{ marginTop: 0 }}>
          <li>Escolha o período e os produtos no topo (e, se quiser, o filtro de linha).</li>
          <li>Clique em <b>Copiar prompt</b> e cole na conversa com o Claude.</li>
          <li>Ele responde o que esperar, o que aprendemos, o que melhorou, riscos e recomendações de compra.</li>
        </ol>
        <p className="note" style={{ margin: '4px 0 0' }}>O texto não leva informação financeira (parcelas, vencimentos, contas a pagar).</p>
      </Box>
      <div style={{ height: 16 }} />
      <Load state={st} height={420}>{(d) => (
        <Box title={`Prompt de análise · ${d.periodo}`} sub={`${n0(d.caracteres)} caracteres`}
          right={
            <span style={{ display: 'inline-flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <span className="seg" role="group" aria-label="Nível de detalhe">
                {[['completo', 'Completo'], ['resumido', 'Resumido']].map(([v, t]) => <button key={v} aria-pressed={detalhe === v} onClick={() => setDetalhe(v)}>{t}</button>)}
              </span>
              <button className="btn ghost" onClick={() => baixar(d.texto)}><Icon name="download" />Baixar .md</button>
              <button className="btn primary" onClick={() => copiar(d.texto)}>{copiado ? 'Copiado!' : 'Copiar prompt'}</button>
            </span>}>
          <textarea id="prompt-analise" readOnly value={d.texto} aria-label="Prompt de análise"
            style={{ width: '100%', minHeight: 520, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12.5, lineHeight: 1.5,
              padding: 12, border: '1px solid var(--line)', borderRadius: 'var(--r)', background: 'var(--surface-2)', color: 'var(--ink)', resize: 'vertical' }} />
        </Box>
      )}</Load>
    </>
  )
}
