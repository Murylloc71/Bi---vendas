"""Compras pela API do Qive (Arquivei): NF-e recebidas nos CNPJs da Uai Comprei.

Substitui as planilhas de compras. Cada item de nota vira uma linha de compras, como a planilha:
    SKU      -> do texto do item ("tam: 34 1214.1075.5881.15758" -> 1214.1075.5881.15758-34);
                sem ele, pelo EAN já visto nas compras/estoque; senão, o código do fornecedor
    preço    -> valor unitário e preço com desconto ((valor do item − desconto) ÷ quantidade)
    PE/PROG  -> mesma regra da planilha: preço com desconto = valor unitário -> pronta-entrega
Ficam de fora: transferências entre empresas Uai (emitente 24.410.480), notas que não são de venda
do fornecedor (CFOP fora de x101/x102/x401/x403/x405) e notas com emissão anterior a "desde".

Credenciais: Secrets QIVE_API_ID e QIVE_API_KEY, ou salvas em Dados › Qive.
API: GET {base}/v1/nfe/received?cursor=N&limit=50, cabeçalhos X-API-ID / X-API-KEY; resposta
{"data": [{"access_key", "xml" (base64)}], "page": {"next"}, "count"}. O cursor é guardado e a
próxima sincronização continua de onde parou.
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime

from sqlalchemy import delete, insert, select

from . import db
from .produto import interpretar

NS = {"n": "http://www.portalfiscal.inf.br/nfe"}
UAI = "24410480"                      # raiz do CNPJ das empresas Uai Comprei
CFOP_COMPRA = {"101", "102", "401", "403", "405"}
POR_PAGINA = 50
MAX_PAGINAS = 400                     # por sincronização; o resto fica para a próxima
RE_SKU = re.compile(r"tam:?\s*([0-9A-Za-z]{1,4})\s+(\d{4}\.\d{3,4}(?:[.\-]\d+){1,3})", re.I)

_lock = threading.Lock()
_estado = {"rodando": False, "progresso": None, "erro": None, "inicio": None, "fim": None}


class ErroQive(Exception):
    pass


# ----------------------------------------------------------------------------- configuração
def _cfg() -> dict:
    with db.engine.connect() as c:
        v = c.execute(select(db.configuracoes.c.valor).where(db.configuracoes.c.chave == "qive")).scalar()
    return json.loads(v) if v else {}


def _salvar(cfg: dict):
    with db.engine.begin() as c:
        c.execute(delete(db.configuracoes).where(db.configuracoes.c.chave == "qive"))
        c.execute(insert(db.configuracoes).values(chave="qive", valor=json.dumps(cfg, default=str)))


def credenciais() -> tuple[str, str, str]:
    i, k = os.environ.get("QIVE_API_ID", "").strip(), os.environ.get("QIVE_API_KEY", "").strip()
    if i and k:
        return i, k, "ambiente"
    cfg = _cfg()
    if cfg.get("api_id") and cfg.get("api_key"):
        return cfg["api_id"], cfg["api_key"], "banco"
    return "", "", ""


def configurar(api_id=None, api_key=None, desde=None, fornecedores=None, recomecar=False):
    cfg = _cfg()
    if api_id is not None and api_key is not None:
        if api_id.strip() and api_key.strip():
            cfg.update(api_id=api_id.strip(), api_key=api_key.strip())
        else:
            cfg.pop("api_id", None); cfg.pop("api_key", None)
    if desde:
        date.fromisoformat(desde)
        cfg["desde"] = desde
    if fornecedores is not None:
        cfg["fornecedores"] = fornecedores.strip()
    if recomecar:
        cfg.pop("cursor", None)
    _salvar(cfg)
    return estado()


def base_url() -> str:
    return os.environ.get("QIVE_API_URL", "https://api.arquivei.com.br").rstrip("/")


# ----------------------------------------------------------------------------- API
def _get(url: str, tentativas=4) -> dict:
    i, k, _ = credenciais()
    if not i:
        raise ErroQive("Credenciais do Qive não configuradas.")
    espera = 2.0
    for n in range(tentativas):
        req = urllib.request.Request(url, headers={"X-API-ID": i, "X-API-KEY": k, "Content-Type": "application/json",
                                                   "User-Agent": "bi-vendas/2.0"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise ErroQive("O Qive recusou as credenciais (confira API ID e API Key).") from e
            if n < tentativas - 1 and e.code in (429, 500, 502, 503, 504):
                time.sleep(espera); espera *= 2
                continue
            raise ErroQive(f"Qive respondeu HTTP {e.code}.") from e
        except urllib.error.URLError as e:
            if n < tentativas - 1:
                time.sleep(espera); espera *= 2
                continue
            raise ErroQive(f"Sem conexão com o Qive: {e.reason}") from e
    raise ErroQive("Falha ao consultar o Qive.")


def pagina(cursor: int) -> dict:
    return _get(f"{base_url()}/v1/nfe/received?" + urllib.parse.urlencode({"cursor": cursor, "limit": POR_PAGINA}))


# ----------------------------------------------------------------------------- XML
def _t(el, caminho, padrao=None):
    x = el.find(caminho, NS) if el is not None else None
    return x.text.strip() if x is not None and x.text else padrao


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ler_nota(xml_txt: str) -> dict | None:
    """Lê o XML da NF-e (nfeProc ou NFe) e devolve cabeçalho + itens."""
    raiz = ET.fromstring(xml_txt)
    inf = raiz.find(".//n:infNFe", NS)
    if inf is None:
        return None
    ide, emit, dest, tot = (inf.find(f"n:{x}", NS) for x in ("ide", "emit", "dest", "total/n:ICMSTot"))
    dt = _t(ide, "n:dhEmi") or _t(ide, "n:dEmi")
    itens = []
    for det in inf.findall("n:det", NS):
        p = det.find("n:prod", NS)
        itens.append({"item": det.get("nItem"), "codigo": _t(p, "n:cProd"), "ean": _t(p, "n:cEAN"), "descricao": _t(p, "n:xProd"),
                      "cfop": _t(p, "n:CFOP"), "quantidade": _f(_t(p, "n:qCom")), "valor_unitario": _f(_t(p, "n:vUnCom")),
                      "valor_total": _f(_t(p, "n:vProd")), "desconto": _f(_t(p, "n:vDesc")) or 0.0,
                      "info": _t(det, "n:infAdProd") or ""})
    return {"chave": (inf.get("Id") or "")[-44:], "numero": _t(ide, "n:nNF"), "serie": _t(ide, "n:serie"),
            "data": date.fromisoformat(dt[:10]) if dt else None, "natureza": _t(ide, "n:natOp"),
            "emitente_cnpj": _t(emit, "n:CNPJ") or _t(emit, "n:CPF") or "", "emitente": _t(emit, "n:xNome") or "",
            "destinatario_cnpj": _t(dest, "n:CNPJ") or _t(dest, "n:CPF") or "",
            "valor_nota": _f(_t(tot, "n:vNF")), "valor_produtos": _f(_t(tot, "n:vProd")), "itens": itens}


def sku_do_item(it: dict, por_ean: dict) -> str:
    m = RE_SKU.search(it.get("info") or "")
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    if it.get("ean") and it["ean"] in por_ean:
        return por_ean[it["ean"]]
    return it.get("codigo") or ""


def linhas_compra(nota: dict, por_ean: dict, desde: date, fornecedores: list[str]) -> tuple[list[dict], str | None]:
    """Itens da nota no formato da tabela de compras. Segundo valor: motivo de ter ignorado a nota."""
    if not nota or not nota.get("data"):
        return [], "XML sem data"
    if not str(nota["destinatario_cnpj"]).startswith(UAI):
        return [], "destinatário não é Uai Comprei"
    if str(nota["emitente_cnpj"]).startswith(UAI):
        return [], "transferência entre empresas Uai"
    if nota["data"] < desde:
        return [], "anterior à data inicial"
    if fornecedores and not any(f.lower() in nota["emitente"].lower() or nota["emitente_cnpj"].startswith(f) for f in fornecedores):
        return [], "fornecedor fora do filtro"
    out = []
    for it in nota["itens"]:
        cf = (it.get("cfop") or "")[-3:]
        q, vu = it.get("quantidade"), it.get("valor_unitario")
        if cf not in CFOP_COMPRA or not q or not vu:
            continue
        pdsc = ((it.get("valor_total") or q * vu) - (it.get("desconto") or 0)) / q
        sku_o = sku_do_item(it, por_ean)
        p = interpretar(sku_o, com_tamanho="auto")
        forn = nota["emitente"][:200]
        out.append({
            "linha_chave": f"QIVE|{nota['chave']}|{it['item']}"[:300], "nota_chave": f"{forn}|NF{nota['numero']}"[:200],
            "numero_nota": nota["numero"], "data": nota["data"], "fornecedor": forn, "ean": (it.get("ean") or "")[:40],
            "sku_original": sku_o[:160], "modelo": p.modelo if p.categoria == "calcado" else None,
            "sku": p.sku if (p.categoria == "calcado" and p.cor) else None,
            "valor_unitario": vu, "preco_desconto": round(pdsc, 4), "valor_nota": nota.get("valor_nota"),
            "valor_produtos": nota.get("valor_produtos"), "quantidade": q, "quantidade_origem": "api",
            "modalidade": "PE" if abs(pdsc - vu) <= 0.005 else "PROG",
        })
    return out, (None if out else "sem itens de compra")


# ----------------------------------------------------------------------------- sincronização
def _por_ean(conn) -> dict:
    """EAN -> SKU já visto nas compras importadas (para itens sem SKU no texto)."""
    out = {}
    for r in conn.execute(select(db.compras.c.ean, db.compras.c.sku_original).where(db.compras.c.ean.isnot(None))):
        if r.ean and r.sku_original and r.ean not in out:
            out[r.ean] = r.sku_original
    return out


def sincronizar() -> dict:
    with _lock:
        if _estado["rodando"]:
            raise ErroQive("Uma sincronização do Qive já está em andamento.")
        _estado.update(rodando=True, erro=None, inicio=datetime.now(), fim=None, progresso="iniciando")
    try:
        cfg = _cfg()
        desde = date.fromisoformat(cfg.get("desde") or "2026-01-01")
        forns = [x.strip() for x in (cfg.get("fornecedores") or "").split(",") if x.strip()]
        cursor = int(cfg.get("cursor") or 0)
        with db.engine.connect() as c:
            por_ean = _por_ean(c)
            ja = {r[0] for r in c.execute(select(db.compras.c.linha_chave).where(db.compras.c.linha_chave.like("QIVE|%")))}
        novas, notas, ignoradas, paginas = [], 0, {}, 0
        while paginas < MAX_PAGINAS:
            _estado["progresso"] = f"página {paginas + 1} (cursor {cursor})"
            r = pagina(cursor)
            docs = r.get("data") or []
            for doc in docs:
                try:
                    xml_txt = base64.b64decode(doc.get("xml") or "").decode("utf-8", errors="replace")
                    nota = ler_nota(xml_txt)
                except Exception:  # noqa: BLE001
                    ignoradas["XML ilegível"] = ignoradas.get("XML ilegível", 0) + 1
                    continue
                ls, motivo = linhas_compra(nota, por_ean, desde, forns)
                if motivo:
                    ignoradas[motivo] = ignoradas.get(motivo, 0) + 1
                ls = [x for x in ls if x["linha_chave"] not in ja]
                if ls:
                    notas += 1
                    novas.extend(ls)
                    ja.update(x["linha_chave"] for x in ls)
            paginas += 1
            prox = (r.get("page") or {}).get("next")
            n_cursor = None
            if prox:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(prox).query)
                n_cursor = int(q.get("cursor", [cursor + len(docs)])[0])
            if not docs or n_cursor is None or n_cursor == cursor:
                break
            cursor = n_cursor
            time.sleep(0.3)
        resumo = {"quando": datetime.now().strftime("%Y-%m-%d %H:%M"), "notas_novas": notas, "linhas_novas": len(novas),
                  "pares": sum(x["quantidade"] or 0 for x in novas), "ignoradas": ignoradas, "paginas": paginas}
        with db.engine.begin() as c:
            if novas:
                iid = c.execute(insert(db.importacoes).values(
                    tipo="compras", arquivo="Qive (API)", data_referencia=date.today(), modo="api", status="ok",
                    mapeamento=db.dumps({"origem": "qive"}), resumo=db.dumps(resumo))).inserted_primary_key[0]
                for x in novas:
                    x["importacao_id"] = iid
                for i in range(0, len(novas), 500):
                    ids = c.execute(insert(db.compras).returning(db.compras.c.id), novas[i:i + 500]).scalars().all()
                    c.execute(insert(db.alteracoes), [{"importacao_id": iid, "tabela": "compras", "registro_id": rid, "antes": None} for rid in ids])
                resumo["importacao_id"] = iid
        cfg = _cfg(); cfg["cursor"] = cursor; cfg["ultima"] = resumo; cfg.pop("erro", None); _salvar(cfg)
        _estado.update(progresso="concluída")
        return resumo
    except Exception as e:  # noqa: BLE001
        cfg = _cfg(); cfg["erro"] = {"msg": str(e), "quando": datetime.now().strftime("%Y-%m-%d %H:%M")}; _salvar(cfg)
        _estado.update(erro=str(e), progresso="falhou")
        raise
    finally:
        _estado.update(rodando=False, fim=datetime.now())


def sincronizar_em_segundo_plano():
    def run():
        try:
            sincronizar()
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=run, daemon=True).start()


def agendar(horas: float):
    def loop():
        time.sleep(30)
        while True:
            if credenciais()[0]:
                try:
                    sincronizar()
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(max(0.5, horas) * 3600)
    threading.Thread(target=loop, daemon=True).start()


def estado() -> dict:
    i, _, origem = credenciais()
    cfg = _cfg()
    with db.engine.connect() as c:
        from sqlalchemy import func
        n = c.execute(select(func.count(), func.min(db.compras.c.data), func.max(db.compras.c.data))
                      .where(db.compras.c.linha_chave.like("QIVE|%"))).first()
    return {"configurado": bool(i), "origem": origem, "api_id_final": i[-4:] if i else None,
            "desde": cfg.get("desde") or "2026-01-01", "fornecedores": cfg.get("fornecedores") or "",
            "cursor": cfg.get("cursor"), "ultima": cfg.get("ultima"), "erro": cfg.get("erro"),
            "linhas": n[0], "de": str(n[1]) if n[1] else None, "ate": str(n[2]) if n[2] else None,
            "horas": float(os.environ.get("QIVE_SYNC_HORAS", "6") or 0), "base": base_url(),
            **{k: (v.strftime("%Y-%m-%d %H:%M") if isinstance(v, datetime) else v) for k, v in _estado.items()}}
