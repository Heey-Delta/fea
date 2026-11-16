"""Telas de aprovação (Task 18)."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import approval as ap
from core import operations as ops
from core.models import Account, Item, Operation, Render, Source
from web.common import db_session, render, require_user

router = APIRouter(dependencies=[Depends(require_user)])


def flash(request: Request, kind: str, text: str) -> None:
    request.session["flash"] = {"kind": kind, "text": text}


def accounts_for(session: Session, operation_id: int) -> list[Account]:
    op = session.get(Operation, operation_id)
    ids = ops.linked_account_ids(ops.current_config(session, op).config)
    if not ids:
        return []
    return list(session.scalars(select(Account).where(Account.id.in_(ids)).order_by(Account.id)))


def card(request: Request, session: Session, item: Item) -> dict:
    latest = ap.latest_render(session, item.id)
    storage = request.app.state.storage
    return {
        "item": item,
        "render": latest,
        "video_url": storage.url(latest.output_file) if latest and latest.output_file else None,
        "blocked": ap.can_approve(session, item),
        "warnings": (latest.qa_result or {}).get("warnings", []) if latest else [],
    }


@router.get("/aprovacao", response_class=HTMLResponse)
def queue_page(request: Request, op: int | None = None, session: Session = Depends(db_session)):
    operations = list(session.scalars(select(Operation).order_by(Operation.name)))
    items = ap.queue_items(session, op)
    selected_op = op or (items[0].operation_id if items else None)
    return render(
        request,
        "approval_queue.html",
        active="/aprovacao",
        cards=[card(request, session, i) for i in items],
        operations=operations,
        op=op,
        accounts=accounts_for(session, selected_op) if selected_op else [],
        flash=request.session.pop("flash", None),
    )


@router.post("/aprovacao/lote")
def bulk_action(
    request: Request,
    acao: str = Form(...),
    item_ids: list[int] = Form(default_factory=list),
    account_ids: list[int] = Form(default_factory=list),
    motivo: str = Form(""),
    session: Session = Depends(db_session),
):
    if acao not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Ação inválida")
    done, skipped = ap.bulk(session, item_ids, acao, account_ids, motivo)
    verb = "aprovados" if acao == "approve" else "rejeitados"
    text = f"{done} vídeos {verb}."
    if skipped:
        text += " Ficaram de fora: " + "; ".join(skipped)
    flash(request, "ok" if not skipped else "error", text)
    return RedirectResponse(request.headers.get("referer") or "/aprovacao", status_code=303)


def get_item(session: Session, item_id: int) -> Item:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado")
    return item


@router.get("/aprovacao/{item_id}", response_class=HTMLResponse)
def item_page(request: Request, item_id: int, session: Session = Depends(db_session)) -> Response:
    item = get_item(session, item_id)
    renders = list(
        session.scalars(
            select(Render).where(Render.item_id == item.id).order_by(Render.version.desc())
        )
    )
    return render(
        request,
        "approval_item.html",
        active="/aprovacao",
        c=card(request, session, item),
        renders=renders,
        source=session.get(Source, item.source_id),
        op=session.get(Operation, item.operation_id),
        accounts=accounts_for(session, item.operation_id),
        flash=request.session.pop("flash", None),
    )


@router.post("/aprovacao/{item_id}/{action}")
def item_action(
    request: Request,
    item_id: int,
    action: str,
    account_ids: list[int] = Form(default_factory=list),
    motivo: str = Form(""),
    session: Session = Depends(db_session),
):
    item = get_item(session, item_id)
    try:
        if action == "aprovar":
            ap.approve(session, item, account_ids)
            flash(request, "ok", "Vídeo aprovado.")
        elif action == "rejeitar":
            ap.reject(session, item, motivo)
            flash(request, "ok", "Vídeo rejeitado.")
        elif action == "nova-versao":
            ap.request_new_version(session, item)
            flash(request, "ok", "Nova versão na fila do Editor, com o preset atual.")
        else:
            raise HTTPException(status_code=404, detail="Ação desconhecida")
    except ops.OperationError as exc:
        flash(request, "error", str(exc))
    return RedirectResponse(f"/aprovacao/{item_id}", status_code=303)
