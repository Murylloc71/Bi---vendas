"""
Servidor MCP remoto para a API do Qive (Arquivei) — somente leitura.

Variáveis de ambiente (configurar na hospedagem, NUNCA no GitHub):
  QIVE_API_ID   -> API ID do Qive
  QIVE_API_KEY  -> API Key do Qive
  MCP_SECRET    -> código secreto (mín. 32 caracteres) que vai na URL do conector
  QIVE_BASE_URL -> opcional; padrão https://api.arquivei.com.br
                   (para testes: https://sandbox-api.arquivei.com.br)

URL do conector no Claude:  https://SEU-SERVIDOR/mcp/<MCP_SECRET>
Teste de funcionamento:     https://SEU-SERVIDOR/health
"""

import base64
import os
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import PlainTextResponse

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
QIVE_API_ID = os.environ.get("QIVE_API_ID", "")
QIVE_API_KEY = os.environ.get("QIVE_API_KEY", "")
MCP_SECRET = os.environ.get("MCP_SECRET", "")
QIVE_BASE_URL = os.environ.get("QIVE_BASE_URL", "https://api.arquivei.com.br").rstrip("/")

if len(MCP_SECRET) < 32 or not re.fullmatch(r"[A-Za-z0-9_-]+", MCP_SECRET):
    raise RuntimeError(
        "MCP_SECRET ausente ou fraco: use pelo menos 32 caracteres, "
        "apenas letras, números, '-' ou '_'."
    )

PAGE_LIMIT = 50          # máximo aceito pela API do Qive por página
MAX_PAGES = 40           # trava de segurança: até 2.000 notas por consulta
NS = {"n": "http://www.portalfiscal.inf.br/nfe"}
ENDPOINTS = {"recebida": "/v1/nfe/received", "emitida": "/v1/nfe/emitted"}

mcp = FastMCP(
    "qive",
    instructions=(
        "Consulta notas fiscais eletrônicas (NF-e) no Qive/Arquivei da Uai Comprei. "
        "Somente leitura. Use 'tipo'='recebida' para notas de entrada (fornecedores) "
        "e 'emitida' para notas de saída."
    ),
    host="0.0.0.0",
    streamable_http_path=f"/mcp/{MCP_SECRET}",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------
def _so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def _validar_cnpj(cnpj: str) -> str:
    cnpj = _so_digitos(cnpj)
    if len(cnpj) != 14:
        raise ValueError(f"CNPJ inválido: precisa ter 14 dígitos (recebi {len(cnpj)}).")
    return cnpj


def _validar_tipo(tipo: str) -> str:
    tipo = (tipo or "").strip().lower()
    if tipo not in ENDPOINTS:
        raise ValueError("tipo deve ser 'recebida' ou 'emitida'.")
    return tipo


def _headers() -> dict:
    if not QIVE_API_ID or not QIVE_API_KEY:
        raise RuntimeError("Credenciais do Qive não configuradas no servidor.")
    return {
        "X-API-ID": QIVE_API_ID,
        "X-API-KEY": QIVE_API_KEY,
        "Content-Type": "application/json",
    }


def _texto(no, caminho: str) -> str | None:
    if no is None:
        return None
    achado = no.find(caminho, NS)
    return achado.text if achado is not None else None


def _resumir_xml(chave: str, xml_b64: str) -> dict:
    """Extrai os campos principais do XML (base64) de uma NF-e."""
    resumo = {"chave_acesso": chave}
    try:
        raiz = ET.fromstring(base64.b64decode(xml_b64))
        inf = raiz.find(".//n:infNFe", NS)
        ide = inf.find("n:ide", NS)
        emit = inf.find("n:emit", NS)
        dest = inf.find("n:dest", NS)
        resumo.update(
            {
                "numero": _texto(ide, "n:nNF"),
                "serie": _texto(ide, "n:serie"),
                "data_emissao": _texto(ide, "n:dhEmi") or _texto(ide, "n:dEmi"),
                "natureza_operacao": _texto(ide, "n:natOp"),
                "emitente_cnpj": _texto(emit, "n:CNPJ") or _texto(emit, "n:CPF"),
                "emitente_nome": _texto(emit, "n:xNome"),
                "destinatario_cnpj": _texto(dest, "n:CNPJ") or _texto(dest, "n:CPF"),
                "destinatario_nome": _texto(dest, "n:xNome"),
                "valor_total": _texto(inf, "n:total/n:ICMSTot/n:vNF"),
                "qtd_itens": len(inf.findall("n:det", NS)),
            }
        )
    except Exception as erro:  # XML incompleto, evento, etc.
        resumo["aviso"] = f"Não foi possível ler o XML: {erro}"
    return resumo


async def _buscar(tipo: str, params: dict) -> list[dict]:
    """Percorre todas as páginas do Qive (cursor) e devolve as notas na ordem da API."""
    url = QIVE_BASE_URL + ENDPOINTS[tipo]
    notas: list[dict] = []
    async with httpx.AsyncClient(timeout=60, headers=_headers()) as cliente:
        resposta = await cliente.get(url, params=params)
        for _ in range(MAX_PAGES):
            if resposta.status_code != 200:
                raise RuntimeError(
                    f"Qive respondeu {resposta.status_code}: {resposta.text[:300]}"
                )
            corpo = resposta.json()
            dados = corpo.get("data") or []
            for item in dados:
                notas.append(_resumir_xml(item.get("access_key"), item.get("xml", "")))
            proxima = (corpo.get("page") or {}).get("next")
            if not dados or len(dados) < PAGE_LIMIT or not proxima:
                break
            resposta = await cliente.get(proxima)
    return notas


def _janela(data_inicio: str | None, data_fim: str | None, dias: int) -> tuple[str, str]:
    fim = date.fromisoformat(data_fim) if data_fim else date.today()
    inicio = date.fromisoformat(data_inicio) if data_inicio else fim - timedelta(days=dias)
    return f"{inicio.isoformat()} 00:00:00", f"{fim.isoformat()} 23:59:59"


# ---------------------------------------------------------------------------
# Ferramentas MCP
# ---------------------------------------------------------------------------
@mcp.tool()
async def ultimas_notas(
    cnpj: str, tipo: str = "recebida", quantidade: int = 5, dias: int = 30
) -> dict:
    """Retorna as notas mais recentes que entraram no Qive para um CNPJ.

    cnpj: CNPJ da empresa Uai Comprei (com ou sem pontuação).
    tipo: 'recebida' (entrada/fornecedor) ou 'emitida' (saída).
    quantidade: quantas notas devolver (1 a 20).
    dias: quantos dias para trás procurar (1 a 90).
    """
    cnpj, tipo = _validar_cnpj(cnpj), _validar_tipo(tipo)
    quantidade = max(1, min(int(quantidade), 20))
    dias = max(1, min(int(dias), 90))
    de, ate = _janela(None, None, dias)
    notas = await _buscar(
        tipo,
        {"cnpj[]": cnpj, "created_at[from]": de, "created_at[to]": ate, "limit": PAGE_LIMIT},
    )
    # A API devolve em ordem de entrada no Qive; as últimas da lista são as mais novas.
    recentes = list(reversed(notas[-quantidade:]))
    return {
        "cnpj": cnpj,
        "tipo": tipo,
        "periodo_pesquisado": {"de": de, "ate": ate},
        "total_no_periodo": len(notas),
        "ordem": "da mais recente para a mais antiga (entrada no Qive)",
        "notas": recentes,
    }


@mcp.tool()
async def listar_notas(
    cnpj: str,
    tipo: str = "recebida",
    data_inicio: str | None = None,
    data_fim: str | None = None,
) -> dict:
    """Lista as notas que entraram no Qive para um CNPJ em um período.

    cnpj: CNPJ da empresa (com ou sem pontuação).
    tipo: 'recebida' ou 'emitida'.
    data_inicio / data_fim: datas no formato AAAA-MM-DD (padrão: últimos 7 dias).
    """
    cnpj, tipo = _validar_cnpj(cnpj), _validar_tipo(tipo)
    de, ate = _janela(data_inicio, data_fim, 7)
    notas = await _buscar(
        tipo,
        {"cnpj[]": cnpj, "created_at[from]": de, "created_at[to]": ate, "limit": PAGE_LIMIT},
    )
    return {
        "cnpj": cnpj,
        "tipo": tipo,
        "periodo": {"de": de, "ate": ate},
        "total": len(notas),
        "limitado": len(notas) >= PAGE_LIMIT * MAX_PAGES,
        "notas": notas,
    }


@mcp.tool()
async def consultar_nota(chave_acesso: str) -> dict:
    """Consulta uma NF-e pela chave de acesso de 44 dígitos (procura em recebidas e emitidas)."""
    chave = _so_digitos(chave_acesso)
    if len(chave) != 44:
        raise ValueError("A chave de acesso precisa ter 44 dígitos.")
    for tipo in ("recebida", "emitida"):
        notas = await _buscar(tipo, {"access_key[]": chave, "limit": PAGE_LIMIT})
        if notas:
            return {"tipo": tipo, "nota": notas[0]}
    return {"encontrada": False, "mensagem": "Chave não encontrada no Qive desta conta."}


# ---------------------------------------------------------------------------
# Rota de teste e aplicação web
# ---------------------------------------------------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


app = mcp.streamable_http_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
