"""Telas do Postador: Nova publicação (21.1) e Envios (24). Contas ficam em web/access.py."""

import secrets
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import distribution as dist
from core import operations as ops
from core.models import Account, Batch, Item, Operation, PublishJob, Render
from core.operations import OperationError
from web.common import db_session, render, require_user

router = APIRouter(dependencies=[Depends(require_user)])

STATUS_LABEL = {
    "planned": "agendado",
    "pending_capacity": "sem vaga",
    "uploading": "enviando",
    "scheduled_platform": "agendado na plataforma",
    "processing": "processando",
    "retry_wait": "nova tentativa",
    "uncertain": "incerto",
    "published": "publicado",
    "failed": "falha",
    "skipped": "pulado",
    "cancelled": "cancelado",
}
TIMEZONES = ("America/Sao_Paulo", "America/Manaus", "America/New_York", "Europe/Lisbon", "UTC")


def flash(request: Request, kind: str, text: str) -> None:
    request.session["flash"] = {"kind": kind, "text": text}


# --- Nova publicação ----------------------------------------------------------------------


def op_accounts(session: Session, op: Operation) -> list[Account]:
    ids = ops.linked_account_ids(ops.current_config(session, op).config)
    if not ids:
        return []
    return list(session.scalars(select(Account).where(Account.id.in_(ids)).order_by(Account.id)))


def parse_start(value: str, tz: str) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo(tz)).astimezone(UTC)


@router.get("/publicacoes/nova", response_class=HTMLResponse)
def new_page(request: Request, op: int | None = None, session: Session = Depends(db_session)):
    operations = list(
        session.scalars(
            select(Operation)
            .where(Operation.status.in_(("active", "paused")))
            .order_by(Operation.name)
        )
    )
    selected = session.get(Operation, op) if op else (operations[0] if operations else None)
    form = request.session.pop("publish_form", None) or {}
    context = {
        "operations": operations,
        "op": selected,
        "items": [],
        "accounts": [],
        "publish": {},
        "preview": None,
    }
    if selected:
        context["items"] = dist.schedulable_items(session, selected.id)
        context["accounts"] = op_accounts(session, selected)
        context["publish"] = dist.publish_config(ops.current_config(session, selected).config)
        if form.get("preview"):
            try:
                rows = dist.preview(
                    session,
                    selected,
                    item_ids=form["item_ids"],
                    account_ids=form["account_ids"],
                    mode=form["mode"],
                    interval_min=form["interval_min"],
                    first_immediate=form["first_immediate"],
                    start_at=parse_start(form["start_at"], form["tz"]),
                )
                names = {a.id: a.name for a in context["accounts"]}
                context["preview"] = [
                    {
                        "item": r.item_id,
                        "account": names.get(r.account_id, r.account_id),
                        "at": r.planned_at.astimezone(ZoneInfo(form["tz"]))
                        if r.planned_at
                        else None,
                        "status": STATUS_LABEL[r.status],
                        "reason": r.reason,
                    }
                    for r in rows
                ]
            except (OperationError, ValueError) as exc:
                context["flash"] = {"kind": "error", "text": str(exc)}
    context.setdefault("flash", request.session.pop("flash", None))
    return render(
        request,
        "publication_new.html",
        active="/publicacoes",
        form=form,
        request_key=secrets.token_hex(16),
        timezones=TIMEZONES,
        **context,
    )


@router.post("/publicacoes/nova")
def new_submit(
    request: Request,
    operation_id: int = Form(...),
    item_ids: list[int] = Form([]),
    account_ids: list[int] = Form([]),
    mode: str = Form("rotation"),
    interval_min: int = Form(30),
    first_immediate: bool = Form(False),
    start_at: str = Form(""),
    tz: str = Form("America/Sao_Paulo"),
    acao: str = Form("criar"),
    request_key: str = Form(...),
    session: Session = Depends(db_session),
) -> Response:
    op = session.get(Operation, operation_id)
    if op is None:
        raise HTTPException(status_code=404, detail="Operação não encontrada")
    form = {
        "item_ids": item_ids,
        "account_ids": account_ids,
        "mode": mode,
        "interval_min": interval_min,
        "first_immediate": first_immediate,
        "start_at": start_at,
        "tz": tz,
    }
    if acao == "previa":
        request.session["publish_form"] = {**form, "preview": True}
        return RedirectResponse(f"/publicacoes/nova?op={op.id}#previa", status_code=303)
    try:
        if not item_ids:
            raise OperationError("Escolha ao menos um vídeo.")
        if not account_ids:
            raise OperationError("Escolha ao menos uma conta.")
        batch, created = dist.create_batch(
            session,
            op,
            item_ids=item_ids,
            account_ids=account_ids,
            mode=mode,
            interval_min=interval_min,
            first_immediate=first_immediate,
            start_at=parse_start(start_at, tz),
            request_key=f"manual:{request_key}",
        )
    except (OperationError, ValueError) as exc:
        request.session["publish_form"] = form
        flash(request, "error", str(exc))
        return RedirectResponse(f"/publicacoes/nova?op={op.id}", status_code=303)
    total = session.scalar(select(func.count()).where(PublishJob.batch_id == batch.id))
    flash(
        request, "ok", f"Lote #{batch.id} {'criado' if created else 'já existia'}: {total} envios."
    )
    return RedirectResponse(f"/publicacoes?lote={batch.id}", status_code=303)


# --- Envios -------------------------------------------------------------------------------


@router.get("/publicacoes", response_class=HTMLResponse)
def jobs_page(
    request: Request,
    status: str = "",
    op: int | None = None,
    lote: int | None = None,
    session: Session = Depends(db_session),
) -> Response:
    stmt = (
        select(PublishJob, Account, Item, Batch)
        .join(Account, Account.id == PublishJob.account_id)
        .join(Render, Render.id == PublishJob.render_id)
        .join(Item, Item.id == Render.item_id)
        .join(Batch, Batch.id == PublishJob.batch_id)
    )
    if status:
        stmt = stmt.where(PublishJob.status == status)
    if op:
        stmt = stmt.where(Batch.operation_id == op)
    if lote:
        stmt = stmt.where(PublishJob.batch_id == lote)
    rows = session.execute(
        stmt.order_by(PublishJob.planned_at.desc().nulls_last(), PublishJob.id.desc()).limit(300)
    ).all()
    counts = dict(
        session.execute(select(PublishJob.status, func.count()).group_by(PublishJob.status)).all()
    )
    return render(
        request,
        "publications.html",
        active="/publicacoes",
        rows=rows,
        counts=counts,
        labels=STATUS_LABEL,
        status=status,
        op=op,
        lote=lote,
        operations=list(session.scalars(select(Operation).order_by(Operation.name))),
        flash=request.session.pop("flash", None),
    )


@router.post("/publicacoes/{job_id}/decidir")
def decide(
    request: Request,
    job_id: int,
    decisao: str = Form(...),
    url: str = Form(""),
    session: Session = Depends(db_session),
) -> Response:
    job = session.get(PublishJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Envio não encontrado")
    try:
        if decisao == "cancel" and job.status in ("planned", "pending_capacity", "retry_wait"):
            dist.cancel_job(session, job)
        else:
            dist.resolve_uncertain(session, job, decisao, url.strip())
        flash(request, "ok", f"Envio #{job.id}: {STATUS_LABEL[job.status]}.")
    except OperationError as exc:
        flash(request, "error", str(exc))
    return RedirectResponse(request.headers.get("referer") or "/publicacoes", status_code=303)
