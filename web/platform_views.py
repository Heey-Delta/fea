"""Painel da plataforma (Task 34): ambiente isolado de cada operação na VPS.

O painel só grava o estado desejado; quem aplica é o agente da VPS em até ~15 s.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from core import platform as pf
from core.models import Operation, OperationRuntime
from core.operations import OperationError
from web.common import db_session, require_user

router = APIRouter(dependencies=[Depends(require_user)])

ACTIONS = ("ligar", "parar", "reiniciar", "limites", "versao", "backup", "restaurar")


def context(session: Session, op: Operation) -> dict:
    """Dados da aba Ambiente (sem criar registro só por abrir a tela)."""
    views = pf.servers(session)
    return {
        "runtime": session.get(OperationRuntime, op.id),
        "servers": views,
        "platform_online": any(v.online for v in views),
        "versions": pf.available_versions(session),
        "state_label": pf.STATE_LABEL,
        "limits": {
            "cpu_min": pf.CPU_MIN,
            "cpu_max": pf.CPU_MAX,
            "mem_min": pf.MEMORY_MIN,
            "mem_max": pf.MEMORY_MAX,
        },
    }


@router.post("/operacoes/{operation_id}/ambiente/{acao}")
def act(
    request: Request,
    operation_id: int,
    acao: str,
    cpu: float = Form(1.0),
    memoria: int = Form(1024),
    versao: str = Form(""),
    backup: str = Form(""),
    session: Session = Depends(db_session),
):
    op = session.get(Operation, operation_id)
    if op is None or acao not in ACTIONS:
        raise HTTPException(status_code=404)
    messages = {
        "ligar": "Ambiente pedido: o agente liga em até 15 s.",
        "parar": "Parada pedida: o agente para em até 15 s.",
        "reiniciar": "Reinício pedido.",
        "limites": "Limites salvos: o agente recria o ambiente com eles.",
        "versao": "Versão salva: o agente troca a imagem do ambiente.",
        "backup": "Backup pedido: aparece na lista quando terminar.",
        "restaurar": "Restauração pedida: o ambiente para, restaura e volta.",
    }
    try:
        if acao == "ligar":
            pf.set_desired(session, op, "running")
        elif acao == "parar":
            pf.set_desired(session, op, "stopped")
        elif acao == "reiniciar":
            pf.request_restart(session, op)
        elif acao == "limites":
            pf.set_limits(session, op, cpu, memoria)
        elif acao == "versao":
            pf.set_version(session, op, versao)
        elif acao == "backup":
            pf.request_backup(session, op)
        else:
            pf.request_restore(session, op, backup)
        kind, text = "ok", messages[acao]
    except OperationError as exc:
        session.rollback()
        kind, text = "error", str(exc)
    request.session["flash"] = {"kind": kind, "text": text}
    return RedirectResponse(f"/operacoes/{op.id}?aba=ambiente", status_code=303)
