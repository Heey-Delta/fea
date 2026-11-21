"""Postador e Limpeza (Tasks 16, 20.2, 21.2, 22.4 e 24).

- `scheduler` (1 por minuto): distribuição automática, reavaliação de `pending_capacity` e
  envio para a fila `publish` de tudo que chegou na hora.
- `publish`: gera título/descrição/tags, envia pelo adaptador e trata o resultado:
  rate limit → `retry_wait` (2, 10, 30 min) e depois `failed`; timeout → `uncertain` e
  `check` antes de qualquer nova tentativa; token inválido → conta em erro, envio espera.
- `cleanup` (1 por minuto): apaga original e renders X minutos após a última publicação, e
  também dos rejeitados/duplicados. Registros, hashes e links ficam.
"""

import logging
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core import accounts as acc
from core import credentials as creds
from core import distribution as dist
from core import queue, titles
from core.config import Settings, get_settings
from core.models import Account, Event, Item, Operation, PublishJob, Render
from core.operations import current_config
from core.security import TokenCipher
from core.storage import Storage, get_storage
from networks import make_adapter, profile_for_platform
from networks.base import (
    AuthError,
    PlatformAdapter,
    PublishFailed,
    PublishRequest,
    RateLimited,
    TemporaryError,
    Uncertain,
)
from worker.handlers import register
from worker.runner import JobContext

log = logging.getLogger("worker.postador")

RETRY_WAITS_MIN = (2, 10, 30)
ACCOUNT_WAIT = timedelta(minutes=5)
QUOTA_TZ = ZoneInfo("America/Los_Angeles")  # a cota do Google zera à meia-noite do Pacífico
# Envios que impedem apagar os arquivos do vídeo (incertos e com falha também: 24.5).
BLOCKS_CLEANUP = (
    "planned",
    "pending_capacity",
    "uploading",
    "scheduled_platform",
    "processing",
    "retry_wait",
    "uncertain",
    "failed",
)

AdapterFactory = Callable[[str], PlatformAdapter]


def default_adapters(settings: Settings) -> AdapterFactory:
    return lambda platform: make_adapter(platform, settings)


def _event(
    session: Session,
    job: PublishJob,
    action: str,
    detail: dict | None = None,
    operation_id: int | None = None,
) -> None:
    session.add(
        Event(
            entity="publish_job",
            entity_id=job.id,
            operation_id=operation_id,
            action=action,
            detail=detail,
        )
    )


# --- Agendador ----------------------------------------------------------------------------


def due_jobs(session: Session, now: datetime) -> list[PublishJob]:
    return list(
        session.scalars(
            select(PublishJob)
            .where(PublishJob.status.in_(("planned", "retry_wait")), PublishJob.planned_at <= now)
            .order_by(PublishJob.planned_at)
            .limit(200)
        )
    )


def operation_of(session: Session, job: PublishJob) -> int | None:
    """Operação dona do envio (envio → render → item), para a fila separada (Task 31.1)."""
    return session.scalar(
        select(Item.operation_id)
        .join(Render, Render.item_id == Item.id)
        .where(Render.id == job.render_id)
    )


def enqueue_publish(
    session: Session, job: PublishJob, *, check: bool = False, run_at: datetime | None = None
) -> None:
    stamp = int((job.planned_at or datetime.now(UTC)).timestamp())
    kind = "check" if check else "publish"
    queue.enqueue(
        session,
        "publish",
        f"{kind}:{job.id}:{job.attempts}:{stamp}",
        ref_id=job.id,
        operation_id=operation_of(session, job),
        priority="high" if check else "normal",
        run_at=run_at,
        max_attempts=1,
        payload={"check": True} if check else None,
    )


def scheduler_tick(session: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    created = dist.auto_distribute(session, now)
    moved = dist.reevaluate_pending(session, now)
    due = due_jobs(session, now)
    for job in due:
        enqueue_publish(session, job)
    # Envios em processamento sem consulta na fila (ex.: worker reiniciado).
    for job in session.scalars(select(PublishJob).where(PublishJob.status == "processing")):
        enqueue_status(session, job, now)
    # Métricas: uma tarefa por conta a cada hora, quando há vídeos com métrica vencida.
    hour = now.strftime("%Y%m%d%H")
    for account_id in metrics_due(session, now):
        queue.enqueue(
            session,
            "publish",
            f"metrics:{account_id}:{hour}",
            ref_id=account_id,
            priority="low",
            max_attempts=1,
            payload={"metrics": True},
        )
    # Renovação diária dos tokens (Instagram expira em 60 dias sem uso; TikTok em 365).
    day = now.strftime("%Y%m%d")
    for account in session.scalars(
        select(Account).where(
            Account.status == "connected", Account.platform.in_(("tiktok", "instagram"))
        )
    ):
        queue.enqueue(
            session,
            "publish",
            f"refresh:{account.id}:{day}",
            ref_id=account.id,
            priority="low",
            max_attempts=1,
            payload={"refresh": True},
        )
    return {"batches": created, "pending_moved": moved, "enqueued": len(due)}


@register("scheduler")
def scheduler_job(ctx: JobContext) -> None:
    with ctx.session_factory() as session:
        result = scheduler_tick(session)
        session.commit()
    if result["enqueued"] or result["batches"]:
        log.info("agendador", extra=result)


# --- Envio --------------------------------------------------------------------------------


def uploads_today(session: Session, platform: str, now: datetime) -> int:
    start = datetime.combine(now.astimezone(QUOTA_TZ).date(), datetime.min.time(), QUOTA_TZ)
    return (
        session.scalar(
            select(func.count())
            .select_from(Event)
            .where(
                Event.entity == "platform_upload",
                Event.action == platform,
                Event.at >= start,
            )
        )
        or 0
    )


def next_quota_reset(now: datetime) -> datetime:
    local = now.astimezone(QUOTA_TZ)
    tomorrow = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), QUOTA_TZ)
    return (tomorrow + timedelta(minutes=5)).astimezone(UTC)


def make_metadata(
    session: Session, job: PublishJob, item: Item, config: dict, platform: str = "youtube"
) -> titles.Metadata:
    """Título na hora da publicação (16.1), com o corpus da operação e sem repetir a conta.

    Os limites de título, legenda e tags são os da rede da conta (Task 28.2).
    """
    profile = profile_for_platform(platform)
    publish = dist.publish_config(config)
    corpus = [
        t
        for t in session.scalars(
            select(Item.text)
            .where(Item.operation_id == item.operation_id, Item.text.is_not(None))
            .order_by(Item.id.desc())
            .limit(500)
        )
        if t
    ]
    recent = list(
        session.scalars(
            select(PublishJob.title)
            .where(PublishJob.account_id == job.account_id, PublishJob.title.is_not(None))
            .order_by(PublishJob.id.desc())
            .limit(100)
        )
    )
    return titles.generate(
        publish.get("titles") or {},
        item_text=item.text,
        corpus=corpus,
        recent_titles=recent,
        title_max=profile.title_max_chars,
        description_max=profile.description_max_chars,
        tags_max=profile.tags_max_chars,
        platform_tags=["shorts"] if platform == "youtube" else [],
        seed=job.id,
    )


def start_upload(session: Session, job_id: int, settings: Settings, now: datetime):
    """Trava o envio, confere conta e cota e marca `uploading`. None = não é hora de enviar."""
    job = session.get(PublishJob, job_id, with_for_update=True)
    if job is None or job.status not in ("planned", "retry_wait"):
        return None
    account = session.get(Account, job.account_id)
    render = session.get(Render, job.render_id)
    item = session.get(Item, render.item_id)
    op = session.get(Operation, item.operation_id)
    if not acc.usable(account):
        # 19.6: o envio espera a conta voltar; outras contas seguem.
        job.planned_at = now + ACCOUNT_WAIT
        job.status_reason = f"Conta {account.name} está em '{account.status}': aguardando."
        return None
    if render.status != "ok" or not render.output_file or render.files_deleted_at:
        job.status, job.status_reason = "failed", "Render indisponível para envio."
        _event(session, job, "failed", {"reason": job.status_reason}, op.id)
        return None
    if (
        account.platform == "youtube"
        and uploads_today(session, account.platform, now) >= settings.youtube_daily_upload_limit
    ):
        job.planned_at = next_quota_reset(now)
        job.status_reason = "Cota diária de uploads do projeto Google esgotada."
        return None
    config = current_config(session, op).config
    if job.title is None or job.description is None or job.tags is None:
        # Título escrito à mão na tela Publicações vale; o que faltar é gerado.
        meta = make_metadata(session, job, item, config, account.platform)
        if job.title is None:
            job.title, job.title_method = meta.title, meta.method
        if job.description is None:
            job.description = meta.description.replace(meta.title, job.title, 1)
        if job.tags is None:
            job.tags = meta.tags
    job.status, job.status_reason = "uploading", None
    job.attempts += 1
    session.add(
        Event(
            entity="platform_upload", entity_id=job.id, operation_id=op.id, action=account.platform
        )
    )
    privacy = dist.publish_config(config).get("privacy") or "public"
    return job, account, render, item, op, privacy, config


def run_publish(
    factory: sessionmaker,
    job_id: int,
    storage: Storage,
    settings: Settings,
    adapters: AdapterFactory,
    now: datetime | None = None,
) -> str | None:
    now = now or datetime.now(UTC)
    with factory() as session:
        started = start_upload(session, job_id, settings, now)
        session.commit()
        if started is None:
            return None
        job, account, render, item, op, privacy, config = started
        cipher = TokenCipher(settings.token_encryption_key)
        try:
            credentials = acc.credentials(cipher, account)
        except Exception as exc:  # noqa: BLE001 - token ilegível conta como erro da conta
            return auth_failed(session, job, account, op.id, str(exc), now)
        adapter = adapters(account.platform)
        try:
            fresh = adapter.fresh_credentials(credentials)
        except AuthError as exc:
            return auth_failed(session, job, account, op.id, str(exc), now)
        except (RateLimited, TemporaryError) as exc:
            return retry_or_fail(session, job, str(exc), now, op.id)
        if fresh != credentials:
            # Token renovado (TikTok e Instagram): grava o novo antes de usar.
            account.token_encrypted = cipher.encrypt(fresh)
            session.commit()
            credentials = fresh
        request = PublishRequest(
            file_path="",
            title=job.title,
            description=job.description or "",
            tags=job.tags or [],
            privacy=privacy,
        )
        render_key = render.output_file
        op_id, account_id = op.id, account.id

    if "needs_public_url" in adapter.capabilities:
        try:
            request.file_url = storage.url(render_key, expires_s=6 * 3600)
        except Exception:  # noqa: BLE001
            request.file_url = None
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "video.mp4"
        try:
            storage.get_file(render_key, path)
        except Exception as exc:  # noqa: BLE001
            with factory() as session:
                job = session.get(PublishJob, job_id)
                return retry_or_fail(session, job, f"Arquivo do render: {exc}", now, op_id)
        request.file_path = str(path)
        try:
            result = adapter.publish(credentials, request)
        except AuthError as exc:
            with factory() as session:
                return auth_failed(
                    session,
                    session.get(PublishJob, job_id),
                    session.get(Account, account_id),
                    op_id,
                    str(exc),
                    now,
                )
        except (RateLimited, TemporaryError) as exc:
            with factory() as session:
                job = session.get(PublishJob, job_id)
                return retry_or_fail(session, job, str(exc), now, op_id)
        except Uncertain as exc:
            with factory() as session:
                job = session.get(PublishJob, job_id)
                return mark_uncertain(session, job, adapter, str(exc), now, op_id)
        except PublishFailed as exc:
            with factory() as session:
                job = session.get(PublishJob, job_id)
                job.status, job.status_reason = "failed", str(exc)[:500]
                _event(session, job, "failed", {"reason": job.status_reason}, op_id)
                session.commit()
                return job.status

    with factory() as session:
        job = session.get(PublishJob, job_id)
        if result.status == "processing":
            return mark_processing(session, job, result.external_id, now, op_id)
        return dist.published(session, job, result.external_id, result.url, result.status, now)


def mark_processing(
    session: Session, job: PublishJob, external_id: str, now: datetime, operation_id: int | None
) -> str:
    """Envio aceito, a plataforma ainda processa (TikTok, Instagram). O agendador consulta."""
    job.status, job.external_id = "processing", external_id
    job.status_reason = "Enviado; a plataforma está processando."
    _event(session, job, "processing", {"external_id": external_id}, operation_id)
    enqueue_status(session, job, now + timedelta(minutes=1))
    session.commit()
    return job.status


def enqueue_status(session: Session, job: PublishJob, run_at: datetime) -> None:
    queue.enqueue(
        session,
        "publish",
        f"status:{job.id}:{int(run_at.timestamp()) // 60}",
        ref_id=job.id,
        operation_id=operation_of(session, job),
        run_at=run_at,
        max_attempts=1,
        payload={"status": True},
    )


PROCESSING_TIMEOUT = timedelta(hours=2)


def run_status(
    factory: sessionmaker,
    job_id: int,
    settings: Settings,
    adapters: AdapterFactory,
    now: datetime | None = None,
) -> str | None:
    """Consulta o processamento na plataforma: publicado, falhou ou ainda processando."""
    now = now or datetime.now(UTC)
    with factory() as session:
        job = session.get(PublishJob, job_id)
        if job is None or job.status != "processing":
            return None
        account = session.get(Account, job.account_id)
        render = session.get(Render, job.render_id)
        op_id = session.get(Item, render.item_id).operation_id
        try:
            credentials = acc.credentials(TokenCipher(settings.token_encryption_key), account)
            result = adapters(account.platform).status(credentials, job.external_id)
        except PublishFailed as exc:
            job.status, job.status_reason = "failed", str(exc)[:500]
            _event(session, job, "failed", {"reason": job.status_reason}, op_id)
            session.commit()
            return job.status
        except Exception as exc:  # noqa: BLE001 - erro passageiro: tenta na próxima rodada
            job.status_reason = f"Consulta falhou ({str(exc)[:200]}); tentando de novo."
            enqueue_status(session, job, now + timedelta(minutes=5))
            session.commit()
            return job.status
        if result is not None:
            return dist.published(session, job, result.external_id, result.url, "published", now)
        if job.updated_at and now - job.updated_at > PROCESSING_TIMEOUT:
            job.status = "uncertain"
            job.status_reason = "A plataforma não terminou de processar em 2 h: confira e decida."
            _event(session, job, "uncertain", {"reason": job.status_reason}, op_id)
        else:
            enqueue_status(session, job, now + timedelta(minutes=2))
        session.commit()
        return job.status


METRICS_EVERY = timedelta(hours=6)
METRICS_WINDOW = timedelta(days=30)


def metrics_due(session: Session, now: datetime) -> dict[int, list[int]]:
    """Envios publicados nos últimos 30 dias com métricas vencidas, por conta (Task 28.3)."""
    rows = session.execute(
        select(PublishJob.account_id, PublishJob.id).where(
            PublishJob.status == "published",
            PublishJob.external_id.is_not(None),
            PublishJob.published_at >= now - METRICS_WINDOW,
            (PublishJob.metrics_at.is_(None)) | (PublishJob.metrics_at <= now - METRICS_EVERY),
        )
    )
    out: dict[int, list[int]] = {}
    for account_id, job_id in rows:
        out.setdefault(account_id, []).append(job_id)
    return out


def run_metrics(
    factory: sessionmaker,
    account_id: int,
    settings: Settings,
    adapters: AdapterFactory,
    now: datetime | None = None,
) -> int:
    now = now or datetime.now(UTC)
    with factory() as session:
        account = session.get(Account, account_id)
        jobs = [session.get(PublishJob, i) for i in metrics_due(session, now).get(account_id, [])]
        if not jobs or not acc.usable(account):
            return 0
        try:
            credentials = acc.credentials(TokenCipher(settings.token_encryption_key), account)
            stats = adapters(account.platform).metrics(credentials, [j.external_id for j in jobs])
        except Exception as exc:  # noqa: BLE001 - métrica nunca derruba nada
            log.warning("métricas indisponíveis", extra={"account": account_id, "error": str(exc)})
            return 0
        for job in jobs:
            if job.external_id in stats:
                job.metrics = stats[job.external_id]
            job.metrics_at = now
        session.commit()
        return sum(1 for j in jobs if j.external_id in stats)


def auth_failed(
    session: Session,
    job: PublishJob,
    account: Account,
    operation_id: int,
    reason: str,
    now: datetime,
) -> str:
    acc.mark_error(session, account, reason)
    job.status = "planned"
    job.attempts = max(0, job.attempts - 1)
    job.planned_at = now + ACCOUNT_WAIT
    job.status_reason = f"Conta em erro: {reason[:300]}"
    _event(session, job, "account_error", {"reason": reason[:300]}, operation_id)
    session.commit()
    return job.status


def retry_or_fail(
    session: Session, job: PublishJob, reason: str, now: datetime, operation_id: int | None
) -> str:
    """24.2 e 24.4: só este envio volta para a fila, com espera crescente."""
    if job.attempts <= len(RETRY_WAITS_MIN):
        wait = RETRY_WAITS_MIN[job.attempts - 1]
        job.status, job.planned_at = "retry_wait", now + timedelta(minutes=wait)
        job.status_reason = f"{reason[:400]} Nova tentativa em {wait} min."
    else:
        job.status, job.status_reason = "failed", f"{reason[:400]} Tentativas esgotadas."
    _event(session, job, job.status, {"reason": reason[:300]}, operation_id)
    session.commit()
    return job.status


def mark_uncertain(
    session: Session,
    job: PublishJob,
    adapter: PlatformAdapter,
    reason: str,
    now: datetime,
    operation_id: int | None,
) -> str:
    """24.3: não reenviar às cegas. Confere na plataforma; sem `check`, decisão manual."""
    job.status = "uncertain"
    if "check" in adapter.capabilities:
        job.status_reason = f"{reason[:300]} Conferindo na plataforma."
        enqueue_publish(session, job, check=True, run_at=now + timedelta(minutes=2))
    else:
        job.status_reason = f"{reason[:300]} Confira na plataforma e decida na tela de envios."
    _event(session, job, "uncertain", {"reason": reason[:300]}, operation_id)
    session.commit()
    return job.status


def run_check(
    factory: sessionmaker,
    job_id: int,
    settings: Settings,
    adapters: AdapterFactory,
    now: datetime | None = None,
) -> str | None:
    now = now or datetime.now(UTC)
    with factory() as session:
        job = session.get(PublishJob, job_id)
        if job is None or job.status != "uncertain":
            return None
        account = session.get(Account, job.account_id)
        since = (job.updated_at - timedelta(minutes=30)).astimezone(UTC).isoformat()
        title, platform = job.title or "", account.platform
        try:
            credentials = acc.credentials(TokenCipher(settings.token_encryption_key), account)
            found = adapters(platform).check(credentials, title, since)
        except Exception as exc:  # noqa: BLE001
            job.status_reason = f"Conferência falhou ({str(exc)[:200]}): decisão manual."
            session.commit()
            return job.status
        if found is not None:
            return dist.published(session, job, found.external_id, found.url, "published", now)
        # Não foi criado: pode reenviar com segurança (conta como tentativa).
        render = session.get(Render, job.render_id)
        op_id = session.get(Item, render.item_id).operation_id
        return retry_or_fail(session, job, "Envio não encontrado na plataforma.", now, op_id)


def run_refresh(
    factory: sessionmaker, account_id: int, settings: Settings, adapters: AdapterFactory
) -> bool:
    """Renova o token da conta e grava se mudou. Token recusado → conta em erro."""
    with factory() as session:
        account = session.get(Account, account_id)
        if account is None or not acc.usable(account):
            return False
        cipher = TokenCipher(settings.token_encryption_key)
        try:
            credentials = acc.credentials(cipher, account)
            fresh = adapters(account.platform).fresh_credentials(credentials)
        except AuthError as exc:
            acc.mark_error(session, account, str(exc))
            session.commit()
            return False
        except Exception as exc:  # noqa: BLE001 - tenta de novo amanhã
            log.warning("renovação falhou", extra={"account": account_id, "error": str(exc)})
            return False
        if fresh != credentials:
            account.token_encrypted = cipher.encrypt(fresh)
            session.commit()
            return True
        return False


@register("publish")
def publish_job(ctx: JobContext) -> None:
    settings = creds.load(ctx.session_factory, get_settings())
    adapters = default_adapters(settings)
    payload = ctx.payload or {}
    if payload.get("check"):
        run_check(ctx.session_factory, ctx.ref_id, settings, adapters)
    elif payload.get("status"):
        run_status(ctx.session_factory, ctx.ref_id, settings, adapters)
    elif payload.get("metrics"):
        run_metrics(ctx.session_factory, ctx.ref_id, settings, adapters)
    elif payload.get("refresh"):
        run_refresh(ctx.session_factory, ctx.ref_id, settings, adapters)
    else:
        run_publish(ctx.session_factory, ctx.ref_id, get_storage(), settings, adapters)


# --- Limpeza ------------------------------------------------------------------------------


def retention_minutes(session: Session, op: Operation, cache: dict[int, int]) -> int:
    if op.id not in cache:
        retention = current_config(session, op).config.get("retention") or {}
        cache[op.id] = int(retention.get("delete_after_minutes", 30))
    return cache[op.id]


def delete_files(session: Session, storage: Storage, item: Item, now: datetime) -> int:
    deleted = 0
    keys = [item.original_file] if item.original_file else []
    renders = list(session.scalars(select(Render).where(Render.item_id == item.id)))
    keys += [r.output_file for r in renders if r.output_file and not r.files_deleted_at]
    for key in keys:
        try:
            storage.delete(key)
            deleted += 1
        except Exception:  # noqa: BLE001
            log.warning("falha ao apagar", extra={"key": key})
            return -1
    for r in renders:
        r.files_deleted_at = r.files_deleted_at or now
    item.files_deleted_at = now
    session.add(
        Event(
            entity="item",
            entity_id=item.id,
            operation_id=item.operation_id,
            action="files_deleted",
            detail={"files": deleted},
        )
    )
    return deleted


def run_cleanup(session: Session, storage: Storage, now: datetime | None = None) -> int:
    """Apaga os arquivos que passaram do prazo. Devolve quantos itens foram limpos."""
    now = now or datetime.now(UTC)
    cleaned, cache = 0, {}
    blocked_items = (
        select(Render.item_id)
        .join(PublishJob, PublishJob.render_id == Render.id)
        .where(PublishJob.status.in_(BLOCKS_CLEANUP))
    )
    published_due = session.scalars(
        select(Item)
        .where(
            Item.files_deleted_at.is_(None),
            Item.delete_after.is_not(None),
            Item.delete_after <= now,
            Item.id.not_in(blocked_items),
        )
        .limit(200)
    )
    for item in list(published_due):
        if delete_files(session, storage, item, now) >= 0:
            cleaned += 1
    # 24.6: rejeitados e duplicados, X minutos após a decisão.
    decided = session.scalars(
        select(Item)
        .where(
            Item.files_deleted_at.is_(None),
            Item.status.in_(("rejected", "duplicate")),
            Item.id.not_in(blocked_items),
        )
        .limit(200)
    )
    for item in list(decided):
        op = session.get(Operation, item.operation_id)
        if item.updated_at + timedelta(minutes=retention_minutes(session, op, cache)) > now:
            continue
        if delete_files(session, storage, item, now) >= 0:
            cleaned += 1
    return cleaned


def measure_bucket(session: Session, storage, now: datetime | None = None) -> int | None:
    """De hora em hora mede o bucket do R2 para o limite de armazenamento (core/usage.py)."""
    from core import usage
    from core.storage import is_remote, unwrap

    now = now or datetime.now(UTC)
    if not is_remote(storage):
        return None
    last = usage.get_setting(session, usage.MEASURED_KEY)
    if last and now - datetime.fromisoformat(last) < timedelta(hours=1):
        return None
    size = unwrap(storage).total_bytes()
    usage.set_storage(session, size, now)
    return size


@register("cleanup")
def cleanup_job(ctx: JobContext) -> None:
    with ctx.session_factory() as session:
        storage = get_storage()
        cleaned = run_cleanup(session, storage)
        session.commit()
        try:
            measure_bucket(session, storage)
            session.commit()
        except Exception:  # noqa: BLE001 - a medição volta a tentar na próxima rodada
            session.rollback()
            log.exception("falha ao medir o bucket")
    if cleaned:
        log.info("limpeza", extra={"items": cleaned})
