"""Telas do Postador: Contas (Task 19), Nova publicação (21.1) e Envios (24)."""

import secrets
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import accounts as acc
from core import distribution as dist
from core import operations as ops
from core.models import Account, Batch, Item, Operation, PublishJob, Render
from core.operations import OperationError
from core.security import TokenCipher
from networks.base import AdapterError
from networks.youtube_shorts.adapter import authorize_url
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


def settings_of(request: Request):
    return request.app.state.settings


def cipher_of(request: Request) -> TokenCipher | None:
    key = settings_of(request).token_encryption_key
    return TokenCipher(key) if key else None


def adapter_of(request: Request, platform: str):
    return request.app.state.adapter_factory(platform)


def google_redirect(request: Request) -> str:
    base = settings_of(request).public_base_url
    if base:
        return base.rstrip("/") + "/contas/youtube/retorno"
    return str(request.url_for("youtube_callback"))


# --- Contas -------------------------------------------------------------------------------


@router.get("/contas", response_class=HTMLResponse)
def accounts_page(request: Request, session: Session = Depends(db_session)) -> Response:
    settings = settings_of(request)
    accounts = acc.list_accounts(session)
    today = {
        a.id: session.scalar(
            select(func.count()).where(
                PublishJob.account_id == a.id,
                PublishJob.status == "published",
                PublishJob.published_at >= datetime.now(UTC).replace(hour=0, minute=0, second=0),
            )
        )
        for a in accounts
    }
    missing = [
        name
        for name, value in (
            ("GOOGLE_CLIENT_ID", settings.google_client_id),
            ("GOOGLE_CLIENT_SECRET", settings.google_client_secret),
            ("TOKEN_ENCRYPTION_KEY", settings.token_encryption_key),
        )
        if not value
    ]
    return render(
        request,
        "accounts.html",
        active="/contas",
        accounts=accounts,
        today=today,
        missing=missing,
        redirect_uri=google_redirect(request),
        timezones=TIMEZONES,
        flash=request.session.pop("flash", None),
    )


@router.get("/contas/youtube/conectar")
def youtube_connect(request: Request) -> Response:
    settings = settings_of(request)
    if not (settings.google_client_id and settings.google_client_secret and cipher_of(request)):
        flash(
            request,
            "error",
            "Preencha GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET e "
            "TOKEN_ENCRYPTION_KEY antes de conectar.",
        )
        return RedirectResponse("/contas", status_code=303)
    state = secrets.token_urlsafe(24)
    request.session["google_state"] = state
    return RedirectResponse(
        authorize_url(settings.google_client_id, google_redirect(request), state), status_code=302
    )


@router.get("/contas/youtube/retorno", name="youtube_callback")
def youtube_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    session: Session = Depends(db_session),
) -> Response:
    expected = request.session.pop("google_state", None)
    if error:
        flash(request, "error", f"Google recusou a conexão: {error}.")
        return RedirectResponse("/contas", status_code=303)
    if not expected or not secrets.compare_digest(expected, state) or not code:
        flash(request, "error", "Retorno do Google inválido (state). Tente conectar de novo.")
        return RedirectResponse("/contas", status_code=303)
    adapter = adapter_of(request, "youtube")
    try:
        credentials = adapter.exchange_code(code, google_redirect(request))
        external_id, name = adapter.account_info(credentials)
    except AdapterError as exc:
        flash(request, "error", f"Não foi possível conectar: {exc}")
        return RedirectResponse("/contas", status_code=303)
    account = acc.connect(
        session,
        cipher_of(request),
        platform="youtube",
        external_id=external_id,
        name=name,
        credentials=credentials,
    )
    flash(
        request,
        "ok",
        f"Canal {account.name} conectado. Ligue-o às operações no canvas (bloco Conta).",
    )
    return RedirectResponse("/contas", status_code=303)


def get_account(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    return account


@router.post("/contas/{account_id}/acao")
def account_action(
    request: Request,
    account_id: int,
    acao: str = Form(...),
    session: Session = Depends(db_session),
) -> Response:
    account = get_account(session, account_id)
    try:
        acc.change_status(session, account, acao)
        flash(request, "ok", f"{account.name}: {account.status}.")
    except OperationError as exc:
        flash(request, "error", str(exc))
    return RedirectResponse("/contas", status_code=303)


@router.post("/contas/{account_id}/testar")
def account_test(request: Request, account_id: int, session: Session = Depends(db_session)):
    account = get_account(session, account_id)
    try:
        credentials = acc.credentials(cipher_of(request), account)
        _, name = adapter_of(request, account.platform).account_info(credentials)
        if account.status == "error":
            account.status = "connected"
        flash(request, "ok", f"Conexão ok: {name}.")
    except (AdapterError, OperationError, ValueError) as exc:
        acc.mark_error(session, account, str(exc))
        flash(request, "error", f"Falhou: {exc}")
    return RedirectResponse("/contas", status_code=303)


@router.post("/contas/{account_id}/config")
def account_config(
    request: Request,
    account_id: int,
    daily_limit: int = Form(...),
    timezone: str = Form(...),
    session: Session = Depends(db_session),
) -> Response:
    account = get_account(session, account_id)
    try:
        acc.update_settings(session, account, daily_limit, timezone)
        flash(request, "ok", f"{account.name}: limite {daily_limit}/dia, fuso {timezone}.")
    except OperationError as exc:
        flash(request, "error", str(exc))
    return RedirectResponse("/contas", status_code=303)


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
