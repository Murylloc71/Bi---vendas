"""Agenda diária da sincronização com o Omie (pedidos de compra + estoque do Omie 03 e 04).

Roda nos horários configurados (padrão 12:00, horário de Brasília). Se o servidor estava
desligado/reiniciando no horário, roda assim que voltar (não pula o dia).
Horários: tela Dados › Omie, ou variável OMIE_HORARIOS (ex.: "12:00" ou "07:00,12:00").
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, insert, select

from . import db

BRASILIA = timezone(timedelta(hours=-3))   # o Brasil não tem horário de verão desde 2019
PADRAO = "12:00"
_estado = {"proxima": None, "ultima": None, "rodando": False, "erros": []}


def _cfg(chave):
    with db.engine.connect() as c:
        return c.execute(select(db.configuracoes.c.valor).where(db.configuracoes.c.chave == chave)).scalar()


def _set(chave, valor):
    with db.engine.begin() as c:
        c.execute(delete(db.configuracoes).where(db.configuracoes.c.chave == chave))
        c.execute(insert(db.configuracoes).values(chave=chave, valor=valor))


def horarios() -> list[str]:
    bruto = os.environ.get("OMIE_HORARIOS", "").strip() or _cfg("omie_horarios") or PADRAO
    out = []
    for h in bruto.split(","):
        h = h.strip()
        try:
            hh, mm = (int(x) for x in h.split(":"))
            if 0 <= hh < 24 and 0 <= mm < 60:
                out.append(f"{hh:02d}:{mm:02d}")
        except ValueError:
            continue
    return sorted(set(out)) or [PADRAO]


def definir_horarios(texto: str) -> list[str]:
    hs = [h.strip() for h in (texto or "").split(",") if h.strip()]
    validos = []
    for h in hs:
        try:
            hh, mm = (int(x) for x in h.split(":"))
            assert 0 <= hh < 24 and 0 <= mm < 60
            validos.append(f"{hh:02d}:{mm:02d}")
        except (ValueError, AssertionError) as e:
            raise ValueError(f"Horário inválido: {h} (use HH:MM, ex.: 12:00)") from e
    if not validos:
        raise ValueError("Informe ao menos um horário.")
    _set("omie_horarios", ",".join(sorted(set(validos))))
    return horarios()


def _agora():
    return datetime.now(BRASILIA)


def ultimo_horario_devido(agora=None) -> datetime:
    """O horário agendado mais recente que já passou (hoje ou ontem)."""
    agora = agora or _agora()
    cands = []
    for dia in (agora.date(), agora.date() - timedelta(days=1)):
        for h in horarios():
            hh, mm = (int(x) for x in h.split(":"))
            t = datetime(dia.year, dia.month, dia.day, hh, mm, tzinfo=BRASILIA)
            if t <= agora:
                cands.append(t)
    return max(cands)


def proximo_horario(agora=None) -> datetime:
    agora = agora or _agora()
    for dia in (agora.date(), agora.date() + timedelta(days=1)):
        for h in horarios():
            hh, mm = (int(x) for x in h.split(":"))
            t = datetime(dia.year, dia.month, dia.day, hh, mm, tzinfo=BRASILIA)
            if t > agora:
                return t
    return agora + timedelta(days=1)


def ultima_execucao():
    v = _cfg("omie_agenda_ultima")
    return datetime.fromisoformat(v) if v else None


def executar():
    """Sincroniza pedidos e estoque do Omie; o erro de um não impede o outro."""
    from . import estoque_omie, omie
    _estado.update(rodando=True, erros=[])
    try:
        if omie.credenciais()[0]:
            try:
                omie.sincronizar()
            except Exception as e:  # noqa: BLE001
                _estado["erros"].append(f"Pedidos: {e}")
        if any(estoque_omie.credenciais(c["id"])[0] for c in estoque_omie.CONTAS):
            try:
                r = estoque_omie.sincronizar()
                _estado["erros"].extend(r.get("erros") or [])
            except Exception as e:  # noqa: BLE001
                _estado["erros"].append(f"Estoque: {e}")
    finally:
        agora = _agora()
        _set("omie_agenda_ultima", agora.isoformat())
        _estado.update(rodando=False, ultima=agora.strftime("%Y-%m-%d %H:%M"))


def iniciar():
    def loop():
        time.sleep(15)
        while True:
            try:
                devido = ultimo_horario_devido()
                ult = ultima_execucao()
                if ult is None or ult < devido:
                    executar()
                _estado["proxima"] = proximo_horario().strftime("%Y-%m-%d %H:%M")
            except Exception:  # noqa: BLE001 - a agenda nunca para por erro de uma rodada
                pass
            time.sleep(30)
    threading.Thread(target=loop, daemon=True).start()


def estado() -> dict:
    ult = ultima_execucao()
    return {"horarios": horarios(), "fixo_por_variavel": bool(os.environ.get("OMIE_HORARIOS", "").strip()),
            "proxima": proximo_horario().strftime("%Y-%m-%d %H:%M"),
            "ultima": ult.astimezone(BRASILIA).strftime("%Y-%m-%d %H:%M") if ult else None,
            "rodando": _estado["rodando"], "erros": _estado["erros"]}
