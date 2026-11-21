"""Distribuição e agenda (Tasks 21, 22 e 23).

Um lote (`batches`) junta vídeos aprovados e contas. Cada par vídeo × conta vira um envio
(`publish_jobs`) com horário planejado:

- rodízio (padrão): cada vídeo vai para um canal só, alternando os canais;
- todos: o mesmo vídeo em cada conta.

Horário n de uma conta = T0 + (n − 1) × intervalo, dentro da janela diária e do limite diário
da conta, no fuso dela. O que passar de 7 dias fica `pending_capacity`, reavaliado depois.
Reenviar o mesmo pedido (mesma `request_key`) devolve o lote existente.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.models import Account, Batch, Event, Item, Operation, PublishJob, Render
from core.operations import OperationError, current_config, linked_account_ids

HORIZON = timedelta(days=7)
# Envios que ocupam vaga no limite diário e na agenda da conta.
OCCUPYING = (
    "planned",
    "uploading",
    "scheduled_platform",
    "processing",
    "retry_wait",
    "uncertain",
    "published",
)
OPEN = (*OCCUPYING, "pending_capacity")
# Envios encerrados sem publicar: podem voltar para a agenda no mesmo registro.
REUSABLE = ("failed", "cancelled", "skipped")
DEFAULT_WINDOW = {"start": "08:00", "end": "23:00"}


def publish_config(config: dict) -> dict:
    node = next((n for n in config.get("nodes", []) if n.get("type") == "publish"), None)
    return (node or {}).get("config") or {}


def parse_hhmm(value: str) -> time:
    hour, minute = (value or "00:00").split(":")
    return time(int(hour), int(minute))


@dataclass
class Candidate:
    item_id: int
    render_id: int
    sha256: str | None
    allowed: set[int] | None  # contas aprovadas para o vídeo (None = todas do lote)


@dataclass
class Planned:
    item_id: int
    render_id: int
    account_id: int
    planned_at: datetime | None
    status: str
    reason: str | None = None


class Agenda:
    """Encaixa horários na janela e no limite diário de cada conta (Task 22)."""

    def __init__(
        self,
        accounts: list[Account],
        window: dict,
        interval: timedelta,
        now: datetime,
        counts: dict[tuple[int, date], int],
        next_free: dict[int, datetime],
    ):
        self.accounts = {a.id: a for a in accounts}
        self.start = parse_hhmm(window.get("start", DEFAULT_WINDOW["start"]))
        self.end = parse_hhmm(window.get("end", DEFAULT_WINDOW["end"]))
        self.interval = interval
        self.now = now
        self.counts = counts
        self.next_free = next_free

    def fit(self, account_id: int, at: datetime) -> datetime | None:
        """Primeiro horário >= `at` que cabe na janela e no limite. None = além de 7 dias."""
        account = self.accounts[account_id]
        tz = ZoneInfo(account.timezone or "America/Sao_Paulo")
        t = max(at, self.next_free.get(account_id, at)).astimezone(tz)
        limit = self.now + HORIZON
        while t <= limit:
            day_start = datetime.combine(t.date(), self.start, tz)
            day_end = datetime.combine(t.date(), self.end, tz)
            if t < day_start:
                t = day_start
            if t > day_end or self.counts.get((account_id, t.date()), 0) >= account.daily_limit:
                t = datetime.combine(t.date() + timedelta(days=1), self.start, tz)
                continue
            return t.astimezone(UTC)
        return None

    def take(self, account_id: int, at: datetime) -> None:
        tz = ZoneInfo(self.accounts[account_id].timezone or "America/Sao_Paulo")
        key = (account_id, at.astimezone(tz).date())
        self.counts[key] = self.counts.get(key, 0) + 1
        self.next_free[account_id] = at + self.interval


def first_slot(
    now: datetime, start_at: datetime | None, first_immediate: bool, interval: timedelta
) -> datetime:
    if start_at:
        return max(start_at, now)
    return now if first_immediate else now + interval


def plan(
    candidates: list[Candidate],
    agenda: Agenda,
    account_ids: list[int],
    mode: str,
    t0: datetime,
    published: set[tuple[int, str]],
) -> list[Planned]:
    """Distribui os vídeos (Tasks 21.3, 21.4, 21.5 e 23.3). Função pura sobre a agenda."""
    out: list[Planned] = []
    if mode == "all":
        for account_id in account_ids:
            cursor = t0
            for c in candidates:
                if c.allowed is not None and account_id not in c.allowed:
                    continue
                if c.sha256 and (account_id, c.sha256) in published:
                    out.append(
                        Planned(
                            c.item_id,
                            c.render_id,
                            account_id,
                            None,
                            "skipped",
                            "Mesmo vídeo já publicado nesta conta.",
                        )
                    )
                    continue
                at = agenda.fit(account_id, cursor)
                if at is None:
                    out.append(
                        Planned(
                            c.item_id,
                            c.render_id,
                            account_id,
                            None,
                            "pending_capacity",
                            "Sem vaga nos próximos 7 dias.",
                        )
                    )
                    continue
                agenda.take(account_id, at)
                out.append(Planned(c.item_id, c.render_id, account_id, at, "planned"))
                cursor = at + agenda.interval
        return out

    # Rodízio: um canal por vídeo; quem está no limite (ou já tem o vídeo) é pulado.
    pointer, cursor = 0, t0
    for c in candidates:
        order = account_ids[pointer:] + account_ids[:pointer]
        options = [
            a
            for a in order
            if (c.allowed is None or a in c.allowed)
            and not (c.sha256 and (a, c.sha256) in published)
        ]
        if not options:
            fallback = next((a for a in order if c.allowed is None or a in c.allowed), None)
            if fallback is not None:
                out.append(
                    Planned(
                        c.item_id,
                        c.render_id,
                        fallback,
                        None,
                        "skipped",
                        "Mesmo vídeo já publicado nas contas possíveis.",
                    )
                )
            continue
        best, best_at = options[0], None
        for account_id in options:
            at = agenda.fit(account_id, cursor)
            if at is not None and (best_at is None or at < best_at):
                best, best_at = account_id, at
        if best_at is None:
            out.append(
                Planned(
                    c.item_id,
                    c.render_id,
                    best,
                    None,
                    "pending_capacity",
                    "Sem vaga nos próximos 7 dias em nenhuma conta.",
                )
            )
            continue
        agenda.take(best, best_at)
        out.append(Planned(c.item_id, c.render_id, best, best_at, "planned"))
        cursor = best_at + agenda.interval
        pointer = (account_ids.index(best) + 1) % len(account_ids)
    return out


def load_agenda(
    session: Session, accounts: list[Account], window: dict, interval: timedelta, now: datetime
) -> Agenda:
    """Agenda com o que já está marcado nas contas (de qualquer operação)."""
    counts: dict[tuple[int, date], int] = {}
    next_free: dict[int, datetime] = {}
    by_id = {a.id: a for a in accounts}
    rows = session.execute(
        select(PublishJob.account_id, PublishJob.planned_at, PublishJob.published_at).where(
            PublishJob.account_id.in_(list(by_id)),
            PublishJob.status.in_(OCCUPYING),
            func.coalesce(PublishJob.published_at, PublishJob.planned_at)
            >= now - timedelta(days=1),
        )
    )
    for account_id, planned_at, published_at in rows:
        at = published_at or planned_at
        if at is None:
            continue
        tz = ZoneInfo(by_id[account_id].timezone or "America/Sao_Paulo")
        key = (account_id, at.astimezone(tz).date())
        counts[key] = counts.get(key, 0) + 1
        next_free[account_id] = max(next_free.get(account_id, at), at + interval)
    return Agenda(accounts, window, interval, now, counts, next_free)


def published_hashes(session: Session, account_ids: list[int]) -> set[tuple[int, str]]:
    rows = session.execute(
        select(PublishJob.account_id, Item.sha256)
        .join(Render, Render.id == PublishJob.render_id)
        .join(Item, Item.id == Render.item_id)
        .where(
            PublishJob.account_id.in_(account_ids),
            PublishJob.status.in_(OCCUPYING),
            Item.sha256.is_not(None),
        )
    )
    return {(a, s) for a, s in rows}


def schedulable_items(session: Session, operation_id: int, item_ids: list[int] | None = None):
    """Aprovados, com render aprovado, que ainda não têm envio aberto."""
    taken = (
        select(Render.item_id)
        .join(PublishJob, PublishJob.render_id == Render.id)
        .where(PublishJob.status.in_(OPEN))
    )
    stmt = (
        select(Item)
        .where(
            Item.operation_id == operation_id,
            Item.status == "approved",
            Item.approved_render_id.is_not(None),
            Item.id.not_in(taken),
        )
        .order_by(Item.approved_at, Item.id)
    )
    if item_ids is not None:
        stmt = stmt.where(Item.id.in_(item_ids))
    return list(session.scalars(stmt))


def request_key_for(
    operation_id: int, item_ids: list[int], account_ids: list[int], mode: str, nonce: str = ""
) -> str:
    raw = f"{operation_id}|{sorted(item_ids)}|{sorted(account_ids)}|{mode}|{nonce}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def create_batch(
    session: Session,
    op: Operation,
    *,
    item_ids: list[int] | None,
    account_ids: list[int],
    mode: str = "rotation",
    interval_min: int = 30,
    first_immediate: bool = False,
    start_at: datetime | None = None,
    request_key: str,
    automatic: bool = False,
    window: dict | None = None,
    now: datetime | None = None,
) -> tuple[Batch, bool]:
    """Cria o lote e os envios. Devolve (lote, criado agora?)."""
    existing = session.scalar(select(Batch).where(Batch.request_key == request_key))
    if existing is not None:
        return existing, False
    if mode not in ("rotation", "all"):
        raise OperationError("Modo de distribuição inválido.")
    if interval_min < 0:
        raise OperationError("Intervalo não pode ser negativo.")
    now = now or datetime.now(UTC)
    accounts = list(
        session.scalars(select(Account).where(Account.id.in_(account_ids)).order_by(Account.id))
    )
    if mode == "rotation":
        accounts = [a for a in accounts if a.status == "connected"]
    else:
        accounts = [a for a in accounts if a.status != "revoked"]
    if not accounts:
        raise OperationError("Nenhuma conta disponível (conectada) para este lote.")
    items = schedulable_items(session, op.id, item_ids)
    if not items:
        raise OperationError("Nenhum vídeo aprovado disponível para agendar.")

    config = current_config(session, op).config
    window = window or publish_config(config).get("window") or DEFAULT_WINDOW
    interval = timedelta(minutes=interval_min)
    ids = [a.id for a in accounts]
    agenda = load_agenda(session, accounts, window, interval, now)
    candidates = [
        Candidate(
            i.id,
            i.approved_render_id,
            i.sha256,
            set(i.approved_account_ids) if i.approved_account_ids else None,
        )
        for i in items
    ]
    t0 = first_slot(now, start_at, first_immediate, interval)
    planned = plan(candidates, agenda, ids, mode, t0, published_hashes(session, ids))

    # Um envio por vídeo e conta (restrição do banco). Se o par já teve um envio que falhou,
    # foi cancelado ou pulado, o mesmo registro volta para a agenda em vez de criar outro.
    previous = {
        (j.render_id, j.account_id): j
        for j in session.scalars(
            select(PublishJob).where(PublishJob.render_id.in_({p.render_id for p in planned}))
        )
    }
    if planned and all(
        previous.get((p.render_id, p.account_id)) is not None
        and previous[(p.render_id, p.account_id)].status not in REUSABLE
        for p in planned
    ):
        raise OperationError("Esses vídeos já têm envio para essas contas: veja em Publicações.")

    batch = Batch(
        operation_id=op.id,
        request_key=request_key,
        mode=mode,
        automatic=automatic,
        interval_min=interval_min,
        first_immediate=first_immediate,
        start_at=start_at,
    )
    try:
        with session.begin_nested():
            session.add(batch)
            session.flush()
            for p in planned:
                old = previous.get((p.render_id, p.account_id))
                if old is None:
                    session.add(
                        PublishJob(
                            batch_id=batch.id,
                            render_id=p.render_id,
                            account_id=p.account_id,
                            planned_at=p.planned_at,
                            status=p.status,
                            status_reason=p.reason,
                        )
                    )
                elif old.status in REUSABLE:
                    old.batch_id = batch.id
                    old.planned_at = p.planned_at
                    old.status = p.status
                    old.status_reason = p.reason
                    old.attempts = 0
                    old.external_id = old.url = old.published_at = None
            session.flush()
    except IntegrityError:
        # Dois pedidos ao mesmo tempo (ex.: toque duplo em "Criar envios").
        raise OperationError(
            "Esse envio acabou de ser criado por outro pedido: veja em Publicações."
        ) from None
    session.add(
        Event(
            entity="batch",
            entity_id=batch.id,
            operation_id=op.id,
            action="created",
            detail={
                "mode": mode,
                "videos": len(candidates),
                "jobs": len(planned),
                "pending": sum(p.status == "pending_capacity" for p in planned),
                "skipped": sum(p.status == "skipped" for p in planned),
                "automatic": automatic,
            },
        )
    )
    session.flush()
    return batch, True


def preview(
    session: Session,
    op: Operation,
    *,
    item_ids: list[int] | None,
    account_ids: list[int],
    mode: str,
    interval_min: int,
    first_immediate: bool,
    start_at: datetime | None,
    now: datetime | None = None,
) -> list[Planned]:
    """Prévia da agenda (21.1) sem gravar nada."""
    now = now or datetime.now(UTC)
    accounts = list(
        session.scalars(select(Account).where(Account.id.in_(account_ids)).order_by(Account.id))
    )
    accounts = [a for a in accounts if a.status == "connected" or mode == "all"]
    if not accounts:
        return []
    window = publish_config(current_config(session, op).config).get("window") or DEFAULT_WINDOW
    interval = timedelta(minutes=interval_min)
    ids = [a.id for a in accounts]
    agenda = load_agenda(session, accounts, window, interval, now)
    items = schedulable_items(session, op.id, item_ids)
    candidates = [
        Candidate(
            i.id,
            i.approved_render_id,
            i.sha256,
            set(i.approved_account_ids) if i.approved_account_ids else None,
        )
        for i in items
    ]
    return plan(
        candidates,
        agenda,
        ids,
        mode,
        first_slot(now, start_at, first_immediate, interval),
        published_hashes(session, ids),
    )


def window_minutes(window: dict) -> int:
    start, end = parse_hhmm(window.get("start", "08:00")), parse_hhmm(window.get("end", "23:00"))
    return max(1, (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute))


def auto_distribute(session: Session, now: datetime | None = None) -> list[int]:
    """Distribuição automática (21.2): operações ativas com o bloco Postagem em automático.

    No rodízio, o espaçamento é a janela dividida pelos vídeos do dia (22.2): a soma dos
    limites diários das contas da operação.
    """
    now = now or datetime.now(UTC)
    created = []
    for op in session.scalars(select(Operation).where(Operation.status == "active")):
        config = current_config(session, op).config
        publish = publish_config(config)
        approval = next(
            (n.get("config") or {} for n in config.get("nodes", []) if n.get("type") == "approval"),
            {},
        )
        if not (publish.get("automatic") or approval.get("auto_approve")):
            continue
        account_ids = linked_account_ids(config)
        accounts = list(session.scalars(select(Account).where(Account.id.in_(account_ids))))
        items = schedulable_items(session, op.id)
        if not items or not any(a.status == "connected" for a in accounts):
            continue
        mode = publish.get("mode", "rotation")
        window = publish.get("window") or DEFAULT_WINDOW
        per_day = sum(a.daily_limit for a in accounts if a.status == "connected") or 1
        interval = int(publish.get("interval_min") or 0)
        if mode == "rotation":
            interval = max(interval, window_minutes(window) // per_day)
        ids = [i.id for i in items]
        key = "auto:" + request_key_for(op.id, ids, account_ids, mode)
        try:
            batch, new = create_batch(
                session,
                op,
                item_ids=ids,
                account_ids=account_ids,
                mode=mode,
                interval_min=interval,
                first_immediate=bool(publish.get("first_immediate")),
                request_key=key,
                automatic=True,
                window=window,
                now=now,
            )
        except OperationError:
            continue
        if new:
            created.append(batch.id)
    return created


def reevaluate_pending(session: Session, now: datetime | None = None) -> int:
    """Envios `pending_capacity` voltam para `planned` quando abre vaga (22.4)."""
    now = now or datetime.now(UTC)
    jobs = list(
        session.scalars(
            select(PublishJob)
            .where(PublishJob.status == "pending_capacity")
            .order_by(PublishJob.id)
        )
    )
    moved = 0
    for job in jobs:
        account = session.get(Account, job.account_id)
        batch = session.get(Batch, job.batch_id)
        if account is None or account.status != "connected":
            continue
        op = session.get(Operation, batch.operation_id)
        window = publish_config(current_config(session, op).config).get("window") or DEFAULT_WINDOW
        interval = timedelta(minutes=batch.interval_min)
        agenda = load_agenda(session, [account], window, interval, now)
        at = agenda.fit(account.id, now)
        if at is not None:
            job.planned_at, job.status, job.status_reason = at, "planned", None
            session.flush()
            moved += 1
    return moved


def cancel_job(session: Session, job: PublishJob) -> None:
    if job.status not in ("planned", "pending_capacity", "retry_wait", "failed", "uncertain"):
        raise OperationError("Este envio não pode ser cancelado agora.")
    job.status, job.status_reason = "cancelled", "cancelado na interface"
    session.add(Event(entity="publish_job", entity_id=job.id, action="cancelled"))


def published(
    session: Session, job: PublishJob, external_id: str, url: str, status: str, now: datetime
) -> str:
    job.status, job.status_reason = status, None
    job.external_id, job.url, job.published_at = external_id, url, now
    render = session.get(Render, job.render_id)
    item = session.get(Item, render.item_id)
    op = session.get(Operation, item.operation_id)
    minutes = int(
        (current_config(session, op).config.get("retention") or {}).get("delete_after_minutes", 30)
    )
    # X minutos após a última publicação do vídeo (24.5).
    deadline = now + timedelta(minutes=minutes)
    item.delete_after = max(item.delete_after or deadline, deadline)
    session.add(
        Event(
            entity="publish_job",
            entity_id=job.id,
            operation_id=op.id,
            action="published",
            detail={"url": url, "external_id": external_id},
        )
    )
    session.commit()
    return job.status


def resolve_uncertain(session: Session, job: PublishJob, decision: str, url: str = "") -> None:
    """Decisão manual de um envio incerto (24.3): publicado, tentar de novo ou cancelar."""
    if job.status not in ("uncertain", "failed"):
        raise OperationError("Só envios incertos ou com falha aceitam esta decisão.")
    now = datetime.now(UTC)
    if decision == "published":
        if not url.startswith("https://"):
            raise OperationError("Informe o link do vídeo publicado.")
        published(session, job, url.rstrip("/").rsplit("/", 1)[-1], url, "published", now)
    elif decision == "retry":
        job.status, job.planned_at, job.status_reason = "retry_wait", now, "nova tentativa manual"
        session.add(Event(entity="publish_job", entity_id=job.id, action="manual_retry"))
    elif decision == "cancel":
        job.status, job.status_reason = "cancelled", "cancelado na interface"
        session.add(Event(entity="publish_job", entity_id=job.id, action="cancelled"))
    else:
        raise OperationError("Decisão desconhecida.")
