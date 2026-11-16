"""Telas e API das operações (Task 4).

O canvas (próxima etapa da Task 4) salva o fluxo por POST /operacoes/{id}/config em JSON.
"""

import json
from typing import Any

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from core import operations as ops
from core.models import Operation
from core.states import OPERATION_STATUS
from web.common import db_session, render, require_user

router = APIRouter(dependencies=[Depends(require_user)])

STATUS_LABEL = {
    "draft": "Rascunho",
    "active": "Ativa",
    "paused": "Pausada",
    "archived": "Arquivada",
}
TABS = [
    ("geral", "Visão geral"),
    ("config", "Configuração"),
    ("fontes", "Fontes"),
    ("contas", "Contas"),
    ("execucoes", "Execuções"),
    ("historico", "Histórico de versões"),
]
# Ações de estado oferecidas a partir de cada estado.
ACTIONS = {
    "draft": [("active", "Ativar")],
    "active": [("paused", "Pausar")],
    "paused": [("active", "Retomar")],
    "archived": [],
}


def flash(request: Request, kind: str, text: str) -> None:
    request.session["flash"] = {"kind": kind, "text": text}


def get_operation(session: Session, operation_id: int) -> Operation:
    op = session.get(Operation, operation_id)
    if op is None:
        raise HTTPException(status_code=404, detail="Operação não encontrada")
    return op


@router.get("/operacoes", response_class=HTMLResponse)
def list_page(
    request: Request, status: str = "", session: Session = Depends(db_session)
) -> Response:
    status = status if status in OPERATION_STATUS else ""
    return render(
        request,
        "operations_list.html",
        active="/operacoes",
        operations=ops.list_operations(session, status or None),
        status=status,
        status_label=STATUS_LABEL,
        flash=request.session.pop("flash", None),
    )


@router.post("/operacoes")
def create(request: Request, name: str = Form(""), session: Session = Depends(db_session)):
    try:
        op = ops.create_operation(session, name)
    except ops.OperationError as exc:
        flash(request, "error", str(exc))
        return RedirectResponse("/operacoes", status_code=303)
    return RedirectResponse(f"/operacoes/{op.id}", status_code=303)


@router.get("/operacoes/{operation_id}", response_class=HTMLResponse)
def detail_page(
    request: Request,
    operation_id: int,
    aba: str = "geral",
    v: int | None = None,
    session: Session = Depends(db_session),
) -> Response:
    op = get_operation(session, operation_id)
    config = ops.current_config(session, op)
    history = ops.versions(session, op)
    shown = next((h for h in history if h.version == v), config)
    issues = ops.validate_graph(config.config)
    return render(
        request,
        "operation_detail.html",
        active="/operacoes",
        op=op,
        config=config,
        shown=shown,
        shown_json=json.dumps(shown.config, ensure_ascii=False, indent=2),
        history=history,
        issues=issues,
        errors=[i for i in issues if i.level == "error"],
        tab=aba if aba in dict(TABS) else "geral",
        tabs=TABS,
        actions=ACTIONS[op.status],
        status_label=STATUS_LABEL,
        node_label=ops.NODE_TYPES,
        flash=request.session.pop("flash", None),
    )


@router.get("/operacoes/{operation_id}/fluxo", response_class=HTMLResponse)
def canvas_page(
    request: Request, operation_id: int, session: Session = Depends(db_session)
) -> Response:
    op = get_operation(session, operation_id)
    config = ops.current_config(session, op)
    read_only = op.status == "archived"
    boot = {
        "config": config.config,
        "issues": [
            {"level": i.level, "message": i.message, "node_id": i.node_id}
            for i in ops.validate_graph(config.config)
        ],
        "labels": ops.NODE_TYPES,
        "allowedEdges": sorted(ops.ALLOWED_EDGES),
        "saveUrl": f"/operacoes/{op.id}/config",
        "readOnly": read_only,
    }
    return render(
        request,
        "operation_canvas.html",
        active="/operacoes",
        op=op,
        config=config,
        boot=boot,
        read_only=read_only,
        palette=list(ops.NODE_TYPES.items()),
    )


@router.post("/operacoes/{operation_id}/status")
def change_status(
    request: Request,
    operation_id: int,
    acao: str = Form(...),
    session: Session = Depends(db_session),
):
    op = get_operation(session, operation_id)
    try:
        ops.change_status(session, op, acao)
        flash(request, "ok", f"Operação agora está {STATUS_LABEL[acao].lower()}.")
    except ops.OperationError as exc:
        flash(request, "error", str(exc))
    return RedirectResponse(f"/operacoes/{operation_id}", status_code=303)


@router.post("/operacoes/{operation_id}/duplicar")
def duplicate(request: Request, operation_id: int, session: Session = Depends(db_session)):
    copy_op = ops.duplicate_operation(session, get_operation(session, operation_id))
    flash(request, "ok", "Operação duplicada como rascunho.")
    return RedirectResponse(f"/operacoes/{copy_op.id}", status_code=303)


@router.post("/operacoes/{operation_id}/config")
def save_config(
    operation_id: int,
    config: dict[str, Any] = Body(...),
    session: Session = Depends(db_session),
) -> JSONResponse:
    """Usado pelo canvas: salva uma versão nova e devolve os problemas do fluxo."""
    op = get_operation(session, operation_id)
    try:
        version = ops.save_config(session, op, config)
    except ops.OperationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    issues = ops.validate_graph(version.config)
    return JSONResponse(
        {
            "version": version.version,
            "issues": [
                {"level": i.level, "message": i.message, "node_id": i.node_id} for i in issues
            ],
        }
    )
