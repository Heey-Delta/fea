"""Fila de itens (Task 8): visão geral e por operação, filtros por etapa e ações em lote.

Etapas (REQ-QUEUE-005): pesca (descobertos, sem permissão, elegíveis, editando), editados
(aguardando aprovação, corrigir, aprovados), exclusão (com prazo de apagar) e descartados.
Ordem: prioridade da execução, depois score (8.5).
"""

from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from core import approval, queue
from core.models import Event, Execution, Item, Operation, Source

STAGES = {
    "pesca": ("discovered", "pending_permission", "eligible", "rendering"),
    "editados": ("awaiting_approval", "needs_fix", "approved"),
    "descartados": ("rejected", "duplicate"),
}
STAGE_LABEL = {
    "pesca": "Pesca",
    "editados": "Editados",
    "exclusao": "Exclusão",
    "descartados": "Descartados",
}
STATUS_LABEL = {
    "discovered": "descoberto",
    "duplicate": "duplicado",
    "rejected": "rejeitado",
    "pending_permission": "sem permissão",
    "eligible": "elegível",
    "rendering": "editando",
    "needs_fix": "corrigir",
    "awaiting_approval": "aguardando aprovação",
    "approved": "aprovado",
}
PRIORITY_ORDER = case({"high": 0, "normal": 1, "low": 2}, value=Item.priority, else_=1)
ACTIONS = {
    "release": "Liberar permissão e baixar",
    "rerender": "Nova versão (render)",
    "reject": "Rejeitar",
    "priority_high": "Prioridade alta",
}


def query(operation_id: int | None = None, stage: str = "", status: str = ""):
    stmt = select(Item)
    if operation_id:
        stmt = stmt.where(Item.operation_id == operation_id)
    if stage == "exclusao":
        stmt = stmt.where(Item.delete_after.is_not(None), Item.files_deleted_at.is_(None))
    elif stage in STAGES:
        stmt = stmt.where(Item.status.in_(STAGES[stage]))
    if status:
        stmt = stmt.where(Item.status == status)
    return stmt


def list_items(session: Session, operation_id=None, stage="", status="", limit=300) -> list[Item]:
    stmt = query(operation_id, stage, status).order_by(
        PRIORITY_ORDER, Item.score.desc(), Item.id.desc()
    )
    return list(session.scalars(stmt.limit(limit)))


def stage_counts(session: Session, operation_id: int | None = None) -> dict[str, int]:
    rows = dict(
        session.execute(
            query(operation_id).with_only_columns(Item.status, func.count()).group_by(Item.status)
        ).all()
    )
    counts = {stage: sum(rows.get(s, 0) for s in statuses) for stage, statuses in STAGES.items()}
    counts["exclusao"] = (
        session.scalar(query(operation_id, "exclusao").with_only_columns(func.count())) or 0
    )
    counts.update({f"status:{k}": v for k, v in rows.items()})
    return counts


def summary(session: Session, item_ids: list[int], action: str) -> dict:
    """Resumo antes de confirmar (REQ-UI-005): quantos entram e quantos ficam de fora."""
    items = list(session.scalars(select(Item).where(Item.id.in_(item_ids))))
    ok, skipped = [], []
    for item in items:
        reason = blocked(session, item, action)
        (skipped if reason else ok).append((item, reason))
    by_status: dict[str, int] = {}
    for item, _ in ok:
        by_status[STATUS_LABEL[item.status]] = by_status.get(STATUS_LABEL[item.status], 0) + 1
    return {
        "action": action,
        "label": ACTIONS[action],
        "ok": ok,
        "skipped": skipped,
        "by_status": by_status,
    }


def blocked(session: Session, item: Item, action: str) -> str | None:
    if action == "release":
        if item.status != "pending_permission":
            return "não está sem permissão"
        source = session.get(Source, item.source_id)
        if not (source and source.permission_note):
            return "a fonte ainda não tem permissão registrada (canvas → bloco Fonte)"
    elif action == "rerender":
        if item.status not in ("awaiting_approval", "needs_fix", "approved"):
            return "só editados aceitam nova versão"
    elif action == "reject":
        if item.status in ("rejected", "duplicate", "rendering"):
            return "não pode ser rejeitado agora"
    elif action == "priority_high":
        if item.status in ("rejected", "duplicate"):
            return "descartado"
    else:
        return "ação desconhecida"
    return None


def apply(session: Session, item_ids: list[int], action: str, reason: str = "") -> tuple[int, int]:
    """Executa a ação nos itens permitidos. Devolve (feitos, pulados)."""
    done = skipped = 0
    for item in session.scalars(select(Item).where(Item.id.in_(item_ids))):
        if blocked(session, item, action):
            skipped += 1
            continue
        if action == "release":
            item.status, item.status_reason = "discovered", "permissão liberada na fila"
            queue.enqueue(
                session,
                "collect",
                f"release:{item.id}",
                operation_id=item.operation_id,
                execution_id=item.execution_id,
                priority="high",
                payload={"release_item": item.id},
            )
        elif action == "rerender":
            approval.request_new_version(session, item)
        elif action == "reject":
            item.status = "rejected"
            item.status_reason = (reason or "rejeitado na fila")[:500]
            item.approved_render_id = None
            item.approved_account_ids = None
        elif action == "priority_high":
            item.priority = "high"
        session.add(
            Event(
                entity="item",
                entity_id=item.id,
                operation_id=item.operation_id,
                action=f"queue_{action}",
                detail={"reason": reason} if reason else None,
            )
        )
        done += 1
    return done, skipped


def context(session: Session, items: list[Item]) -> dict:
    """Nomes de operação e execução para a tabela, sem uma consulta por linha."""
    op_ids = {i.operation_id for i in items}
    ops = {o.id: o.name for o in session.scalars(select(Operation).where(Operation.id.in_(op_ids)))}
    ex_ids = {i.execution_id for i in items if i.execution_id}
    exs = {e.id: e for e in session.scalars(select(Execution).where(Execution.id.in_(ex_ids)))}
    return {"op_names": ops, "executions": exs, "now": datetime.now(UTC)}
