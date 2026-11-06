from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd


class ErroImportacao(Exception):
    pass


def normalizar_texto(s) -> str:
    s = "" if s is None else str(s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def ler_arquivo(nome: str, conteudo: bytes) -> dict[str, pd.DataFrame]:
    """Lê todas as abas como texto bruto (sem inferir tipos)."""
    nome_l = nome.lower()
    try:
        if nome_l.endswith((".csv", ".txt")):
            txt = conteudo.decode("utf-8-sig", errors="replace")
            sep = ";" if txt.count(";") > txt.count(",") else ","
            return {"csv": pd.read_csv(io.StringIO(txt), sep=sep, dtype=object)}
        abas = pd.read_excel(io.BytesIO(conteudo), sheet_name=None, dtype=object)
    except Exception as e:  # noqa: BLE001
        raise ErroImportacao(f"Não foi possível ler o arquivo: {e}") from e
    out = {}
    for k, df in abas.items():
        df = df.dropna(how="all")
        df.columns = [str(c).strip() for c in df.columns]
        out[str(k)] = df
    return out


def assinatura(colunas) -> str:
    base = "|".join(sorted(normalizar_texto(c) for c in colunas))
    return hashlib.sha1(base.encode()).hexdigest()[:16]


def numero(v):
    """Converte para float aceitando '1.234,56' e '1234.56'. None se vazio; ValueError se inválido."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if pd.isna(v):
            return None
        return float(v)
    s = str(v).strip()
    if s == "" or s.lower() in {"nan", "none", "-"}:
        return None
    s = s.replace("R$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    return float(s)


def data_valor(v) -> date | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, pd.Timestamp):
        return v.date()
    s = str(v).strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"data inválida: {s}")


def texto(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


@dataclass
class Resumo:
    tipo: str
    adicionados: int = 0
    atualizados: int = 0
    duplicados: int = 0
    rejeitados: int = 0
    ignorados: int = 0
    erros: list[dict] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    detalhes: dict = field(default_factory=dict)

    def erro(self, linha, motivo, valor=None, aba=None):
        self.rejeitados += 1
        if len(self.erros) < 200:
            self.erros.append({"linha": linha, "aba": aba, "motivo": motivo, "valor": valor})

    def dict(self):
        return {
            "tipo": self.tipo, "adicionados": self.adicionados, "atualizados": self.atualizados,
            "duplicados": self.duplicados, "rejeitados": self.rejeitados, "ignorados": self.ignorados,
            "erros": self.erros, "avisos": self.avisos, "detalhes": self.detalhes,
        }


def achar_coluna(colunas, *candidatos) -> str | None:
    norm = {normalizar_texto(c): c for c in colunas}
    for cand in candidatos:
        c = normalizar_texto(cand)
        if c in norm:
            return norm[c]
    for cand in candidatos:
        c = normalizar_texto(cand)
        for k, orig in norm.items():
            if c in k:
                return orig
    return None
