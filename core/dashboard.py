"""Dashboard (Task 25): indicadores clicáveis e painel de erros alimentado por `events`."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import Account, Event, Execution, Item, Operation, PublishJob

ERROR_ACTIONS = ("failed", "error", "account_error", "uncertain", "retry_wait")


def kpis(session: Session, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    day = now - timedelta(hours=24)

    def count(stmt) -> int:
        return session.scalar(stmt) or 0

    jobs = select(func.count()).select_from(PublishJob)
    items = select(func.count()).select_from(Item)
    return [
        {
            "label": "Operações ativas",
            "href": "/operacoes",
            "value": count(select(func.count()).where(Operation.status == "active")),
        },
        {
            "label": "Execuções rodando",
            "href": "/operacoes",
            "value": count(select(func.count()).where(Execution.status == "running")),
        },
        {
            "label": "Na pesca",
            "href": "/fila?etapa=pesca",
            "value": count(items.where(Item.status.in_(("discovered", "eligible", "rendering")))),
        },
        {
            "label": "Sem permissão",
            "href": "/fila?estado=pending_permission",
            "value": count(items.where(Item.status == "pending_permission")),
        },
        {
            "label": "Aguardando aprovação",
            "href": "/aprovacao",
            "value": count(items.where(Item.status == "awaiting_approval")),
        },
        {
            "label": "Estoque de editados",
            "href": "/fila?estado=approved",
            "value": count(items.where(Item.status == "approved")),
        },
        {
            "label": "Agendados",
            "href": "/publicacoes?status=planned",
            "value": count(jobs.where(PublishJob.status == "planned")),
        },
        {
            "label": "Publicados (24 h)",
            "href": "/publicacoes?status=published",
            "value": count(
                jobs.where(PublishJob.status == "published", PublishJob.published_at >= day)
            ),
        },
        {
            "label": "Incertos",
            "href": "/publicacoes?status=uncertain",
            "value": count(jobs.where(PublishJob.status == "uncertain")),
            "alert": True,
        },
        {
            "label": "Falhas",
            "href": "/publicacoes?status=failed",
            "value": count(jobs.where(PublishJob.status == "failed")),
            "alert": True,
        },
        {
            "label": "Corrigir (QC)",
            "href": "/fila?estado=needs_fix",
            "value": count(items.where(Item.status == "needs_fix")),
            "alert": True,
        },
        {
            "label": "Contas com erro",
            "href": "/contas",
            "value": count(select(func.count()).where(Account.status == "error")),
            "alert": True,
        },
        {
            "label": "Na fila de exclusão",
            "href": "/fila?etapa=exclusao",
            "value": count(
                items.where(Item.delete_after.is_not(None), Item.files_deleted_at.is_(None))
            ),
        },
    ]


def recent_errors(session: Session, limit: int = 15) -> list[Event]:
    return list(
        session.scalars(
            select(Event)
            .where(Event.action.in_(ERROR_ACTIONS))
            .order_by(Event.id.desc())
            .limit(limit)
        )
    )


def link_for(event: Event) -> str:
    return {
        "publish_job": "/publicacoes",
        "account": "/contas",
        "render": "/fila?estado=needs_fix",
        "item": f"/aprovacao/{event.entity_id}",
    }.get(event.entity, "/")
