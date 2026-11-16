"""Tela da Fila (Task 8): geral ou por operação, filtros e ações em lote com resumo."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import items as it
from core.models import Operation
from web.common import db_session, render, require_user

router = APIRouter(dependencies=[Depends(require_user)])


def back(op: int | None, etapa: str, estado: str) -> str:
    params = [f"{k}={v}" for k, v in (("op", op), ("etapa", etapa), ("estado", estado)) if v]
    return "/fila" + ("?" + "&".join(params) if params else "")


@router.get("/fila", response_class=HTMLResponse)
def page(
    request: Request,
    op: int | None = None,
    etapa: str = "",
    estado: str = "",
    session: Session = Depends(db_session),
) -> Response:
    items = it.list_items(session, op, etapa, estado)
    return render(
        request,
        "queue.html",
        active="/fila",
        items=items,
        op=op,
        etapa=etapa,
        estado=estado,
        counts=it.stage_counts(session, op),
        stages=it.STAGE_LABEL,
        labels=it.STATUS_LABEL,
        actions=it.ACTIONS,
        operations=list(session.scalars(select(Operation).order_by(Operation.name))),
        flash=request.session.pop("flash", None),
        **it.context(session, items),
    )


@router.post("/fila/lote", response_class=HTMLResponse)
def bulk(
    request: Request,
    acao: str = Form(...),
    item_ids: list[int] = Form([]),
    motivo: str = Form(""),
    confirmar: bool = Form(False),
    op: int | None = Form(None),
    etapa: str = Form(""),
    estado: str = Form(""),
    session: Session = Depends(db_session),
) -> Response:
    target = back(op, etapa, estado)
    if acao not in it.ACTIONS or not item_ids:
        request.session["flash"] = {"kind": "error", "text": "Escolha itens e uma ação."}
        return RedirectResponse(target, status_code=303)
    if not confirmar:
        return render(
            request,
            "queue_confirm.html",
            active="/fila",
            s=it.summary(session, item_ids, acao),
            motivo=motivo,
            op=op,
            etapa=etapa,
            estado=estado,
            labels=it.STATUS_LABEL,
        )
    done, skipped = it.apply(session, item_ids, acao, motivo)
    text = f"{it.ACTIONS[acao]}: {done} itens."
    if skipped:
        text += f" {skipped} ficaram de fora."
    request.session["flash"] = {"kind": "ok", "text": text}
    return RedirectResponse(target, status_code=303)
