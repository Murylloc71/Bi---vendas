"""API do BI. Executar: uvicorn app.main:app --host 0.0.0.0 --port 8000 (dentro de backend/)."""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, insert, select, func

from . import db
from . import importadores as imp
from . import indicadores as ind
from . import omie
from . import pedidos as pd_
from . import relatorios as rel
from . import resumo as rs
from .importadores.comum import ErroImportacao
from .produto import interpretar

db.criar_tabelas()
app = FastAPI(title="BI Vendas & Estoque", version="2.0")


SEMANAL_PADRAO = "2026-10"


@app.on_event("startup")
def _regras_produto():
    try:
        db.criar_tabelas()
        if _cfg_get("vendas_semanais_desde") is None:      # nunca configurado: liga o padrão
            _cfg_set("vendas_semanais_desde", SEMANAL_PADRAO)
        ind.carregar_modelos_por_cabedal(ler=True)
    except Exception:  # noqa: BLE001 - nunca impedir o servidor de subir
        pass


@app.on_event("startup")
def _agendar_omie():
    # Omie (pedidos de compra + estoque do Omie 03 e 04): todo dia no(s) horário(s) configurado(s),
    # padrão 12:00 de Brasília. Para voltar ao intervalo antigo, defina OMIE_SYNC_HORAS (ex.: 6).
    horas = float(os.environ.get("OMIE_SYNC_HORAS", "0") or 0)
    if horas > 0:
        omie.agendar(horas)
        from . import estoque_omie
        estoque_omie.agendar(horas)
    else:
        from . import agenda
        agenda.iniciar()
    from . import qive
    h_q = float(os.environ.get("QIVE_SYNC_HORAS", "6") or 0)
    if h_q > 0:
        qive.agendar(h_q)


@app.exception_handler(omie.ErroOmie)
async def _erro_omie(_, exc):
    return JSONResponse(status_code=502, content={"detail": str(exc)})
_CARGA = {"rodando": False, "erro": None, "inicio": None, "fim": None}


@app.on_event("startup")
def _carga_automatica():
    """Banco vazio: carrega dados_iniciais/ em segundo plano (o site já responde enquanto isso)."""
    import threading
    pasta = db.RAIZ / "dados_iniciais"
    if os.environ.get("CARGA_INICIAL", "1") == "0" or not pasta.exists():
        return
    try:
        db.criar_tabelas()
        with db.engine.connect() as c:
            n = c.execute(select(func.count()).select_from(db.vendas_mensais)).scalar()
    except Exception:  # noqa: BLE001
        return
    if n:
        return

    def rodar():
        _CARGA.update(rodando=True, erro=None, inicio=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        try:
            from scripts.carga_inicial import main as carga
            carga(str(pasta), None)
        except Exception as e:  # noqa: BLE001
            _CARGA["erro"] = str(e)
        finally:
            _CARGA.update(rodando=False, fim=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    _CARGA["rodando"] = True
    threading.Thread(target=rodar, daemon=True).start()


@app.middleware("http")
async def _login(request, call_next):
    """Exige login em toda a API (menos login, saúde e o endereço do agendador)."""
    from . import auth
    caminho = request.url.path
    if _CARGA["rodando"] and caminho.startswith("/api/") and caminho not in auth.LIVRES:
        return JSONResponse(status_code=503, content={"detail": "O BI está carregando os dados iniciais. Aguarde alguns minutos."})
    papel = auth.ler_sessao(request.cookies.get(auth.COOKIE)) if auth.ativo() else "admin"
    ok, status, msg = auth.permitido(request.url.path, request.method, papel)
    if not ok:
        return JSONResponse(status_code=status, content={"detail": msg})
    request.state.papel = papel
    return await call_next(request)


@app.post("/api/login")
def login(request: Request, corpo: dict = Body(...)):
    from . import auth
    if not auth.ativo():
        return {"ok": True, "papel": "admin", "login": False}
    try:
        papel = auth.conferir_senha(str(corpo.get("senha") or ""), request.client.host if request.client else "?")
    except PermissionError as e:
        raise HTTPException(429, str(e)) from e
    if not papel:
        raise HTTPException(401, "Senha incorreta.")
    r = JSONResponse({"ok": True, "papel": papel})
    r.set_cookie(auth.COOKIE, auth.criar_sessao(papel), max_age=auth.DURACAO, httponly=True, samesite="lax",
                 secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https", path="/")
    return r


@app.post("/api/logout")
def logout():
    from . import auth
    r = JSONResponse({"ok": True})
    r.delete_cookie(auth.COOKIE, path="/")
    return r


@app.get("/api/sessao")
def sessao(request: Request):
    from . import auth
    if not auth.ativo():
        return {"login": False, "papel": "admin", "aviso": "Sem senha (BI_SENHA): o BI está aberto." if auth.na_internet() else None,
                "bloqueado": auth.na_internet(), "carregando": _CARGA["rodando"], "erro_carga": _CARGA["erro"]}
    papel = auth.ler_sessao(request.cookies.get(auth.COOKIE))
    return {"login": True, "papel": papel, "autenticado": papel is not None, "carregando": _CARGA["rodando"], "erro_carga": _CARGA["erro"]}


@app.post("/api/cron/sincronizar")
@app.get("/api/cron/sincronizar")
def cron_sincronizar(token: str = ""):
    """Chamado pelo agendador externo (ex.: cron-job.org) às 12h: acorda o servidor e sincroniza
    Omie (pedidos + estoque) e Qive em segundo plano. Protegido pela variável CRON_TOKEN."""
    import hmac as _hmac
    import threading
    esperado = os.environ.get("CRON_TOKEN", "").strip()
    if not esperado or not _hmac.compare_digest(token.encode(), esperado.encode()):
        raise HTTPException(403, "Token inválido.")
    from . import agenda, qive

    def rodar():
        try:
            agenda.executar()
        finally:
            if qive.credenciais()[0]:
                try:
                    qive.sincronizar()
                except Exception:  # noqa: BLE001
                    pass
    threading.Thread(target=rodar, daemon=True).start()
    return JSONResponse(status_code=202, content={"ok": True, "mensagem": "Sincronização iniciada."})


@app.middleware("http")
async def _filtro_linha(request, call_next):
    """?linha=em_linha|fora|sem_marcacao em qualquer rota filtra os produtos pela marcação."""
    from . import linha as _linha
    from . import abc as _abc
    modo = request.query_params.get("linha")
    curva = request.query_params.get("curva")
    tok = _linha.MODO.set(modo if modo in _linha.MODOS else None)
    tok2 = _abc.MODO.set(curva if curva in _abc.FILTROS else None)
    try:
        return await call_next(request)
    finally:
        _linha.MODO.reset(tok)
        _abc.MODO.reset(tok2)


app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])

MAX_UPLOAD = 30 * 1024 * 1024


@app.exception_handler(ErroImportacao)
async def _erro_imp(_, exc: ErroImportacao):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def _validar(nivel, categoria):
    if nivel not in ind.NIVEIS:
        raise HTTPException(400, f"nivel deve ser um de {ind.NIVEIS}")
    if categoria not in ind.CATEGORIAS:
        raise HTTPException(400, f"categoria deve ser uma de {ind.CATEGORIAS}")


def _periodo(d, inicio, fim):
    meses = ind.resolver_periodo(d, inicio, fim)
    if not meses:
        raise HTTPException(404, "Sem dados de vendas no período. Importe o relatório de vendas.")
    return meses


# ----------------------------------------------------------------------------- leitura
@app.get("/api/meta")
def meta():
    d = ind.dados()
    with db.engine.connect() as c:
        ult = {r.tipo: {"data": r.criado_em.isoformat() if r.criado_em else None, "arquivo": r.arquivo}
               for r in c.execute(select(db.importacoes).where(db.importacoes.c.status == "ok")
                                  .order_by(db.importacoes.c.id))}
    completos = [m for m in d.meses if m not in d.parciais]
    return {
        "meses": [{"mes": m.strftime("%Y-%m"), "rotulo": ind.mes_label(m), "parcial": m in d.parciais,
                   "dias": d.dias_mes.get(m)} for m in d.meses],
        "ultimo_mes_completo": completos[-1].strftime("%Y-%m") if completos else None,
        "depositos": sorted(d.E["deposito"].unique().tolist()) if not d.E.empty else [],
        "fotos_estoque": sorted({x.strftime("%Y-%m-%d") for x in d.E["data"].unique()}) if not d.E.empty else [],
        "ultimas_importacoes": ult,
        "tem_dados": bool(d.meses),
    }


@app.get("/api/painel")
def painel(inicio: str | None = None, fim: str | None = None, nivel: str = "modelo", categoria: str = "todos"):
    """Todos os indicadores de um intervalo de meses (ATUAL e ALL TIME acumulado)."""
    _validar(nivel, categoria)
    d = ind.dados()
    meses = _periodo(d, inicio, fim)
    k = ind.kpis_vendas(d, meses, categoria)
    tab = ind.tabela(d, meses, categoria, nivel)
    tempo = ind.tempo_estoque(d, meses, categoria)
    rup = ind.rupturas_atuais(d, categoria, nivel)
    perd = ind.vendas_perdidas(d, meses, categoria, nivel)
    eco = ind.economia_pe(d, meses, categoria)
    grade = ind.grade_quebrada(d) if categoria in ("todos", "calcado") else {"status": "sem_dados"}
    parado = ind.estoque_parado(d, categoria, nivel)
    rot = ind.mes_label(meses[0]) + ("" if len(meses) == 1 else f" a {ind.mes_label(meses[-1])}")
    return {
        "periodo": {"inicio": meses[0].strftime("%Y-%m"), "fim": meses[-1].strftime("%Y-%m"), "rotulo": rot,
                    "meses": len(meses), "dias": ind.dias_periodo(d, meses)},
        "kpis": k, "serie": ind.serie_mensal(d, meses, categoria),
        "precos": ind.faixas_preco(d, meses, categoria),
        "economia_pe": eco, "vendas_perdidas": perd, "estoque": ind.resumo_estoque(d, categoria),
        "tempo_estoque": tempo, "rupturas": rup, "grade_quebrada": grade, "estoque_parado": parado,
        "tabela": tab,
        "resumo": rs.montar(k, tab, tempo, rup, perd, eco, grade, parado, rot),
    }


@app.get("/api/home")
def home(categoria: str = "todos"):
    _validar("modelo", categoria)
    d = ind.dados()
    if not d.meses:
        return {"tem_dados": False}
    completos = [m for m in d.meses if m not in d.parciais]
    foco = completos[-1] if completos else d.meses[-1]
    parcial = next((m for m in reversed(d.meses) if m in d.parciais), None)
    k_foco = ind.kpis_vendas(d, [foco], categoria)
    ult3 = d.meses[-3:]
    tab3 = ind.tabela(d, completos[-3:] if len(completos) >= 3 else d.meses, categoria, "modelo")
    out = {
        "tem_dados": True,
        "foco": {"mes": foco.strftime("%Y-%m"), "rotulo": ind.mes_label(foco), "kpis": k_foco},
        "serie": ind.serie_mensal(d, d.meses, categoria),
        "serie_categorias": {c: ind.serie_mensal(d, d.meses, c) for c in ("calcado", "outro")} if categoria == "todos" else None,
        "top_modelos": tab3[:10],
        "top_periodo": [ind.mes_label(x) for x in (completos[-3:] if len(completos) >= 3 else d.meses)],
        "estoque": ind.resumo_estoque(d, categoria),
        "tempo_estoque": ind.tempo_estoque(d, ult3, categoria),
        "rupturas": ind.rupturas_atuais(d, categoria, "sku", limite=8),
        "grade_quebrada": ind.grade_quebrada(d, limite=8) if categoria != "outro" else {"status": "sem_dados"},
        "estoque_parado": ind.estoque_parado(d, categoria, "sku", limite=8),
        "economia_pe": ind.economia_pe(d, d.meses, categoria),
        "vendas_perdidas": ind.vendas_perdidas(d, d.meses, categoria),
    }
    if parcial is not None:
        kp = ind.kpis_vendas(d, [parcial], categoria)
        dm = parcial.days_in_month
        kp["projecao_faturamento"] = ind._f(kp["faturamento_dia"] * dm) if kp.get("faturamento_dia") else None
        kp["projecao_unidades"] = ind._f(kp["unidades_dia"] * dm, 0) if kp.get("unidades_dia") else None
        out["parcial"] = {"mes": parcial.strftime("%Y-%m"), "rotulo": ind.mes_label(parcial),
                          "dias": d.dias_mes.get(parcial), "dias_mes": dm, "kpis": kp}
    tab_foco = ind.tabela(d, [foco], categoria, "modelo")
    out["resumo"] = rs.montar(k_foco, tab_foco, out["tempo_estoque"], out["rupturas"],
                              ind.vendas_perdidas(d, [foco], categoria), ind.economia_pe(d, [foco], categoria),
                              out["grade_quebrada"], out["estoque_parado"], ind.mes_label(foco))
    return out


@app.get("/api/mensal")
def mensal(categoria: str = "todos"):
    _validar("modelo", categoria)
    d = ind.dados()
    return {"meses": ind.mensal(d, categoria)}


@app.get("/api/comparar")
def comparar(a: str, b: str, nivel: str = "modelo", categoria: str = "todos"):
    _validar(nivel, categoria)
    d = ind.dados()
    disp = {m.strftime("%Y-%m") for m in d.meses}
    if a not in disp or b not in disp:
        raise HTTPException(404, "Mês sem dados.")
    return ind.comparar_meses(d, a, b, categoria, nivel)


@app.get("/api/detalhe")
def detalhe(nivel: str, chave: str, categoria: str = "todos"):
    _validar(nivel, categoria)
    out = ind.detalhe(ind.dados(), nivel, chave, categoria)
    # pares a caminho (pedidos do Omie em aberto) por tamanho
    ac = pd_.a_caminho_por_sku()
    if not ac.empty:
        ac = ind._chaves(ac.copy())
        ac = ac[ac[f"k_{nivel}"] == chave]
        out["a_caminho"] = {"pares": ind._f(ac["a_receber"].sum(), 0),
                            "previsao": ac["previsao"].min().strftime("%Y-%m-%d") if len(ac) else None,
                            "por_tamanho": {str(t): ind._f(q, 0) for t, q in ac.groupby("tamanho")["a_receber"].sum().items()}}
    return out


# ----------------------------------------------------------------------------- páginas (endpoints menores)
def _ctx(inicio, fim, nivel, categoria):
    _validar(nivel, categoria)
    d = ind.dados()
    meses = _periodo(d, inicio, fim)
    rot = ind.mes_label(meses[0]) + ("" if len(meses) == 1 else f" a {ind.mes_label(meses[-1])}")
    per = {"inicio": meses[0].strftime("%Y-%m"), "fim": meses[-1].strftime("%Y-%m"), "rotulo": rot,
           "meses": len(meses), "dias": ind.dias_periodo(d, meses)}
    return d, meses, per


@app.get("/api/vendas/resultado")
def vendas_resultado(inicio: str | None = None, fim: str | None = None, categoria: str = "calcado"):
    d, meses, per = _ctx(inicio, fim, "modelo", categoria)
    k = ind.kpis_vendas(d, meses, categoria)
    tab = ind.tabela(d, meses, categoria, "modelo")
    tempo = ind.tempo_estoque(d, meses, categoria)
    rup = ind.rupturas_atuais(d, categoria, "sku")
    perd = ind.vendas_perdidas(d, meses, categoria)
    eco = ind.economia_pe(d, meses, categoria)
    grade = ind.grade_quebrada(d) if categoria != "outro" else {"status": "sem_dados"}
    parado = ind.estoque_parado(d, categoria)
    ant = ind.periodo_anterior(d, meses)
    return {"periodo": per, "kpis": k, "serie": ind.serie_mensal(d, meses, categoria),
            "serie_anterior": ind.serie_mensal(d, ant, categoria) if ant else None,
            "top": tab[:8], "resumo": rs.montar(k, tab, tempo, rup, perd, eco, grade, parado, per["rotulo"]),
            "graficos": ind.graficos_resultado(tab, ind.faixas_preco(d, meses, categoria)),
            "serie_12m": ind.serie_mensal(d, d.meses[-12:], categoria),
            "economia_pe": {x: eco.get(x) for x in ("status", "economia", "pares_calculados", "economia_pct", "motivo")},
            "vendas_perdidas": {x: perd.get(x) for x in ("status", "pares", "valor", "dias_monitorados", "motivo")}}


@app.get("/api/vendas/diario")
def vendas_diario(categoria: str = "calcado", semanas: int = 12):
    _validar("modelo", categoria)
    return ind.vendas_diarias(ind.dados(), categoria, max(4, min(semanas, 52)))


@app.get("/api/vendas/produtos")
def vendas_produtos(inicio: str | None = None, fim: str | None = None, nivel: str = "modelo", categoria: str = "calcado"):
    d, meses, per = _ctx(inicio, fim, nivel, categoria)
    tab = ind.tabela(d, meses, categoria, nivel)
    return {"periodo": per, "tabela": tab, "kpis": ind.kpis_vendas(d, meses, categoria)}


@app.get("/api/vendas/precos")
def vendas_precos(inicio: str | None = None, fim: str | None = None, categoria: str = "calcado"):
    d, meses, per = _ctx(inicio, fim, "modelo", categoria)
    return {"periodo": per, "precos": ind.faixas_preco(d, meses, categoria), "kpis": ind.kpis_vendas(d, meses, categoria),
            "serie": ind.serie_mensal(d, d.meses, categoria)}


@app.get("/api/estoque/posicao")
def estoque_posicao(nivel: str = "modelo", categoria: str = "calcado"):
    _validar(nivel, categoria)
    d = ind.dados()
    base = ind.meses_base_demanda(d)
    if not base:
        raise HTTPException(404, "Sem vendas importadas.")
    tab = ind.tabela(d, base, categoria, nivel)
    return {"base": [ind.mes_label(base[0]), ind.mes_label(base[-1])], "estoque": ind.resumo_estoque(d, categoria),
            "tempo_estoque": ind.tempo_estoque(d, base, categoria),
            "tabela": [t for t in tab if (t["estoque"] or 0) != 0 or t["status_estoque"] in ("ruptura", "sem_cadastro")]}


@app.get("/api/estoque/reposicao")
def estoque_reposicao(nivel: str = "sku", categoria: str = "calcado", fornecedor: str | None = None):
    _validar(nivel, categoria)
    d = ind.dados()
    forn = None if fornecedor == "__todos" else (fornecedor or pd_.fornecedor_padrao())
    return {"reposicao": pd_.reposicao(d, categoria, nivel, forn),
            "grade": pd_.grade_com_pedidos(d, forn, limite=500) if categoria != "outro" else {"status": "sem_dados", "motivo": "Disponível para calçados."},
            "fornecedor": forn}


@app.get("/api/estoque/tendencia")
def estoque_tendencia(nivel: str = "sku", categoria: str = "calcado", dias: int = 7):
    _validar(nivel, categoria)
    d = ind.dados()
    t = rel.tendencia(d, categoria, nivel, max(1, min(dias, 365)))
    t["evolucao"] = rel.evolucao(d, categoria)
    return t


@app.get("/api/relatorios/estoque.xlsx")
def relatorio_estoque(nivel: str = "sku", categoria: str = "calcado", fornecedor: str | None = None,
                      dias: int = 7, limite: int = ind.COBERTURA_CRITICA):
    _validar(nivel, categoria)
    forn = None if fornecedor == "__todos" else (fornecedor or pd_.fornecedor_padrao())
    conteudo = rel.planilha_estoque(categoria, nivel, forn, max(1, min(dias, 365)), max(1, min(limite, 365)))
    nome = f"relatorio-estoque-{nivel}-{date.today():%Y-%m-%d}.xlsx"
    return Response(conteudo, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


@app.get("/api/estoque/parado")
def estoque_parado_ep(nivel: str = "sku", categoria: str = "calcado"):
    _validar(nivel, categoria)
    d = ind.dados()
    base = ind.meses_base_demanda(d)
    te = ind.tempo_estoque(d, base, categoria)
    tab = ind.tabela(d, base, categoria, nivel)
    return {"parado": ind.estoque_parado(d, categoria, nivel, limite=300), "tempo_estoque": te,
            "excesso": [t for t in tab if t["status_estoque"] == "excesso"]}


@app.get("/api/estoque/perdidas")
def estoque_perdidas(inicio: str | None = None, fim: str | None = None, nivel: str = "sku", categoria: str = "calcado"):
    d, meses, per = _ctx(inicio, fim, nivel, categoria)
    return {"periodo": per, "vendas_perdidas": ind.vendas_perdidas(d, meses, categoria, nivel, limite=200),
            "rupturas": ind.rupturas_atuais(d, categoria, nivel, limite=200)}


@app.get("/api/compras/pronta-entrega")
def compras_pe(inicio: str | None = None, fim: str | None = None, categoria: str = "calcado"):
    d, meses, per = _ctx(inicio, fim, "modelo", categoria)
    return {"periodo": per, "economia_pe": ind.economia_pe(d, meses, categoria)}


@app.get("/api/compras/pedidos")
def compras_pedidos(fornecedor: str | None = None):
    forn = None if fornecedor == "__todos" else (fornecedor or pd_.fornecedor_padrao())
    return {"fornecedor": forn, "fornecedores": pd_.fornecedores(), "resumo": pd_.resumo(forn),
            "pedidos": pd_.lista(forn), "sync": omie.estado()}


@app.get("/api/compras/mais-comprados")
def compras_mais_comprados(inicio: str | None = None, fim: str | None = None):
    d, meses, per = _ctx(inicio, fim, "modelo", "todos")
    try:
        _, I = pd_.carregar(None)
        rec = I.groupby("modelo")["a_receber"].sum().to_dict() if not I.empty else {}
    except Exception:  # noqa: BLE001 - sem pedidos do Omie, segue sem a coluna
        rec = {}
    return {"periodo": per, **ind.mais_comprados(d, meses, rec)}


@app.get("/api/marcas")
def marcas_rel(inicio: str | None = None, fim: str | None = None, agrupar: bool = False):
    from . import marcas as _marcas
    d, meses, per = _ctx(inicio, fim, "modelo", "calcado")
    try:
        _, I = pd_.carregar(None)
        rec = I.groupby("modelo")["a_receber"].sum().to_dict() if not I.empty else {}
    except Exception:  # noqa: BLE001
        rec = {}
    return _marcas.relatorio(d, meses, agrupar, rec)


@app.put("/api/marcas/manual")
def marcas_manual(corpo: dict = Body(...)):
    from . import marcas as _marcas
    try:
        _marcas.definir_manual(str(corpo.get("modelo") or "").strip(), corpo.get("marca") or None)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


@app.get("/api/compras/calendario")
def compras_calendario(inicio: str | None = None, fim: str | None = None, agrupar: bool = False):
    from . import calendario as _cal
    return _cal.calendario(ind.dados(), inicio, fim, agrupar)


@app.get("/api/compras/pedidos-por-sku")
def compras_pedidos_por_sku(q: str = "", fornecedor: str | None = None):
    forn = None if fornecedor == "__todos" else (fornecedor or pd_.fornecedor_padrao())
    return pd_.busca_sku(q, forn)


@app.get("/api/compras/pedidos/{pedido_id}")
def compras_pedido(pedido_id: int):
    r = pd_.detalhe(pedido_id)
    if not r:
        raise HTTPException(404, "Pedido não encontrado.")
    return r


@app.get("/api/omie/status")
def omie_status():
    return omie.estado()


@app.post("/api/omie/credenciais")
def omie_credenciais(corpo: dict = Body(...)):
    omie.salvar_credenciais(corpo.get("app_key", ""), corpo.get("app_secret", ""))
    return omie.estado()


@app.post("/api/omie/testar")
def omie_testar():
    r = omie.pesquisar("Pendentes", 1, 1)
    return {"ok": True, "pedidos_pendentes": r.get("nTotalRegistros", 0)}


@app.get("/api/omie/estoque")
def omie_estoque_estado():
    from . import estoque_omie
    return estoque_omie.estado()


@app.put("/api/omie/estoque/{cid}")
def omie_estoque_configurar(cid: str, corpo: dict = Body(...)):
    from . import estoque_omie
    return estoque_omie.configurar(cid, corpo.get("app_key"), corpo.get("app_secret"), corpo.get("campo"), corpo.get("ativo"))


@app.post("/api/omie/estoque/{cid}/testar")
def omie_estoque_testar(cid: str):
    from . import estoque_omie
    return {"local": estoque_omie.achar_local_geral(cid), **estoque_omie.estado()}


@app.post("/api/omie/estoque/sincronizar")
def omie_estoque_sincronizar():
    from . import estoque_omie
    if not any(estoque_omie.credenciais(c["id"])[0] for c in estoque_omie.CONTAS):
        raise HTTPException(400, "Configure as credenciais do Omie 03 e/ou 04 primeiro.")
    estoque_omie.sincronizar_em_segundo_plano()
    return estoque_omie.estado()


@app.get("/api/qive")
def qive_estado():
    from . import qive
    return qive.estado()


@app.put("/api/qive")
def qive_configurar(corpo: dict = Body(...)):
    from . import qive
    try:
        return qive.configurar(corpo.get("api_id"), corpo.get("api_key"), corpo.get("desde"), corpo.get("fornecedores"), bool(corpo.get("recomecar")))
    except ValueError as e:
        raise HTTPException(400, "Data inválida.") from e


@app.post("/api/qive/sincronizar")
def qive_sincronizar():
    from . import qive
    if not qive.credenciais()[0]:
        raise HTTPException(400, "Configure o API ID e a API Key do Qive primeiro.")
    qive.sincronizar_em_segundo_plano()
    return qive.estado()


@app.post("/api/qive/testar")
def qive_testar():
    from . import qive
    try:
        r = qive.pagina(0)
    except qive.ErroQive as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "notas_na_primeira_pagina": len(r.get("data") or []), **qive.estado()}


@app.get("/api/omie/agenda")
def omie_agenda():
    from . import agenda
    return agenda.estado()


@app.put("/api/omie/agenda")
def omie_agenda_definir(corpo: dict = Body(...)):
    from . import agenda
    try:
        agenda.definir_horarios(corpo.get("horarios", ""))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return agenda.estado()


@app.post("/api/omie/sincronizar")
def omie_sincronizar():
    if not omie.credenciais()[0]:
        raise HTTPException(400, "Configure as credenciais do Omie primeiro.")
    omie.sincronizar_em_segundo_plano()
    return omie.estado()


# ----------------------------------------------------------------------------- importação
@app.post("/api/importar/previa")
async def previa(arquivo: UploadFile = File(...), tipo: str | None = Form(None),
                 deposito: str | None = Form(None), data_referencia: str | None = Form(None),
                 modo: str | None = Form(None), fila: str | None = Form(None)):
    conteudo = await arquivo.read()
    if len(conteudo) > MAX_UPLOAD:
        raise HTTPException(413, "Arquivo maior que 30 MB.")
    if not arquivo.filename.lower().endswith((".xlsx", ".xlsm", ".xls", ".csv", ".txt")):
        raise HTTPException(400, "Envie um arquivo .xlsx ou .csv.")
    prep = imp.preparar(arquivo.filename, conteudo)
    t = tipo or prep["tipo"]
    if not t:
        return {"token": prep["token"], "arquivo": arquivo.filename, "tipo": None,
                "colunas": {k: list(v.columns) for k, v in prep["abas"].items()},
                "resumo": None, "mensagem": "Não reconheci o tipo do arquivo. Escolha vendas, estoque ou compras."}
    params = {"deposito": deposito, "data_referencia": data_referencia, "modo": modo}
    sug = None
    if t == "vendas_dia":
        # canal, conta e período já vêm preenchidos (nome do arquivo, último envio, sequência)
        try:
            hoje = date.fromisoformat(data_referencia) if data_referencia else date.today()
            na_tela = json.loads(fila) if fila else []
            sug = imp.sugerir_vendas_dia(arquivo.filename, prep["abas"], hoje, na_tela if isinstance(na_tela, list) else [])
            params.update({k: sug[k] for k in ("canal", "conta", "periodo_inicio", "periodo_fim")})
        except Exception:  # noqa: BLE001 - a sugestão nunca impede a prévia
            sug = None
    r = imp.executar(prep["token"], t, None, params, confirmar=False)
    r["sugestao"] = sug
    return r


@app.post("/api/importar/simular")
def simular(corpo: dict = Body(...)):
    """Refaz a prévia com mapeamento/parâmetros ajustados.
    resugerir_periodo (vendas por período): depois de trocar canal ou conta, o período volta a ser
    o seguinte ao último envio do novo canal/conta."""
    params = dict(corpo.get("parametros") or {})
    origem = None
    if corpo.get("tipo") == "vendas_dia" and corpo.get("resugerir_periodo"):
        try:
            hoje = date.fromisoformat(corpo.get("hoje") or "")
        except ValueError:
            hoje = date.today()
        fila = corpo.get("fila") if isinstance(corpo.get("fila"), list) else []
        (ini, fim), origem = imp.periodo_seguinte_vendas_dia(params.get("canal"), params.get("conta"), hoje, fila)
        params.update(periodo_inicio=ini.isoformat(), periodo_fim=fim.isoformat())
        origem["no_futuro"] = ini > hoje
    r = imp.executar(corpo["token"], corpo["tipo"], corpo.get("mapeamento"), params, confirmar=False)
    if origem:
        r["origem_periodo"] = origem
    return r


@app.post("/api/importar/confirmar")
def confirmar(corpo: dict = Body(...)):
    r = imp.executar(corpo["token"], corpo["tipo"], corpo.get("mapeamento"), corpo.get("parametros", {}), confirmar=True)
    if corpo["tipo"] == "vendas":
        imp.revincular_estoque()
    return r


@app.get("/api/importacoes")
def importacoes():
    with db.engine.connect() as c:
        rows = c.execute(select(db.importacoes).order_by(db.importacoes.c.id.desc())).all()
    out = []
    for r in rows:
        res = json.loads(r.resumo) if r.resumo else None
        out.append({"id": r.id, "tipo": r.tipo, "arquivo": r.arquivo, "criado_em": r.criado_em.isoformat() if r.criado_em else None,
                    "data_referencia": r.data_referencia.isoformat() if r.data_referencia else None,
                    "deposito": r.deposito, "modo": r.modo, "status": r.status, "resumo": res})
    return out


@app.post("/api/importacoes/{imp_id}/desfazer")
def desfazer(imp_id: int):
    r = imp.desfazer(imp_id)
    imp.revincular_estoque()
    return r


@app.get("/api/importacoes/{imp_id}/arquivo")
def baixar(imp_id: int):
    with db.engine.connect() as c:
        r = c.execute(select(db.importacoes).where(db.importacoes.c.id == imp_id)).first()
    if not r or not r.armazenado_em or not Path(r.armazenado_em).exists():
        raise HTTPException(404, "Arquivo não encontrado.")
    return FileResponse(r.armazenado_em, filename=r.arquivo)


# ----------------------------------------------------------------------------- vínculos e qualidade
@app.get("/api/vinculos/pendentes")
def pendentes(busca: str = "", limite: int = 200):
    d = ind.dados()
    E = ind.estoque_em(d)
    if E.empty:
        return {"itens": [], "total": 0}
    E = E[(E["vinculo"] == "proprio") & (E["qtd"] > 0)]
    g = E.groupby("codigo").agg(quantidade=("qtd", "sum"), depositos=("deposito", lambda s: sorted(set(s)))).reset_index()
    if busca:
        g = g[g["codigo"].str.contains(busca, case=False, regex=False)]
    g = g.sort_values("quantidade", ascending=False)
    with db.engine.connect() as c:
        manuais = [dict(r._mapping) for r in c.execute(select(db.vinculos).order_by(db.vinculos.c.criado_em.desc()))]
    return {"total": int(len(g)), "quantidade": ind._f(g["quantidade"].sum(), 0),
            "itens": g.head(limite).to_dict("records"), "manuais": manuais}


@app.get("/api/skus")
def skus(busca: str = "", limite: int = 30):
    d = ind.dados()
    s = sorted(set(d.V["sku"]) | set(d.P["sku"]))
    if busca:
        s = [x for x in s if busca.upper() in x.upper()]
    return s[:limite]


@app.post("/api/vinculos")
def criar_vinculo(corpo: dict = Body(...)):
    codigo, sku = (corpo.get("codigo") or "").strip(), (corpo.get("sku") or "").strip().upper()
    if not codigo or not sku:
        raise HTTPException(400, "Informe código e SKU.")
    with db.engine.begin() as c:
        c.execute(delete(db.vinculos).where(db.vinculos.c.codigo == codigo))
        c.execute(insert(db.vinculos).values(codigo=codigo, sku=sku, tamanho=corpo.get("tamanho") or None))
    return imp.revincular_estoque()


@app.delete("/api/vinculos/{codigo}")
def remover_vinculo(codigo: str):
    with db.engine.begin() as c:
        c.execute(delete(db.vinculos).where(db.vinculos.c.codigo == codigo))
    return imp.revincular_estoque()


@app.get("/api/qualidade")
def qualidade():
    """Inconsistências encontradas nos dados (para conferência)."""
    d = ind.dados()
    out = []
    if not d.V.empty and not d.E.empty:
        E = ind.estoque_em(d)
        cod_est = set(E["sku"])
        vend = d.V[d.V["categoria"] == "calcado"].groupby("sku")["un"].sum()
        sem = vend[~vend.index.isin(cod_est)].sort_values(ascending=False)
        if len(sem):
            out.append({"tipo": "aviso", "titulo": f"{len(sem)} SKUs de calçado vendidos sem código no estoque",
                        "itens": [f"{k} ({v:,.0f} un. no histórico)".replace(",", ".") for k, v in sem.head(20).items()]})
        prop = E[(E["vinculo"] == "proprio") & (E["qtd"] > 0)]
        if len(prop):
            out.append({"tipo": "info", "titulo": f"{prop['codigo'].nunique()} códigos de estoque com saldo que não correspondem a SKU vendido",
                        "itens": ["Tratados como produtos próprios (sem histórico de venda). Vincule em Dados › Vínculos se forem variações de um SKU vendido."]})
    if not d.C.empty:
        C = d.C
        sm = C[C["modelo"].isna()]
        if len(sm):
            out.append({"tipo": "aviso", "titulo": f"{len(sm)} linhas de compra com SKU fora do padrão",
                        "itens": sorted({f"{r.data:%d/%m/%Y} SKU '{r.sku_original}'" for r in sm.itertuples()})[:15]})
        sq = C[C["quantidade"].isna()]
        if len(sq):
            out.append({"tipo": "aviso", "titulo": f"{sq['nota_chave'].nunique()} notas sem quantidade ({len(sq)} linhas)",
                        "itens": ["Reimporte as compras com a coluna de quantidade (modo 'substituir período')."]})
        nm = C[(C["valor_nota"] > C["valor_produtos"] * 1.0001)].drop_duplicates("nota_chave")
        if len(nm):
            out.append({"tipo": "aviso", "titulo": f"{len(nm)} nota(s) com valor total maior que o dos produtos",
                        "itens": [f"{r.data:%d/%m/%Y}: nota R$ {r.valor_nota:.2f} × produtos R$ {r.valor_produtos:.2f}" for r in nm.itertuples()][:10]})
    with db.engine.connect() as c:
        for r in c.execute(select(db.importacoes).where((db.importacoes.c.tipo == "vendas") & (db.importacoes.c.status == "ok"))):
            res = json.loads(r.resumo or "{}")
            aj = (res.get("detalhes") or {}).get("skus_ajustados")
            if aj:
                out.append({"tipo": "info", "titulo": f"Importação #{r.id}: {len(aj)} SKU(s) de venda com tamanho embutido, somados ao SKU base",
                            "itens": [f"{k} → {v}" for k, v in aj.items()]})
    return out


@app.get("/api/estoque-externo")
def listar_externos():
    d = ind.dados()
    rot = ind._rotulos(d, "sku")
    return [{"sku": s, "descricao": rot.get(s, "")} for s in sorted(d.externos)]


@app.put("/api/estoque-externo")
def salvar_externos(corpo: dict = Body(...)):
    skus = sorted({str(s).strip().upper() for s in corpo.get("skus", []) if str(s).strip()})
    with db.engine.begin() as c:
        c.execute(delete(db.configuracoes).where(db.configuracoes.c.chave == "estoque_externo"))
        c.execute(insert(db.configuracoes).values(chave="estoque_externo", valor=db.dumps(skus)))
    return {"skus": skus}


_INICIO = datetime.now()


@app.get("/api/sistema")
def sistema():
    """Diagnóstico: versão, banco, ambiente e últimas importações (ajuda a entender por que algo não aparece)."""
    import os as _os
    from .versao import VERSAO
    sqlite = db.DB_URL.startswith("sqlite")
    publicado = _os.environ.get("REPLIT_DEPLOYMENT") == "1" or bool(_os.environ.get("RENDER"))
    with db.engine.connect() as c:
        def ultima(tipo):
            r = c.execute(select(db.importacoes).where((db.importacoes.c.tipo == tipo) & (db.importacoes.c.status == "ok"))
                          .order_by(db.importacoes.c.id.desc()).limit(1)).first()
            return None if not r else {"id": r.id, "arquivo": r.arquivo, "em": str(r.criado_em)[:16] if getattr(r, "criado_em", None) else None,
                                       "data_referencia": str(r.data_referencia) if r.data_referencia else None, "detalhe": r.deposito}
        n_imp = c.execute(select(func.count()).select_from(db.importacoes)).scalar()
        n_lanc = c.execute(select(func.count()).select_from(db.vendas_lancamentos)).scalar()
        dias = c.execute(select(func.min(db.vendas_lancamentos.c.data_inicio), func.max(db.vendas_lancamentos.c.data_fim))).first()
        mensal = c.execute(select(func.max(db.vendas_mensais.c.mes))).scalar()
        ult_dia, ult_mensal, ult_est = ultima("vendas_dia"), ultima("vendas"), ultima("estoque")
    avisos = []
    if sqlite and publicado:
        avisos.append("O app publicado está usando o banco local (SQLite), que é apagado quando o servidor reinicia ou é republicado: "
                      "as importações somem. Crie o banco no Neon e coloque o endereço dele na variável DATABASE_URL.")
    if _os.environ.get("RENDER") and not _os.environ.get("CRON_TOKEN"):
        avisos.append("Sem CRON_TOKEN: o agendador externo das 12h não consegue acordar o servidor gratuito do Render.")
    elif sqlite and _os.environ.get("REPL_ID"):
        avisos.append("Este Repl usa o banco local (SQLite). O app publicado tem outro banco: o que você importa aqui não aparece lá, "
                      "e vice-versa. Importe sempre no mesmo lugar onde consulta o BI, de preferência com PostgreSQL.")
    from . import estoque_omie
    sem = [f"Omie {c['id']} ({c['deposito']})" for c in estoque_omie.CONTAS if not estoque_omie.credenciais(c["id"])[0]]
    if sem:
        avisos.append(f"Estoque sem conexão com {' e '.join(sem)}: configure em Dados › Omie para o estoque vir da API.")
    elif ult_est and ult_est.get("data_referencia") and ult_est["data_referencia"] < (date.today().fromordinal(date.today().toordinal() - 1)).isoformat():
        avisos.append(f"O estoque não é atualizado desde {ult_est['data_referencia']}. Veja Dados › Omie.")
    from . import qive as _qive
    qv = _qive.estado()
    est_ok = [c["deposito"] for c in estoque_omie.CONTAS if estoque_omie.credenciais(c["id"])[0]]
    fontes = [
        {"dado": "Vendas", "origem": "Planilha", "detalhe": "relatório mensal + listas de vendidos do dia",
         "api": "sem API ainda (as notas do Mercado Livre e da Shopee não chegam ao Qive)", "ok": None},
        {"dado": "Estoque", "origem": "API do Omie" if est_ok else "Planilha (sem API configurada)",
         "detalhe": ("Omie 03 e 04: " + ", ".join(est_ok)) if est_ok else "configure em Dados › Omie", "api": "Omie 03 (Unlock) e Omie 04 (Juatuba)", "ok": len(est_ok) == 2},
        {"dado": "Compras", "origem": "API do Qive" + (" + planilhas antigas" if qv["linhas"] else "") if qv["configurado"] else "Planilha (sem API configurada)",
         "detalhe": f"{qv['linhas']} itens de nota vindos do Qive" if qv["configurado"] else "configure em Dados › Qive", "api": "Qive (NF-e recebidas)", "ok": qv["configurado"]},
        {"dado": "Pedidos de compra", "origem": "API do Omie" if omie.credenciais()[0] else "Instantâneo inicial (sem API configurada)",
         "detalhe": "PedidoCompra", "api": "Omie", "ok": bool(omie.credenciais()[0])},
    ]
    return {
        "fontes": fontes,
        "versao": VERSAO, "banco": "SQLite (arquivo local)" if sqlite else "PostgreSQL", "banco_persistente": not sqlite,
        "ambiente": ("Render" if _os.environ.get("RENDER") else "App publicado (deployment)") if publicado else ("Repl de desenvolvimento" if _os.environ.get("REPL_ID") else "Local"),
        "servidor_iniciado_em": _INICIO.strftime("%Y-%m-%d %H:%M"), "agora": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "importacoes": n_imp, "lancamentos_diarios": n_lanc,
        "listas_dia_de": str(dias[0]) if dias and dias[0] else None, "listas_dia_ate": str(dias[1]) if dias and dias[1] else None,
        "ultima_lista_dia": ult_dia, "ultimo_relatorio_mensal": ult_mensal,
        "ultimo_mes_vendas": str(mensal)[:7] if mensal else None, "ultimo_estoque": ult_est,
        "avisos": avisos,
    }


@app.get("/api/linha")
def linha_marcas():
    from . import linha as _linha
    return {"marcas": _linha.marcas()}


@app.put("/api/linha")
def linha_definir(corpo: dict = Body(...)):
    """{chaves: [...], em_linha: true | false | null (limpa)}"""
    from . import linha as _linha
    chaves = corpo.get("chaves") or []
    if not chaves:
        raise HTTPException(400, "Informe ao menos um produto.")
    if len(chaves) > 5000:
        raise HTTPException(400, "No máximo 5000 produtos por vez.")
    n = _linha.definir(chaves, corpo.get("em_linha"))
    return {"atualizados": n, **linha_marcas()}


@app.get("/api/linha/produtos")
def linha_produtos():
    """Todos os modelos (e produtos fora do padrão) com venda, estoque e compra, para marcar em linha."""
    from . import linha as _linha
    d = ind.dados_base()
    m = _linha.marcas()
    base = ind.meses_base_demanda(d)
    V = d.V[d.V["mes"].isin(base)] if base else d.V.iloc[0:0]
    vend = V.groupby("k_modelo")["un"].sum()
    ult_venda = d.V[d.V["un"] > 0].groupby("k_modelo")["mes"].max()
    est = ind._estoque_por_chave(d, "todos", "modelo")
    est = est["est"] if "est" in est else pd.Series(dtype=float)
    C = d.C if d.C is not None else pd.DataFrame(columns=["modelo", "data"])
    ult_compra = C.dropna(subset=["modelo"]).groupby("modelo")["data"].max()
    cat = d.V.drop_duplicates("k_modelo").set_index("k_modelo")["categoria"] if not d.V.empty else pd.Series(dtype=str)
    chaves = set(d.V["k_modelo"]) | set(est.index) | set(ult_compra.index)
    rot = ind._rotulos(d, "modelo")
    itens = []
    for k in chaves:
        if not k or str(k) == "nan":
            continue
        uc = ult_compra.get(k)
        uv = ult_venda.get(k)
        e = _linha.estado(k, m)
        itens.append({"chave": k, "descricao": rot.get(k, ""), "categoria": cat.get(k, "calcado" if "." in str(k) else "outro"),
                      "vendas_3m": ind._f(vend.get(k, 0), 0), "estoque": ind._f(est.get(k, 0), 0),
                      "ultima_venda": uv.strftime("%Y-%m") if uv is not None and not pd.isna(uv) else None,
                      "ultima_compra": uc.strftime("%Y-%m-%d") if uc is not None and not pd.isna(uc) else None,
                      "estado": "em_linha" if e is True else "fora" if e is False else "sem_marcacao"})
    itens.sort(key=lambda x: (-(x["vendas_3m"] or 0), -(x["estoque"] or 0), x["chave"]))
    cont = {k: sum(1 for x in itens if x["estado"] == k) for k in _linha.MODOS}
    return {"itens": itens, "contagem": cont}


@app.get("/api/analise/prompt")
def analise_prompt(inicio: str | None = None, fim: str | None = None, categoria: str = "calcado", detalhe: str = "completo"):
    """Texto com os números do BI para colar numa conversa com o Claude (analista)."""
    import sys
    from . import analise
    _validar("modelo", categoria)
    return analise.gerar(sys.modules[__name__], inicio, fim, categoria, "resumido" if detalhe == "resumido" else "completo")


@app.get("/api/curva")
def curva_abc(categoria: str = "calcado", inicio: str | None = None, fim: str | None = None):
    """Curva ABC por modelo: resumo por classe, pontos da curva de Pareto e a lista de modelos."""
    from . import abc as _abc
    from . import linha as _linha
    base = ind.dados_base()
    r = _abc.classificar(base)
    g = r["tabela"].copy()
    if categoria != "todos" and not g.empty:
        g = g[g["cat"] == categoria]
    if _linha.MODO.get() and not g.empty:
        g = g[_linha.mascara(pd.Series(g.index, index=g.index), _linha.MODO.get())]
    est = ind._estoque_por_chave(base, "todos", "modelo")
    est = est["est"] if "est" in est else pd.Series(dtype=float)
    dias = ind.dias_periodo(base, r["meses"]) if r["meses"] else 0
    try:
        _, I = pd_.carregar(None)
        rec = I.groupby("modelo")["a_receber"].sum() if not I.empty else pd.Series(dtype=float)
    except Exception:  # noqa: BLE001
        rec = pd.Series(dtype=float)
    rot = ind._rotulos(base, "modelo")
    marcas = _linha.marcas()
    # vendas de cada modelo no período escolhido no topo x período anterior de mesma duração
    # (um mês contra o mês anterior); com mês parcial, compara pela média por dia
    try:
        per_m = ind.resolver_periodo(base, inicio, fim)
    except Exception:  # noqa: BLE001
        per_m = []
    per_a = ind.periodo_anterior(base, per_m) if per_m else None
    usa_dia = bool(per_m and per_a and (any(m in base.parciais for m in per_m) or any(m in base.parciais for m in per_a)))
    dias_p = ind.dias_periodo(base, per_m) if per_m else 0
    dias_a = ind.dias_periodo(base, per_a) if per_a else 0
    Vp = base.V[base.V["mes"].isin(per_m)].groupby("k_modelo")[["fat", "un"]].sum() if per_m else None
    Va = base.V[base.V["mes"].isin(per_a)].groupby("k_modelo")[["fat", "un"]].sum() if per_a else None
    col = "fat" if r["criterio"] == "faturamento" else "un"

    def var(atual, anterior):
        if usa_dia:
            atual, anterior = (atual / dias_p if dias_p else 0), (anterior / dias_a if dias_a else 0)
        return ind._pct(atual, anterior) if anterior else None

    itens = []
    for k, x in g.iterrows():
        e = float(est.get(k, 0) or 0)
        dia = float(x.un) / dias if dias else 0
        itens.append({"modelo": k, "descricao": rot.get(k, ""), "categoria": x["cat"], "classe": x["classe"],
                      "faturamento": ind._f(x.fat), "unidades": ind._f(x.un, 0), "participacao": ind._f(x.part, 2),
                      "acumulado": ind._f(x.acum, 1), "estoque": ind._f(e, 0),
                      "cobertura": ind._f(e / dia, 0) if dia and e > 0 else (0 if e <= 0 else None),
                      "a_receber": ind._f(rec.get(k, 0), 0),
                      "linha": "em_linha" if _linha.estado(k, marcas) is True else "fora" if _linha.estado(k, marcas) is False else None,
                      "periodo_valor": ind._f(Vp[col].get(k, 0)) if Vp is not None else None,
                      "periodo_var": var(float(Vp[col].get(k, 0)), float(Va[col].get(k, 0))) if Vp is not None and Va is not None else None})
    # estoque de modelos sem venda no período base (fora da curva)
    est_cat = ind._estoque_por_chave(base, categoria, "modelo")
    est_cat = est_cat["est"] if "est" in est_cat else pd.Series(dtype=float)
    sem_venda = [k for k in est_cat.index if est_cat.get(k, 0) > 0 and k not in r["classes"]]
    resumo = []
    tot_fat = sum(i["faturamento"] or 0 for i in itens) or 1
    tot_un = sum(i["unidades"] or 0 for i in itens) or 1
    for cls in ("A", "B", "C"):
        xs = [i for i in itens if i["classe"] == cls]
        est_c = sum(i["estoque"] or 0 for i in xs)
        un_c = sum(i["unidades"] or 0 for i in xs)
        resumo.append({"classe": cls, "modelos": len(xs), "pct_modelos": ind._f(len(xs) / max(len(itens), 1) * 100, 1),
                       "faturamento": ind._f(sum(i["faturamento"] or 0 for i in xs)), "pct_faturamento": ind._f(sum(i["faturamento"] or 0 for i in xs) / tot_fat * 100, 1),
                       "unidades": ind._f(un_c, 0), "pct_unidades": ind._f(un_c / tot_un * 100, 1),
                       "estoque": ind._f(est_c, 0), "cobertura": ind._f(est_c / (un_c / dias), 0) if dias and un_c else None,
                       "zerados": sum(1 for i in xs if (i["estoque"] or 0) <= 0),
                       "zerados_sem_pedido": sum(1 for i in xs if (i["estoque"] or 0) <= 0 and not i["a_receber"]),
                       "a_receber": ind._f(sum(i["a_receber"] or 0 for i in xs), 0),
                       "periodo_faturamento": ind._f(sum(float(Vp["fat"].get(i["modelo"], 0)) for i in xs)) if Vp is not None else None,
                       "periodo_unidades": ind._f(sum(float(Vp["un"].get(i["modelo"], 0)) for i in xs), 0) if Vp is not None else None,
                       "periodo_var": var(sum(float(Vp[col].get(i["modelo"], 0)) for i in xs), sum(float(Va[col].get(i["modelo"], 0)) for i in xs))
                       if Vp is not None and Va is not None else None})
    n = len(itens)
    pareto = [{"pct_itens": ind._f((j + 1) / n * 100, 1), "pct_fat": i["acumulado"], "itens": j + 1, "classe": i["classe"]}
              for j, i in enumerate(itens) if n <= 80 or j == 0 or j == n - 1 or j % max(1, n // 80) == 0]
    comparacao = None
    if per_m:
        rot_p = ind.mes_label(per_m[0]) + ("" if len(per_m) == 1 else f" a {ind.mes_label(per_m[-1])}")
        rot_a = (ind.mes_label(per_a[0]) + ("" if len(per_a) == 1 else f" a {ind.mes_label(per_a[-1])}")) if per_a else None
        comparacao = {"periodo": rot_p, "anterior": rot_a, "base": "média por dia" if usa_dia else "total", "criterio": r["criterio"]}
    return {"config": r["cfg"], "comparacao": comparacao, "meses": [ind.mes_label(r["meses"][0]), ind.mes_label(r["meses"][-1])] if r["meses"] else None,
            "criterio": r["criterio"], "resumo": resumo, "pareto": pareto, "itens": itens,
            "sem_venda": {"modelos": len(sem_venda), "estoque": ind._f(sum(est_cat.get(k, 0) for k in sem_venda), 0)}, "categoria": categoria}


@app.put("/api/curva/config")
def curva_config(corpo: dict = Body(...), categoria: str = "calcado", inicio: str | None = None, fim: str | None = None):
    from . import abc as _abc
    try:
        _abc.salvar_config(**{k: corpo.get(k) for k in ("meses", "criterio", "limite_a", "limite_b") if corpo.get(k) is not None})
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return curva_abc(categoria, inicio, fim)


# ----------------------------------------------------------------------------- vendas por semana
def _cfg_get(chave):
    with db.engine.connect() as c:
        return c.execute(select(db.configuracoes.c.valor).where(db.configuracoes.c.chave == chave)).scalar()


def _cfg_set(chave, valor):
    with db.engine.begin() as c:
        c.execute(delete(db.configuracoes).where(db.configuracoes.c.chave == chave))
        if valor is not None:
            c.execute(insert(db.configuracoes).values(chave=chave, valor=valor))


@app.get("/api/vendas/semanal")
def vendas_semanal_estado():
    d = ind.dados()
    v = _cfg_get("vendas_semanais_desde")
    return {"desde": None if v in (None, "desligado") else v, "importadas": ind.semanas_importadas(d)}


@app.put("/api/vendas/semanal")
def vendas_semanal_config(corpo: dict = Body(...)):
    """{desde: 'AAAA-MM' | null}: a partir desse mês o relatório mensal deixa de valer (não é apagado)."""
    v = corpo.get("desde")
    if v:
        try:
            date.fromisoformat(v + "-01")
        except ValueError as e:
            raise HTTPException(400, "Mês inválido (use AAAA-MM).") from e
    _cfg_set("vendas_semanais_desde", v or "desligado")
    return vendas_semanal_estado()


@app.get("/api/vendas/semanas")
def vendas_semanas(mes: str, categoria: str = "calcado"):
    _validar("modelo", categoria)
    try:
        date.fromisoformat(mes + "-01")
    except ValueError as e:
        raise HTTPException(400, "Mês inválido (use AAAA-MM).") from e
    return ind.vendas_semanas(ind.dados(), mes, categoria)


# ----------------------------------------------------------------------------- SKUs considerados
@app.get("/api/skus-bi")
def skus_lista():
    """Todos os SKUs lidos (vendas, estoque, compras, listas do dia), com os excluídos à parte."""
    d = ind.dados_base()
    base = ind.meses_base_demanda(d)
    V3 = d.V[d.V["mes"].isin(base)] if base else d.V.iloc[0:0]
    vend = V3.groupby("sku").agg(un=("un", "sum"), fat=("fat", "sum"))
    vend_all = d.V.groupby("sku")["un"].sum()
    ult = d.V[d.V["un"] > 0].groupby("sku")["mes"].max()
    E = ind.estoque_em(d)
    est = E.groupby("sku")["qtd"].sum() if not E.empty else pd.Series(dtype=float)
    em_compras = set(d.C["sku"].dropna()) if d.C is not None and "sku" in d.C else set()
    em_listas = set(d.L["sku"]) if d.L is not None and not d.L.empty else set()
    desc = dict(zip(d.produtos["sku"], d.produtos["descricao"])) if not d.produtos.empty else {}
    desc.update(d.V.drop_duplicates("sku").set_index("sku")["descricao"].dropna().to_dict())
    from .produto import interpretar as _interp
    chaves = set(vend_all.index) | set(est.index) | em_listas
    itens = []
    for k in chaves:
        if not k or str(k) == "nan":
            continue
        p = _interp(str(k), com_tamanho=False)
        u = ult.get(k)
        fontes = [x for x, ok in (("vendas", k in vend_all.index), ("estoque", k in est.index), ("compras", k in em_compras), ("listas do dia", k in em_listas)) if ok]
        itens.append({"sku": k, "descricao": desc.get(k, ""), "categoria": p.categoria, "modelo": p.modelo if p.categoria == "calcado" else None,
                      "vendas_3m": ind._f(vend["un"].get(k, 0), 0), "faturamento_3m": ind._f(vend["fat"].get(k, 0)),
                      "vendas_total": ind._f(vend_all.get(k, 0), 0), "ultima_venda": u.strftime("%Y-%m") if u is not None and not pd.isna(u) else None,
                      "estoque": ind._f(est.get(k, 0), 0), "fontes": fontes, "excluido": False})
    with db.engine.connect() as c:
        exc = list(c.execute(select(db.skus_excluidos)))
    for x in exc:
        p = _interp(str(x.sku), com_tamanho=False)
        itens.append({"sku": x.sku, "descricao": desc.get(x.sku, ""), "categoria": p.categoria, "modelo": p.modelo if p.categoria == "calcado" else None,
                      "vendas_3m": None, "faturamento_3m": None, "vendas_total": None, "ultima_venda": None, "estoque": None,
                      "fontes": [], "excluido": True, "excluido_em": str(x.excluido_em)[:16] if x.excluido_em else None})
    itens.sort(key=lambda x: (x["excluido"], -(x["vendas_3m"] or 0), -(x["estoque"] or 0), x["sku"]))
    return {"itens": itens, "total": len(itens), "excluidos": len(exc)}


@app.put("/api/skus-bi/excluidos")
def skus_excluir(corpo: dict = Body(...)):
    """{skus: [...], excluir: true|false}"""
    skus = [str(x).strip() for x in (corpo.get("skus") or []) if str(x).strip()]
    if not skus:
        raise HTTPException(400, "Informe ao menos um SKU.")
    if len(skus) > 10000:
        raise HTTPException(400, "No máximo 10.000 SKUs por vez.")
    with db.engine.begin() as c:
        c.execute(delete(db.skus_excluidos).where(db.skus_excluidos.c.sku.in_(skus)))
        if corpo.get("excluir", True):
            agora = datetime.utcnow()
            c.execute(insert(db.skus_excluidos), [{"sku": s_[:160], "excluido_em": agora} for s_ in skus])
    return {"alterados": len(skus)}


@app.get("/api/modelos-por-cabedal")
def listar_modelos_por_cabedal():
    ind.carregar_modelos_por_cabedal(ler=True)
    d = ind.dados()
    from .produto import modelos_por_cabedal
    mods = modelos_por_cabedal()
    out = []
    for m in mods:
        V = d.V[d.V["sku"].str.startswith(m + "-")] if not d.V.empty else d.V
        out.append({"modelo": m, "separados": sorted(V["k_modelo"].unique().tolist()) if not V.empty else []})
    return {"modelos": out}


@app.put("/api/modelos-por-cabedal")
def salvar_modelos_por_cabedal(corpo: dict = Body(...)):
    import re as _re
    mods = sorted({str(x).strip() for x in corpo.get("modelos", []) if str(x).strip()})
    ruins = [m for m in mods if not _re.match(r"^\d{4}\.\d{3,4}$", m)]
    if ruins:
        raise HTTPException(400, f"Modelo inválido: {', '.join(ruins)}. Use o formato 7208.101.")
    with db.engine.begin() as c:
        c.execute(delete(db.configuracoes).where(db.configuracoes.c.chave == "modelos_por_cabedal"))
        c.execute(insert(db.configuracoes).values(chave="modelos_por_cabedal", valor=db.dumps(mods)))
    ind.carregar_modelos_por_cabedal(ler=True)
    return listar_modelos_por_cabedal()


@app.get("/api/regras")
def regras():
    return {
        "produto": "Calçados: MODELO (XXXX.XXX) - CABEDAL - COR [- TAMANHO]; '-' e '.' são equivalentes após o modelo; "
                   "com um único segmento após o modelo, ele é a cor (cabedal não informado). Demais produtos: o próprio SKU.",
        "exemplo": {c: vars(interpretar(c, com_tamanho=True)) for c in ("7208.101-29516-15745-36", "1185.702-15745-34", "7208.100.29516.109603-39")},
        "cobertura_critica_dias": ind.COBERTURA_CRITICA, "cobertura_excesso_dias": ind.COBERTURA_EXCESSO,
        "janela_demanda_meses": ind.JANELA_DEMANDA_MESES,
    }


@app.get("/api/saude")
def saude():
    return {"ok": True, "banco": db.DB_URL.split(":", 1)[0]}


# ----------------------------------------------------------------------------- frontend
DIST = db.RAIZ / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{caminho:path}")
    def spa(caminho: str):
        alvo = DIST / caminho
        if caminho and alvo.is_file():
            return FileResponse(alvo)
        # sem cache: depois de atualizar o BI o navegador busca a interface nova
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
