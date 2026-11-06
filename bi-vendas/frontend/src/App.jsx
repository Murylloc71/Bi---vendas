import { useCallback, useEffect, useMemo, useState } from 'react'
import { Ctx, resolverPeriodo } from './ctx'
import Icon from './icons'
import { MaisComprados, PedidoDrawer, Pedidos, ProntaEntrega } from './pages/Compras'
import { Historico as HistImport, Importar, ProdutosLinha, Qualidade, Sistema, Vinculos, Externo } from './pages/Dados'
import { VERSAO } from './versao'
import { Parado, PedidosXEstoque, Perdidas, Posicao, Relatorios, Reposicao } from './pages/Estoque'
import Omie from './pages/Omie'
import Overview from './pages/Overview'
import ProdutoDrawer from './pages/ProdutoDrawer'
import { Historico, Precos, Produtos, Resultado } from './pages/Vendas'
import { useApi } from './ui'
import Analise from './pages/Analise'
import CurvaABC from './pages/CurvaABC'
import Qive from './pages/Qive'
import Skus from './pages/Skus'
import Marcas from './pages/Marcas'
import CalendarioCompras from './pages/CalendarioCompras'
import { api, setFiltroGlobal } from './api'

// filtros: p = período, c = categoria, n = nível, f = fornecedor
const NAV = [
  { group: null, items: [{ path: '/', label: 'Visão geral', icon: 'overview', el: Overview, filtros: 'c', lead: '' },
    { path: '/analise', label: 'Pedir análise', icon: 'report', el: Analise, filtros: 'pc' }] },
  { group: 'Vendas', items: [
    { path: '/vendas/resultado', label: 'Resultado', icon: 'result', el: Resultado, filtros: 'pc' },
    { path: '/vendas/produtos', label: 'Produtos', icon: 'products', el: Produtos, filtros: 'pcn' },
    { path: '/vendas/precos', label: 'Preços', icon: 'price', el: Precos, filtros: 'pc' },
    { path: '/vendas/curva-abc', label: 'Curva ABC', icon: 'result', el: CurvaABC, filtros: 'pc' },
    { path: '/vendas/historico', label: 'Mês a mês', icon: 'history', el: Historico, filtros: 'cn' },
  ] },
  { group: 'Estoque', items: [
    { path: '/estoque/posicao', label: 'Posição', icon: 'stock', el: Posicao, filtros: 'cn' },
    { path: '/estoque/reposicao', label: 'Reposição', icon: 'restock', el: Reposicao, filtros: 'cn', badge: 'repo' },
    { path: '/estoque/parado', label: 'Parado e excesso', icon: 'idle', el: Parado, filtros: 'cn' },
    { path: '/estoque/perdidas', label: 'Vendas perdidas', icon: 'lost', el: Perdidas, filtros: 'pcn' },
    { path: '/estoque/pedidos-x-estoque', label: 'Pedidos x estoque', icon: 'compare', el: PedidosXEstoque, filtros: 'cn' },
    { path: '/estoque/relatorios', label: 'Relatórios', icon: 'report', el: Relatorios, filtros: 'cn' },
  ] },
  { group: 'Compras', items: [
    { path: '/compras/pedidos', label: 'Pedidos (Omie)', icon: 'orders', el: Pedidos, filtros: 'f', badge: 'vencidos' },
    { path: '/compras/pronta-entrega', label: 'Pronta-entrega', icon: 'saving', el: ProntaEntrega, filtros: 'p' },
    { path: '/compras/mais-comprados', label: 'Mais comprados', icon: 'box', el: MaisComprados, filtros: 'p' },
    { path: '/compras/marcas', label: 'Marcas', icon: 'products', el: Marcas, filtros: 'p' },
    { path: '/compras/calendario', label: 'Calendário de compras', icon: 'history', el: CalendarioCompras },
  ] },
  { group: 'Dados', items: [
    { path: '/dados/importar', label: 'Importar arquivos', icon: 'upload', el: Importar },
    { path: '/dados/omie', label: 'Omie', icon: 'plug', el: Omie },
    { path: '/dados/qive', label: 'Qive', icon: 'plug', el: Qive },
    { path: '/dados/historico', label: 'Histórico de importações', icon: 'log', el: HistImport },
    { path: '/dados/vinculos', label: 'Vínculos de estoque', icon: 'link', el: Vinculos },
    { path: '/dados/externo', label: 'Estoque externo', icon: 'layers', el: Externo },
    { path: '/dados/produtos-linha', label: 'Produtos em linha', icon: 'check', el: ProdutosLinha },
    { path: '/dados/skus', label: 'SKUs do BI', icon: 'filter', el: Skus },
    { path: '/dados/qualidade', label: 'Qualidade e regras', icon: 'check', el: Qualidade },
    { path: '/dados/sistema', label: 'Sistema', icon: 'report', el: Sistema },
  ] },
]
const ROTAS = NAV.flatMap((g) => g.items.map((i) => ({ ...i, group: g.group })))

const ler = (k, d) => { try { const v = localStorage.getItem(k); return v ? { ...d, ...JSON.parse(v) } : d } catch { return d } }
const gravar = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* sem storage */ } }
const rotaAtual = () => (location.hash.replace(/^#/, '') || '/')

function BI({ papel, sair }) {
  const [path, setPath] = useState(rotaAtual)
  const [f, setF] = useState(() => ler('bi.filtros', { periodo: { preset: 'atual' }, categoria: 'calcado', nivel: 'modelo', fornecedor: null }))
  const [tema, setTema] = useState(() => { try { return localStorage.getItem('bi.tema') } catch { return null } })
  const [versao, setVersao] = useState(0)
  // gaveta do produto com histórico: abrir um SKU de dentro de um modelo permite voltar
  const [pilha, setPilha] = useState([])
  const produto = pilha.length ? pilha[pilha.length - 1] : null
  const setProduto = (p) => setPilha(p ? [p] : [])
  const [pedido, setPedido] = useState(null)
  const [menu, setMenu] = useState(false)
  const [abertos, setAbertos] = useState(() => ler('bi.menu', {}))
  const meta = useApi('/api/meta', null, [versao])
  const badges = useApi('/api/estoque/reposicao', { nivel: 'sku', categoria: 'calcado' }, [versao])
  const ped = useApi('/api/compras/pedidos', {}, [versao])

  useEffect(() => { const h = () => { setPath(rotaAtual()); setMenu(false) }; window.addEventListener('hashchange', h); return () => window.removeEventListener('hashchange', h) }, [])
  useEffect(() => {
    if (tema) document.documentElement.dataset.theme = tema; else delete document.documentElement.dataset.theme
    try { tema ? localStorage.setItem('bi.tema', tema) : localStorage.removeItem('bi.tema') } catch { /* */ }
  }, [tema])
  const setFiltro = (p) => setF((old) => { const n = { ...old, ...p }; gravar('bi.filtros', n); return n })
  // filtro global de produtos em linha: aplicado em todas as consultas à API
  setFiltroGlobal({ linha: f.linha || '', curva: f.curva || '' })
  const go = useCallback((p) => { location.hash = p; window.scrollTo(0, 0) }, [])
  const rota = ROTAS.find((r) => r.path === path) || ROTAS[0]
  useEffect(() => { document.title = `${rota.label} · BI Vendas & Estoque` }, [rota])

  const meses = meta.data?.meses || []
  const per = useMemo(() => resolverPeriodo(f.periodo, meses), [f.periodo, meses])
  const escuro = tema ? tema === 'dark' : window.matchMedia?.('(prefers-color-scheme: dark)').matches
  const ctx = {
    f, setFiltro, per, meta: meta.data, versao, bump: () => setVersao((v) => v + 1), go,
    openProduto: (nivel, chave) => setPilha((pl) => (pl.length && !(pl[pl.length - 1].nivel === nivel && pl[pl.length - 1].chave === chave) ? [...pl, { nivel, chave }] : [{ nivel, chave }])),
    openPedido: (id) => setPedido(id),
    // Clique num mês dos gráficos: filtra o período por esse mês e abre o resultado dele.
    irParaMes: (mes, destino = '/vendas/resultado') => {
      const m = meses.find((x) => x.mes === mes)
      if (!m) return
      setFiltro({ periodo: m.parcial ? { preset: 'atual' } : { preset: 'custom', ini: mes, fim: mes } })
      setProduto(null)
      if (destino && destino !== path) go(destino)
    },
  }
  const nBadge = {
    repo: badges.data?.reposicao?.contagem?.ruptura_sem_pedido?.itens,
    vencidos: ped.data?.resumo?.previsao_vencida?.pedidos,
  }
  const Page = rota.el
  // Tópico da página atual fica sempre aberto; os demais seguem o que a pessoa escolheu (lembrado no navegador).
  const grupoAberto = (g) => g === rota.group || !!abertos[g]
  const alternarGrupo = (g) => setAbertos((old) => { const n = { ...old, [g]: !grupoAberto(g) }; gravar('bi.menu', n); return n })
  const fl = rota.filtros || ''
  const parcial = meses.find((m) => m.parcial)
  const perLabel = (() => {
    const a = meses.find((m) => m.mes === per[0]), b = meses.find((m) => m.mes === per[1])
    return a && b ? (a.mes === b.mes ? a.rotulo : `${a.rotulo} a ${b.rotulo}`) : ''
  })()

  return (
    <Ctx.Provider value={ctx}>
      <div className="shell">
        <aside className={`side ${menu ? 'open' : ''}`} aria-label="Navegação">
          <div className="side-brand"><div className="mark" aria-hidden="true">BI</div><div><b>Vendas & Estoque</b><small>calçados · ML e Shopee</small></div></div>
          <nav>
            {NAV.map((g, gi) => (
              <div className={`nav-group${g.group ? ' tem-topico' : ''}${!g.group || grupoAberto(g.group) ? ' aberto' : ''}`} key={gi}>
                {g.group && (() => {
                  const alertas = g.items.reduce((t, it) => t + (it.badge === 'repo' && nBadge[it.badge] > 0 ? nBadge[it.badge] : 0), 0)
                  return (
                    <button className="nav-topico" aria-expanded={grupoAberto(g.group)} aria-controls={`grp-${gi}`} onClick={() => alternarGrupo(g.group)}>
                      <Icon name="chevron" className="chev" />{g.group}
                      {!grupoAberto(g.group) && alertas > 0 && <span className="badge warn" title="Alertas dentro deste tópico">{alertas}</span>}
                    </button>
                  )
                })()}
                <div className="nav-itens" id={`grp-${gi}`} hidden={g.group ? !grupoAberto(g.group) : undefined}>
                {g.items.map((it) => (
                  <button key={it.path} className="nav-item" aria-current={rota.path === it.path ? 'page' : undefined} onClick={() => go(it.path)}>
                    <Icon name={it.icon} />{it.label}
                    {it.badge && nBadge[it.badge] > 0 && <span className={`badge ${it.badge === 'repo' ? 'warn' : ''}`} title={it.badge === 'repo' ? 'Zerados sem pedido' : 'Pedidos faturados'}>{nBadge[it.badge]}</span>}
                  </button>
                ))}
                </div>
              </div>
            ))}
          </nav>
          <div className="side-foot">
            {meta.data?.fotos_estoque?.length > 0 && <span>Estoque de {meta.data.fotos_estoque.at(-1).split('-').reverse().join('/')}</span>}
            <button onClick={() => setTema(escuro ? 'light' : 'dark')}><Icon name={escuro ? 'sun' : 'moon'} />{escuro ? 'Tema claro' : 'Tema escuro'}</button>
            {papel === 'leitura' && <span style={{ fontSize: 12, color: 'var(--muted)', padding: '0 10px' }}>Acesso só de consulta</span>}
            {sair && <button onClick={sair}><Icon name="plug" />Sair</button>}
          </div>
        </aside>
        <div className="main">
          <header className="top">
            <button className="btn ghost menu-btn" aria-label="Abrir menu" onClick={() => setMenu(!menu)}><Icon name="menu" /></button>
            <h1>{rota.group && <span>{rota.group} / </span>}{rota.label}</h1>
            <div className="top-filters">
              {fl.includes('p') && meses.length > 0 && (
                <>
                  <label className="ctl"><Icon name="calendar" /><span className="sr-only">Período</span>
                    <select value={f.periodo.preset} onChange={(e) => setFiltro({ periodo: { ...f.periodo, preset: e.target.value, ini: per[0], fim: per[1] } })} aria-label="Período">
                      <option value="ultimo">Último mês fechado</option>
                      {parcial && <option value="atual">Mês atual ({parcial.rotulo}, parcial)</option>}
                      <option value="3m">Últimos 3 meses fechados</option>
                      <option value="6m">Últimos 6 meses fechados</option>
                      <option value="12m">Todo o histórico</option>
                      <option value="custom">Escolher meses</option>
                    </select>
                  </label>
                  {f.periodo.preset === 'custom' ? (
                    <>
                      <label className="ctl">de<select value={per[0]} onChange={(e) => setFiltro({ periodo: { ...f.periodo, ini: e.target.value } })} aria-label="Mês inicial">{meses.map((m) => <option key={m.mes} value={m.mes}>{m.rotulo}</option>)}</select></label>
                      <label className="ctl">até<select value={per[1]} onChange={(e) => setFiltro({ periodo: { ...f.periodo, fim: e.target.value } })} aria-label="Mês final">{meses.map((m) => <option key={m.mes} value={m.mes}>{m.rotulo}</option>)}</select></label>
                    </>
                  ) : <span style={{ color: 'var(--muted)', fontSize: 13 }}>{perLabel}</span>}
                </>
              )}
              <label className={`ctl${f.curva ? ' ativo' : ''}`} title="Mostrar só os modelos de uma curva ABC (Vendas › Curva ABC); vale para todas as telas">
                <Icon name="result" /><span className="sr-only">Curva ABC</span>
                <select value={f.curva || ''} onChange={(e) => setFiltro({ curva: e.target.value })} aria-label="Curva ABC">
                  <option value="">Curva: todas</option><option value="A">Só curva A</option><option value="B">Só curva B</option>
                  <option value="C">Só curva C</option><option value="AB">Curvas A e B</option><option value="sem_venda">Sem venda (fora da curva)</option>
                </select>
              </label>
              <label className={`ctl${f.linha ? ' ativo' : ''}`} title="Mostrar só produtos em linha, fora de linha ou sem marcação (vale para todas as telas)">
                <Icon name="check" /><span className="sr-only">Linha</span>
                <select value={f.linha || ''} onChange={(e) => setFiltro({ linha: e.target.value })} aria-label="Produtos em linha">
                  <option value="">Linha: todos</option><option value="em_linha">Só em linha</option>
                  <option value="fora">Só fora de linha</option><option value="sem_marcacao">Só sem marcação</option>
                </select>
              </label>
              {fl.includes('c') && (
                <label className="ctl"><Icon name="filter" /><span className="sr-only">Produtos</span>
                  <select value={f.categoria} onChange={(e) => setFiltro({ categoria: e.target.value })} aria-label="Produtos">
                    <option value="calcado">Calçados</option><option value="outro">Outros produtos</option><option value="todos">Todos os produtos</option>
                  </select>
                </label>
              )}
              {fl.includes('n') && (
                <div className="seg" role="group" aria-label="Agrupar por">
                  {[['modelo', 'Modelo'], ['cabedal', 'Cabedal'], ['sku', 'SKU']].map(([v, t]) => <button key={v} aria-pressed={f.nivel === v} onClick={() => setFiltro({ nivel: v })}>{t}</button>)}
                </div>
              )}
              {fl.includes('f') && ped.data?.fornecedores?.length > 0 && (
                <label className="ctl"><Icon name="truck" /><span className="sr-only">Fornecedor</span>
                  <select value={f.fornecedor ?? ped.data.fornecedor ?? ''} onChange={(e) => setFiltro({ fornecedor: e.target.value })} aria-label="Fornecedor">
                    {ped.data.fornecedores.map((x) => <option key={x.fornecedor} value={x.fornecedor}>{x.fornecedor} ({x.pedidos})</option>)}
                    <option value="__todos">Todos os fornecedores</option>
                  </select>
                </label>
              )}
            </div>
          </header>
          <main className="content" id="conteudo">
            <AvisoSistema versao={versao} go={go} />
            {meta.error ? <div className="err">{meta.error.message}</div>
              : !meta.data ? <div className="skel" style={{ height: 400 }} />
                : <Page key={rota.path} />}
          </main>
        </div>
        {produto && <ProdutoDrawer key={produto.nivel + produto.chave} alvo={produto} onClose={() => setPilha([])}
          anterior={pilha.length > 1 ? pilha[pilha.length - 2] : null} onBack={() => setPilha((pl) => pl.slice(0, -1))} />}
        {pedido && <PedidoDrawer key={pedido} id={pedido} onClose={() => setPedido(null)} />}
      </div>
    </Ctx.Provider>
  )
}

/** Avisa quando a interface carregada é de outra versão que o servidor, ou quando o banco não guarda os dados. */
function AvisoSistema({ versao, go }) {
  const st = useApi('/api/sistema', null, [versao])
  const d = st.data
  if (!d) return null
  if (d.versao !== VERSAO) return (
    <div className="alert bad" style={{ margin: '0 0 16px' }}>
      <b>A interface aberta está desatualizada</b> (interface {VERSAO}, servidor {d.versao}). Recarregue a página com Ctrl+F5.
      Se continuar, pare e rode o Repl de novo (ou republique) para recompilar a interface.
    </div>)
  if (d.avisos?.length) return (
    <div className="alert bad" style={{ margin: '0 0 16px' }}>{d.avisos[0]} <button className="link" onClick={() => go('/dados/sistema')}>Ver detalhes</button></div>)
  return null
}

/** Portão de login: pergunta ao servidor se precisa de senha e mostra o BI só depois de entrar. */
export default function App() {
  const [st, setSt] = useState(null)
  const checar = () => api.get('/api/sessao').then(setSt, () => setSt({ erro: true }))
  useEffect(() => { checar(); const f = () => checar(); window.addEventListener('bi:login', f); return () => window.removeEventListener('bi:login', f) }, [])
  if (!st) return <div className="login-tela"><div className="skel" style={{ width: 340, height: 220 }} /></div>
  if (st.bloqueado) return <div className="login-tela"><div className="login-box"><h1>BI Vendas & Estoque</h1><p className="alert bad">O BI está publicado sem senha. Defina a variável <code>BI_SENHA</code> no servidor (no Render: Environment) e reinicie.</p></div></div>
  if (st.carregando) return <Carregando onPronto={checar} />
  if (st.login && !st.autenticado) return <Login onEntrar={checar} />
  const sair = st.login ? async () => { try { await api.post('/api/logout') } finally { checar() } } : null
  return <BI papel={st.papel} sair={sair} />
}

/** Primeira vez no servidor: os dados iniciais estão sendo gravados no banco. */
function Carregando({ onPronto }) {
  useEffect(() => { const t = setInterval(onPronto, 5000); return () => clearInterval(t) }, [onPronto])
  return (
    <div className="login-tela">
      <div className="login-box" role="status" aria-live="polite">
        <div className="brand-mark" aria-hidden="true">BI</div>
        <h1>Preparando o BI</h1>
        <p style={{ color: 'var(--ink-2)', margin: '6px 0 14px' }}>É a primeira vez neste banco: estou gravando vendas, compras e pedidos. Leva de 1 a 5 minutos e esta página abre sozinha quando terminar.</p>
        <div className="skel" style={{ height: 8, borderRadius: 4 }} />
      </div>
    </div>
  )
}

function Login({ onEntrar }) {
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState(null)
  const [busy, setBusy] = useState(false)
  const entrar = async (e) => {
    e.preventDefault(); setBusy(true); setErro(null)
    try { await api.post('/api/login', { senha }); onEntrar() } catch (x) { setErro(x.message); setBusy(false) }
  }
  return (
    <div className="login-tela">
      <form className="login-box" onSubmit={entrar}>
        <div className="brand-mark" aria-hidden="true">BI</div>
        <h1>BI Vendas & Estoque</h1>
        <p style={{ color: 'var(--muted)', margin: '0 0 16px' }}>Digite a senha para entrar.</p>
        <label htmlFor="senha" className="sr-only">Senha</label>
        <input id="senha" type="password" autoComplete="current-password" autoFocus value={senha} onChange={(e) => setSenha(e.target.value)} placeholder="Senha" style={{ width: '100%' }} />
        {erro && <div className="alert bad" style={{ marginTop: 10 }} role="alert">{erro}</div>}
        <button className="btn primary" type="submit" disabled={busy || !senha} style={{ width: '100%', marginTop: 12, justifyContent: 'center' }}>{busy ? 'Entrando…' : 'Entrar'}</button>
      </form>
    </div>
  )
}
