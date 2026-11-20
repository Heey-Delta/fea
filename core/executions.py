"""Execuções (Play) da operação (Task 6).

O Play cria uma execução com a configuração congelada e põe uma tarefa `collect` na fila do
Buscador. A execução fecha quando a busca termina: `completed` se achou X elegíveis, senão
`partial` com o motivo (REQ-EXEC-004).
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import queue
from core.models import Event, Execution, Item, Operation, OperationConfig
from core.operations import OperationError, current_config
from core.states import EXECUTION_CRITERIA, PRIORITY

FINISHED = ("completed", "partial", "cancelled")


def fishing_config(config: dict) -> dict:
    node = next((n for n in config.get("nodes") or [] if n.get("type") == "fishing"), None)
    return (node or {}).get("config") or {}


def _event(session: Session, ex: Execution, action: str, detail: dict | None = None) -> None:
    session.add(
        Event(
            entity="execution",
            entity_id=ex.id,
            operation_id=ex.operation_id,
            action=action,
            detail=detail,
        )
    )


def start_execution(
    session: Session,
    op: Operation,
    *,
    target_x: int | None = None,
    search_budget: int | None = None,
    criteria: str | None = None,
    priority: str = "normal",
    source_ids: list[int] | None = None,
    trigger: str = "manual",
    now: datetime | None = None,
) -> Execution:
    """Play: só em operação ativa (Task 4.4). Valores vazios vêm do bloco Pesca."""
    if op.status != "active":
        raise OperationError("Só operações ativas aceitam Play.")
    config = current_config(session, op)
    fishing = fishing_config(config.config)
    target_x = int(target_x or fishing.get("target_x") or 10)
    search_budget = int(search_budget or fishing.get("search_budget") or 300)
    criteria = criteria or fishing.get("criteria") or "recent"
    if target_x <= 0 or search_budget <= 0:
        raise OperationError("Quantidade e orçamento precisam ser maiores que zero.")
    if criteria not in EXECUTION_CRITERIA or priority not in PRIORITY:
        raise OperationError("Critério ou prioridade inválidos.")
    ex = Execution(
        operation_id=op.id,
        config_id=config.id,
        trigger=trigger,
        target_x=target_x,
        search_budget=search_budget,
        criteria=criteria,
        priority=priority,
        source_ids=source_ids or None,
        status="running",
        stats={},
    )
    if now is not None:
        ex.started_at = now  # automação: o horário do tick, não o do banco
    session.add(ex)
    session.flush()
    queue.enqueue(
        session,
        "collect",
        f"collect:{ex.id}",
        ref_id=ex.id,
        operation_id=op.id,
        execution_id=ex.id,
        priority=priority,
    )
    _event(session, ex, "started", {"trigger": trigger, "target_x": target_x})
    return ex


def pause(session: Session, ex: Execution) -> None:
    if ex.status != "running":
        raise OperationError("Só uma execução rodando pode ser pausada.")
    ex.status = "paused"
    _event(session, ex, "paused")


def resume(session: Session, ex: Execution) -> None:
    if ex.status != "paused":
        raise OperationError("Só uma execução pausada pode ser retomada.")
    ex.status = "running"
    _event(session, ex, "resumed")
    session.flush()
    # Acorda os workers: as tarefas desta execução voltaram a valer.
    session.execute(select(func.pg_notify(queue.NOTIFY_CHANNEL, "resume")))


def cancel(session: Session, ex: Execution) -> int:
    """Cancela as tarefas na fila. Itens já criados ficam (REQ-EXEC-006)."""
    if ex.status in FINISHED:
        raise OperationError("A execução já terminou.")
    ex.status = "cancelled"
    ex.finished_at = datetime.now(UTC)
    cancelled = queue.cancel_execution_jobs(session, ex.id)
    _event(session, ex, "cancelled", {"jobs_cancelled": cancelled})
    return cancelled


def finish(session: Session, ex: Execution, selected: int, reason: str | None) -> None:
    if ex.status == "cancelled":
        return
    ex.finished_at = datetime.now(UTC)
    if selected >= ex.target_x:
        ex.status = "completed"
        ex.shortfall_reason = None
    else:
        ex.status = "partial"
        ex.shortfall_reason = f"{reason}; {selected} elegíveis de {ex.target_x}"
    _event(session, ex, ex.status, {"selected": selected})


def counters(session: Session, execution_id: int) -> dict[str, int]:
    """Contadores pela contagem real dos itens (Task 6.6), mais os já vistos antes."""
    rows = dict(
        session.execute(
            select(Item.status, func.count())
            .where(Item.execution_id == execution_id)
            .group_by(Item.status)
        ).all()
    )
    ex = session.get(Execution, execution_id)
    already_seen = (ex.stats or {}).get("already_seen", 0) if ex else 0
    created = sum(rows.values())
    reserve = session.scalar(
        select(func.count()).where(
            Item.execution_id == execution_id,
            Item.status == "eligible",
            Item.status_reason == "reserva",
        )
    )
    return {
        "examinados": created + already_seen,
        "duplicados": rows.get("duplicate", 0) + already_seen,
        "rejeitados": rows.get("rejected", 0),
        "pendentes_permissao": rows.get("pending_permission", 0),
        "elegiveis": rows.get("eligible", 0)
        + rows.get("rendering", 0)
        + rows.get("needs_fix", 0)
        + rows.get("awaiting_approval", 0)
        + rows.get("approved", 0),
        "reserva": reserve or 0,
        "renderizados": rows.get("awaiting_approval", 0) + rows.get("approved", 0),
        "aguardando_aprovacao": rows.get("awaiting_approval", 0),
        "com_erro": rows.get("needs_fix", 0),
    }


def list_executions(session: Session, operation_id: int, limit: int = 50) -> list[Execution]:
    return list(
        session.scalars(
            select(Execution)
            .where(Execution.operation_id == operation_id)
            .order_by(Execution.id.desc())
            .limit(limit)
        )
    )


def config_of(session: Session, ex: Execution) -> dict:
    return session.get(OperationConfig, ex.config_id).config
