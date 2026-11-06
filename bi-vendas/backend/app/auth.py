"""Login do BI.

Senhas pelas variáveis de ambiente (Secrets do Render):
  BI_SENHA          acesso completo (importar, desfazer, configurar)
  BI_SENHA_LEITURA  opcional: só consulta (nada que altere dados)
  BI_SEGREDO        chave que assina o cookie da sessão (o Render gera sozinho)
Sem BI_SENHA o BI fica aberto, o que só é aceitável no computador local. Publicado na
internet (Render) sem BI_SENHA, o BI se recusa a mostrar dados.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

COOKIE = "bi_sessao"
DURACAO = 30 * 24 * 3600          # 30 dias
_tentativas: dict = {}


def _senha(papel):
    return os.environ.get("BI_SENHA" if papel == "admin" else "BI_SENHA_LEITURA", "").strip()


def ativo() -> bool:
    return bool(_senha("admin"))


def na_internet() -> bool:
    return bool(os.environ.get("RENDER") or os.environ.get("REPLIT_DEPLOYMENT"))


def _segredo() -> bytes:
    s = os.environ.get("BI_SEGREDO", "").strip() or ("bi|" + _senha("admin"))
    return hashlib.sha256(s.encode()).digest()


def criar_sessao(papel: str) -> str:
    corpo = base64.urlsafe_b64encode(json.dumps({"p": papel, "e": int(time.time()) + DURACAO}).encode()).decode()
    assin = hmac.new(_segredo(), corpo.encode(), hashlib.sha256).hexdigest()
    return f"{corpo}.{assin}"


def ler_sessao(valor: str | None) -> str | None:
    """Papel ('admin' ou 'leitura') se o cookie for válido; senão None."""
    if not valor or "." not in valor:
        return None
    corpo, assin = valor.rsplit(".", 1)
    if not hmac.compare_digest(assin, hmac.new(_segredo(), corpo.encode(), hashlib.sha256).hexdigest()):
        return None
    try:
        d = json.loads(base64.urlsafe_b64decode(corpo.encode()))
    except Exception:  # noqa: BLE001
        return None
    if d.get("e", 0) < time.time():
        return None
    # se a senha de leitura foi removida, a sessão de leitura deixa de valer
    if d.get("p") == "leitura" and not _senha("leitura"):
        return None
    return d.get("p") if d.get("p") in ("admin", "leitura") else None


def conferir_senha(senha: str, ip: str) -> str | None:
    """Papel correspondente à senha, com limite de 8 tentativas a cada 10 minutos por IP."""
    agora = time.time()
    hist = [t for t in _tentativas.get(ip, []) if agora - t < 600]
    if len(hist) >= 8:
        raise PermissionError("Muitas tentativas. Espere alguns minutos e tente de novo.")
    for papel in ("admin", "leitura"):
        s = _senha(papel)
        if s and hmac.compare_digest(senha.encode(), s.encode()):
            _tentativas.pop(ip, None)
            return papel
    hist.append(agora)
    _tentativas[ip] = hist
    return None


LIVRES = {"/api/login", "/api/logout", "/api/sessao", "/api/saude"}


def permitido(caminho: str, metodo: str, papel: str | None) -> tuple[bool, int, str]:
    """(ok, status, mensagem) para uma requisição à API."""
    if not caminho.startswith("/api/") or caminho in LIVRES or caminho.startswith("/api/cron/"):
        return True, 200, ""
    if not ativo():
        if na_internet():
            return False, 503, "Defina a variável BI_SENHA no servidor para proteger o BI antes de usar."
        return True, 200, ""
    if papel is None:
        return False, 401, "Faça login."
    if papel == "leitura" and metodo not in ("GET", "HEAD", "OPTIONS"):
        return False, 403, "Seu acesso é só de consulta."
    return True, 200, ""
