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


def active_operations(session: Session, limit: int = 6) -> list[Operation]:
    return list(
        session.scalars(
            select(Operation)
            .where(Operation.status == "active")
            .order_by(Operation.updated_at.desc())
            .limit(limit)
        )
    )


def recent_publications(session: Session, limit: int = 8) -> list[tuple]:
    return list(
        session.execute(
            select(PublishJob, Account)
            .join(Account, Account.id == PublishJob.account_id)
            .where(PublishJob.status == "published")
            .order_by(PublishJob.published_at.desc())
            .limit(limit)
        ).all()
    )


# --- gráficos do dashboard ---------------------------------------------------------------

DASH_TZ = "America/Sao_Paulo"


def published_by_day(session: Session, days: int = 14, now: datetime | None = None) -> list[dict]:
    """Publicações por dia (fuso de São Paulo), do mais antigo para hoje, com os dias zerados."""
    from zoneinfo import ZoneInfo

    now = now or datetime.now(UTC)
    today = now.astimezone(ZoneInfo(DASH_TZ)).date()
    first = today - timedelta(days=days - 1)
    local_day = func.date(func.timezone(DASH_TZ, PublishJob.published_at))
    rows = dict(
        session.execute(
            select(local_day, func.count())
            .where(
                PublishJob.status == "published",
                PublishJob.published_at >= now - timedelta(days=days + 1),
            )
            .group_by(local_day)
        ).all()
    )
    out = [
        {"day": first + timedelta(days=i), "count": int(rows.get(first + timedelta(days=i), 0))}
        for i in range(days)
    ]
    # Rótulo só no pico (primeira ocorrência) e no dia de hoje: nunca um número em cada coluna.
    top = max((p["count"] for p in out), default=0)
    peak = next((i for i, p in enumerate(out) if top and p["count"] == top), None)
    for i, p in enumerate(out):
        p["peak"] = i == peak and i < len(out) - 1
    return out


# Ordem fixa dos estágios (a cor segue o estágio, nunca a posição no ranking).
PIPELINE = (
    ("busca", "Na busca", "/fila?etapa=pesca", ("discovered", "eligible")),
    ("edicao", "Editando", "/fila?estado=rendering", ("rendering",)),
    ("aprovacao", "Aprovação", "/aprovacao", ("awaiting_approval", "needs_fix")),
    ("estoque", "Estoque", "/fila?estado=approved", ("approved",)),
)


def pipeline(session: Session) -> list[dict]:
    counts = dict(session.execute(select(Item.status, func.count()).group_by(Item.status)).all())
    out = [
        {"key": key, "label": label, "href": href, "count": sum(counts.get(s, 0) for s in states)}
        for key, label, href, states in PIPELINE
    ]
    scheduled = session.scalar(
        select(func.count()).where(PublishJob.status.in_(("planned", "pending_capacity")))
    )
    out.append(
        {
            "key": "agenda",
            "label": "Agendados",
            "href": "/publicacoes?status=planned",
            "count": int(scheduled or 0),
        }
    )
    return out


def health(session: Session, now: datetime | None = None) -> dict:
    from core import workers

    now = now or datetime.now(UTC)
    day = now - timedelta(hours=24)
    try:
        with session.begin_nested():  # savepoint: não expira o que a tela já carregou
            roles = workers.status(session, now)
    except Exception:  # noqa: BLE001 - migração ainda não aplicada
        roles = []
    failures = session.scalar(
        select(func.count()).where(
            PublishJob.status.in_(("failed", "uncertain")), PublishJob.updated_at >= day
        )
    )
    return {
        "workers": roles,
        "online": sum(1 for w in roles if w["online"]),
        "failures_24h": int(failures or 0),
        "accounts_error": int(
            session.scalar(select(func.count()).where(Account.status == "error")) or 0
        ),
    }


def secondary(kpis_list: list[dict]) -> list[dict]:
    """O resto dos indicadores, para a lista compacta (os 3 principais viram gráfico)."""
    shown = {"Publicados (24 h)", "Na pesca", "Aguardando aprovação", "Estoque de editados"}
    return [k for k in kpis_list if k["label"] not in shown]
