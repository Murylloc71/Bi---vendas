"""Regra única de identificação de produtos.

Toda a aplicação (importação, cálculos, telas) usa estas funções. Nunca
interprete códigos de produto em outro lugar.

Calçados (código iniciado por XXXX.XXX ou XXXX.XXXX):
    MODELO - CABEDAL - COR [- TAMANHO]
    * separadores "-" e "." são equivalentes depois do modelo
      (ex.: 7208.100.29516.109603-39 == 7208.100-29516-109603-39)
    * com um único segmento após o modelo, ele é a COR (cabedal não informado)
    * o SKU canônico usa hífens e não inclui o tamanho

Demais produtos: o próprio código (maiúsculo, sem espaços nas pontas).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MODELO_RE = re.compile(r"^(\d{4}\.\d{3,4})(?:[.\-](.*))?$")
TAMANHO_RE = re.compile(r"^\d{1,2}$")
KIT_RE = re.compile(r"^KIT(\d+)-(.+)$", re.I)

# Sufixos de tamanho/variação em códigos de estoque de produtos que não seguem o padrão
SUFIXO_TAMANHO_OUTROS = re.compile(
    r"^(?:-?\d{1,2}|-?(?:PP|P|M|G|GG|XG|XXG|XGG|EG|EGG|EXG|U|UN|UNI)|\d{2}0000|-\d{2}-\d{2})$",
    re.I,
)

SEM_CABEDAL = "s/cabedal"

# Modelos em que cada cabedal é tratado como um modelo diferente (ex.: 7208.101 com
# cabedal 29516 vira o modelo "7208.101-29516"). Editável em Dados › Qualidade e regras;
# o padrão vale enquanto nada foi salvo.
MODELOS_POR_CABEDAL_PADRAO = ("7208.101",)
_modelos_por_cabedal: set[str] = set(MODELOS_POR_CABEDAL_PADRAO)


def definir_modelos_por_cabedal(modelos) -> None:
    global _modelos_por_cabedal
    _modelos_por_cabedal = {str(m).strip() for m in modelos if str(m).strip()}


def modelos_por_cabedal() -> list[str]:
    return sorted(_modelos_por_cabedal)


@dataclass
class Produto:
    sku: str                 # chave canônica sem tamanho
    categoria: str           # 'calcado' | 'outro'
    modelo: str              # para 'outro' = sku
    cabedal: str | None = None
    cor: str | None = None
    tamanho: str | None = None
    extras: list[str] = field(default_factory=list)
    original: str = ""
    avisos: list[str] = field(default_factory=list)

    @property
    def chave_cabedal(self) -> str:
        if self.categoria != "calcado":
            return self.sku
        if self.cabedal and self.modelo.endswith(f"-{self.cabedal}"):
            return self.modelo          # modelo já separado por cabedal
        return f"{self.modelo}-{self.cabedal or SEM_CABEDAL}"


def limpar(codigo) -> str:
    s = "" if codigo is None else str(codigo)
    s = s.strip()
    # espaços internos ao redor de separadores ("78276- 29")
    s = re.sub(r"\s*([.\-])\s*", r"\1", s)
    return s


def interpretar(codigo, com_tamanho: bool | str = "auto") -> Produto:
    """Interpreta um código.

    com_tamanho:
        True   -> o último segmento numérico (1-2 dígitos) é tamanho (arquivos de estoque)
        False  -> nunca extrai tamanho
        'auto' -> extrai só quando há 3+ segmentos após o modelo e o último tem 1-2 dígitos
                  (SKU de venda com tamanho embutido por engano)
    """
    raw = limpar(codigo)
    m = MODELO_RE.match(raw)
    if not m:
        sku = raw.upper()
        return Produto(sku=sku, categoria="outro", modelo=sku, original=raw)

    modelo, resto = m.group(1), m.group(2)
    segs = [s for s in re.split(r"[.\-]", resto or "") if s != ""]
    avisos: list[str] = []
    tamanho = None
    if segs and TAMANHO_RE.match(segs[-1]):
        if com_tamanho is True and len(segs) >= 2:
            tamanho = segs.pop()
        elif com_tamanho == "auto" and len(segs) >= 3:
            tamanho = segs.pop()
            avisos.append("tamanho embutido no SKU de venda")

    cabedal = cor = None
    extras: list[str] = []
    if len(segs) == 1:
        cor = segs[0]
    elif len(segs) >= 2:
        cabedal, cor, extras = segs[0], segs[1], segs[2:]
        if extras:
            avisos.append("segmentos extras após a cor")

    sku = "-".join([modelo, *segs])
    if cabedal and modelo in _modelos_por_cabedal:
        modelo = f"{modelo}-{cabedal}"
    return Produto(sku=sku, categoria="calcado", modelo=modelo, cabedal=cabedal, cor=cor,
                   tamanho=tamanho, extras=extras, original=raw, avisos=avisos)


def kit(sku: str) -> tuple[int, str] | None:
    """KIT3-4515-999 -> (3, '4515-999')."""
    m = KIT_RE.match(sku or "")
    if not m:
        return None
    return int(m.group(1)), m.group(2).upper()


def chave_nivel(p: Produto, nivel: str) -> str:
    if nivel == "modelo":
        return p.modelo
    if nivel == "cabedal":
        return p.chave_cabedal
    return p.sku


def vincular_outro(codigo: str, conhecidos_por_tamanho: list[str]) -> tuple[str, str] | None:
    """Liga um código de estoque de produto 'outro' a um SKU conhecido.

    Retorna (sku, sufixo) quando o código é exatamente um SKU conhecido ou um SKU
    conhecido seguido de um sufixo de tamanho reconhecível. `conhecidos_por_tamanho`
    deve estar ordenado do maior para o menor (casa o prefixo mais longo).
    """
    cod = limpar(codigo).upper()
    conjunto = set(conhecidos_por_tamanho)
    if cod in conjunto:
        return cod, ""
    for k in conhecidos_por_tamanho:
        if len(k) >= 3 and cod.startswith(k):
            suf = cod[len(k):]
            if SUFIXO_TAMANHO_OUTROS.match(suf):
                return k, suf.lstrip("-")
    return None
