"""Play e acompanhamento das execuções (Task 6)."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from core import executions as exe
from core import operations as ops
from core import sources as src
from core.models import Execution, Operation
from web.common import db_session, render, require_user

router = APIRouter(dependencies=[Depends(require_user)])

EXECUTION_LABEL = {
    "running": "Rodando",
    "paused": "Pausada",
    "completed": "Concluída",
    "partial": "Parcial",
    "cancelled": "Cancelada",
}
CRITERIA_LABEL = {"recent": "Mais recentes", "heat": "Priorizar heat tags"}
PRIORITY_LABEL = {"low": "Baixa", "normal": "Normal", "high": "Alta"}


def flash(request: Request, kind: str, text: str) -> None:
    request.session["flash"] = {"kind": kind, "text": text}


@router.get("/operacoes/{operation_id}/play", response_class=HTMLResponse)
def play_page(request: Request, operation_id: int, session: Session = Depends(db_session)):
    op = session.get(Operation, operation_id)
    if op is None:
        raise HTTPException(status_code=404, detail="Operação não encontrada")
    config = ops.current_config(session, op)
    return render(
        request,
        "play.html",
        active="/operacoes",
        op=op,
        config=config,
        fishing=exe.fishing_config(config.config),
        sources=[s for s in src.list_sources(session, op.id) if s.status != "paused"],
        criteria_label=CRITERIA_LABEL,
        priority_label=PRIORITY_LABEL,
        flash=request.session.pop("flash", None),
    )


@router.post("/operacoes/{operation_id}/play")
def play(
    request: Request,
    operation_id: int,
    target_x: int = Form(...),
    search_budget: int = Form(...),
    criteria: str = Form("recent"),
    priority: str = Form("normal"),
    source_ids: list[int] = Form(default_factory=list),
    session: Session = Depends(db_session),
):
    op = session.get(Operation, operation_id)
    if op is None:
        raise HTTPException(status_code=404, detail="Operação não encontrada")
    try:
        ex = exe.start_execution(
            session,
            op,
            target_x=target_x,
            search_budget=search_budget,
            criteria=criteria,
            priority=priority,
            source_ids=source_ids,
        )
    except ops.OperationError as exc:
        flash(request, "error", str(exc))
        return RedirectResponse(f"/operacoes/{operation_id}/play", status_code=303)
    return RedirectResponse(f"/execucoes/{ex.id}", status_code=303)


def get_execution(session: Session, execution_id: int) -> Execution:
    ex = session.get(Execution, execution_id)
    if ex is None:
        raise HTTPException(status_code=404, detail="Execução não encontrada")
    return ex


@router.get("/execucoes/{execution_id}", response_class=HTMLResponse)
def execution_page(
    request: Request, execution_id: int, session: Session = Depends(db_session)
) -> Response:
    ex = get_execution(session, execution_id)
    counts = exe.counters(session, ex.id)
    return render(
        request,
        "execution.html",
        active="/operacoes",
        ex=ex,
        op=session.get(Operation, ex.operation_id),
        counts=counts,
        progress=min(100, round(100 * counts["elegiveis"] / ex.target_x)) if ex.target_x else 0,
        label=EXECUTION_LABEL,
        criteria_label=CRITERIA_LABEL,
        priority_label=PRIORITY_LABEL,
        flash=request.session.pop("flash", None),
    )


ACTIONS = {"pausar": exe.pause, "retomar": exe.resume, "cancelar": exe.cancel}


@router.post("/execucoes/{execution_id}/{action}")
def execution_action(
    request: Request, execution_id: int, action: str, session: Session = Depends(db_session)
):
    if action not in ACTIONS:
        raise HTTPException(status_code=404, detail="Ação desconhecida")
    ex = get_execution(session, execution_id)
    try:
        ACTIONS[action](session, ex)
        flash(request, "ok", f"Execução {EXECUTION_LABEL[ex.status].lower()}.")
    except ops.OperationError as exc:
        flash(request, "error", str(exc))
    return RedirectResponse(f"/execucoes/{execution_id}", status_code=303)
