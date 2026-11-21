"""Aprovação (Task 18): manual, em lote e "nova versão".

A aprovação vale para um render exato e para as contas escolhidas (REQ-APP-004). Só entram
itens aguardando aprovação, com permissão registrada (18.4). Novo render zera a aprovação.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import queue
from core.models import Event, Item, Operation, Render
from core.operations import OperationError, current_config


def _event(session: Session, item: Item, action: str, detail: dict | None = None) -> None:
    session.add(
        Event(
            entity="item",
            entity_id=item.id,
            operation_id=item.operation_id,
            action=action,
            detail=detail,
        )
    )


def latest_render(session: Session, item_id: int) -> Render | None:
    return session.scalar(
        select(Render).where(Render.item_id == item_id).order_by(Render.version.desc()).limit(1)
    )


def can_approve(session: Session, item: Item) -> str | None:
    """Motivo do bloqueio, ou None se pode aprovar."""
    if item.status != "awaiting_approval":
        return "Só vídeos aguardando aprovação podem ser aprovados."
    render = latest_render(session, item.id)
    if render is None or render.status != "ok":
        return "O último render não passou no controle de qualidade."
    return None


def approve(session: Session, item: Item, account_ids: list[int], by: str = "manual") -> Render:
    blocked = can_approve(session, item)
    if blocked:
        raise OperationError(blocked)
    if not account_ids:
        raise OperationError("Escolha ao menos uma conta.")
    render = latest_render(session, item.id)
    item.status = "approved"
    item.approved_by = by
    item.approved_render_id = render.id
    item.approved_account_ids = sorted(set(account_ids))
    item.approved_at = datetime.now(UTC)
    _event(session, item, "approved", {"render": render.version, "accounts": account_ids})
    return render


def reject(session: Session, item: Item, reason: str) -> None:
    if item.status not in ("awaiting_approval", "needs_fix", "approved"):
        raise OperationError("Este vídeo não pode ser rejeitado agora.")
    item.status = "rejected"
    item.status_reason = (reason or "rejeitado na aprovação").strip()[:500]
    item.approved_render_id = None
    item.approved_account_ids = None
    _event(session, item, "rejected", {"reason": item.status_reason})


def request_new_version(session: Session, item: Item) -> int:
    """Novo render com o preset atual da operação (18.2). Devolve o id da tarefa."""
    if item.status not in ("awaiting_approval", "needs_fix", "approved"):
        raise OperationError("Este vídeo não pode ganhar nova versão agora.")
    op = session.get(Operation, item.operation_id)
    config = current_config(session, op)
    renders = session.scalar(select(func.count()).where(Render.item_id == item.id)) or 0
    job = queue.enqueue(
        session,
        "render",
        f"render:{item.id}:{config.id}:v{renders + 1}",
        ref_id=item.id,
        operation_id=item.operation_id,
        execution_id=item.execution_id,
        priority="high",
        payload={"config_id": config.id},
    )
    _event(session, item, "new_version_requested", {"config_id": config.id})
    return job.id


def bulk(
    session: Session, item_ids: list[int], action: str, account_ids: list[int], reason: str = ""
) -> tuple[int, list[str]]:
    """Aprova ou rejeita vários. Devolve (feitos, motivos dos que ficaram de fora)."""
    done, skipped = 0, []
    for item in session.scalars(select(Item).where(Item.id.in_(item_ids))):
        try:
            if action == "approve":
                approve(session, item, account_ids)
            else:
                reject(session, item, reason)
            done += 1
        except OperationError as exc:
            skipped.append(f"#{item.id}: {exc}")
    return done, skipped


def queue_items(session: Session, operation_id: int | None = None) -> list[Item]:
    stmt = select(Item).where(Item.status == "awaiting_approval").order_by(Item.id)
    if operation_id:
        stmt = stmt.where(Item.operation_id == operation_id)
    return list(session.scalars(stmt))
