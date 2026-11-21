"""Automação das operações (Tasks 6.8 e 6.9), checada a cada minuto pelo Buscador.

Configuração em `automation` no fluxo da operação:
    daily_play_at  "HH:MM" no fuso da operação, ou null para desligar o Play diário;
    daily_target   vídeos por dia que a operação posta;
    stock_enabled  liga a reposição automática do estoque;
    stock_min_days dias de postagem que o estoque deve cobrir (recomendado: 3 a 7).
"""

import logging
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import executions as exe
from core.models import Execution, Item, Operation, PublishJob, Render
from core.operations import current_config

log = logging.getLogger("automation")

# Itens que já passaram pela Pesca e vão virar postagem (não contam os de reserva).
READY_STATUSES = ("eligible", "rendering", "awaiting_approval", "approved")
DEFAULT_TZ = "America/Sao_Paulo"


def settings_of(config: dict) -> tuple[dict, ZoneInfo]:
    auto = config.get("automation") or {}
    publish = next((n for n in config.get("nodes") or [] if n.get("type") == "publish"), {})
    tz = ZoneInfo((publish.get("config") or {}).get("timezone") or DEFAULT_TZ)
    return auto, tz


def parse_hhmm(value: str) -> time | None:
    try:
        hours, minutes = value.split(":")
        return time(int(hours), int(minutes))
    except (AttributeError, ValueError):
        return None


def has_open_execution(session: Session, operation_id: int) -> bool:
    return bool(
        session.scalar(
            select(func.count()).where(
                Execution.operation_id == operation_id,
                Execution.status.in_(("running", "paused")),
            )
        )
    )


def ready_stock(session: Session, operation_id: int) -> int:
    """Vídeos selecionados ainda não publicados em nenhuma conta."""
    published = (
        select(Render.item_id)
        .join(PublishJob, PublishJob.render_id == Render.id)
        .where(PublishJob.status == "published")
    )
    return session.scalar(
        select(func.count()).where(
            Item.operation_id == operation_id,
            Item.status.in_(READY_STATUSES),
            (Item.status_reason.is_(None)) | (Item.status_reason != "reserva"),
            Item.id.not_in(published),
        )
    )


STOCK_BACKOFF = timedelta(minutes=30)


def stock_backoff(session: Session, operation_id: int, now: datetime) -> bool:
    """A última reposição terminou sem nada novo há pouco: não adianta buscar de novo já."""
    last = session.scalar(
        select(Execution)
        .where(Execution.operation_id == operation_id, Execution.trigger == "stock")
        .order_by(Execution.id.desc())
        .limit(1)
    )
    if last is None or last.started_at < now - STOCK_BACKOFF:
        return False
    return last.status == "partial"


def daily_play_due(
    session: Session, op: Operation, auto: dict, tz: ZoneInfo, now: datetime
) -> bool:
    at = parse_hhmm(auto.get("daily_play_at") or "")
    if at is None:
        return False
    local_now = now.astimezone(tz)
    if local_now.time() < at:
        return False
    start_of_day = datetime.combine(local_now.date(), time(0), tz).astimezone(UTC)
    already = session.scalar(
        select(func.count()).where(
            Execution.operation_id == op.id,
            Execution.trigger == "scheduled",
            Execution.started_at >= start_of_day,
            Execution.started_at < start_of_day + timedelta(days=1),
        )
    )
    return not already


def automation_tick(session: Session, now: datetime | None = None) -> list[int]:
    """Inicia as execuções devidas. Devolve os ids criados."""
    now = now or datetime.now(UTC)
    started: list[int] = []
    for op in session.scalars(select(Operation).where(Operation.status == "active")):
        config = current_config(session, op)
        if config is None:  # operação sem fluxo salvo: nada a automatizar (e não trava as outras)
            continue
        auto, tz = settings_of(config.config)
        if has_open_execution(session, op.id):
            continue
        if daily_play_due(session, op, auto, tz, now):
            ex = exe.start_execution(session, op, trigger="scheduled", now=now)
            started.append(ex.id)
            log.info("play diário", extra={"operation_id": op.id, "execution_id": ex.id})
            continue
        if auto.get("stock_enabled"):
            target = int(auto.get("daily_target") or 0) * int(auto.get("stock_min_days") or 0)
            stock = ready_stock(session, op.id)
            if target and stock < target and not stock_backoff(session, op.id, now):
                ex = exe.start_execution(
                    session, op, target_x=target - stock, trigger="stock", now=now
                )
                started.append(ex.id)
                log.info(
                    "reposição de estoque",
                    extra={"operation_id": op.id, "stock": stock, "target": target},
                )
    return started


def next_daily_play(auto: dict, tz: ZoneInfo, now: datetime) -> datetime | None:
    """Próximo Play diário, para mostrar na interface."""
    at = parse_hhmm(auto.get("daily_play_at") or "")
    if at is None:
        return None
    local = now.astimezone(tz)
    candidate = datetime.combine(local.date(), at, tz)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate
