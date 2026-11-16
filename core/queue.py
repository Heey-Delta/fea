"""Fila de tarefas no Postgres (Task 3).

Cada fila é um tipo de tarefa na tabela `jobs`: collect (Buscador), render (Editor),
publish e scheduler (Postador), cleanup (Limpeza). Um worker pega a próxima tarefa com
FOR UPDATE SKIP LOCKED, marca como `running` e solta o lock antes de trabalhar, para não
segurar uma transação aberta durante um render longo. Se o worker morrer no meio,
`requeue_stale` devolve a tarefa para a fila.

Quem chama controla a transação (commit/rollback).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.logging import redact_text
from core.models import Execution, Job

PRIORITY_VALUE = {"low": 0, "normal": 1, "high": 2}
NOTIFY_CHANNEL = "fea_jobs"
MAX_BACKOFF_S = 3600


class RetryableError(Exception):
    """Falha de processo (rede, rate limit, timeout): a tarefa volta para a fila."""


class PermanentError(Exception):
    """Falha de conteúdo ou configuração: tentar de novo não resolve."""


@dataclass(frozen=True)
class Enqueued:
    id: int
    created: bool


def backoff_seconds(attempts: int) -> int:
    """30 s, 60 s, 120 s, … até 1 hora."""
    return min(30 * 2 ** max(attempts - 1, 0), MAX_BACKOFF_S)


def enqueue(
    session: Session,
    type: str,
    idempotency_key: str,
    *,
    ref_id: int | None = None,
    operation_id: int | None = None,
    execution_id: int | None = None,
    priority: str = "normal",
    run_at: datetime | None = None,
    max_attempts: int = 3,
) -> Enqueued:
    """Põe uma tarefa na fila. A mesma chave nunca cria duas tarefas (Task 3.5)."""
    values = {
        "type": type,
        "idempotency_key": idempotency_key,
        "ref_id": ref_id,
        "operation_id": operation_id,
        "execution_id": execution_id,
        "priority": PRIORITY_VALUE[priority],
        "max_attempts": max_attempts,
    }
    if run_at is not None:
        values["run_at"] = run_at
    stmt = (
        pg_insert(Job)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(Job.id)
    )
    job_id = session.execute(stmt).scalar()
    if job_id is None:
        existing = session.execute(select(Job.id).where(Job.idempotency_key == idempotency_key))
        return Enqueued(existing.scalar_one(), created=False)
    # O aviso só chega aos workers quando a transação for confirmada.
    session.execute(
        text("SELECT pg_notify(:channel, :type)"), {"channel": NOTIFY_CHANNEL, "type": type}
    )
    return Enqueued(job_id, created=True)


def claim(session: Session, types: list[str], worker_id: str) -> Job | None:
    """Pega a próxima tarefa: maior prioridade, depois a mais antiga (Task 3.2 e 3.9).

    Tarefas de execuções pausadas ficam na fila (Task 3.8).
    """
    paused = select(Execution.id).where(Execution.status == "paused")
    stmt = (
        select(Job)
        .where(
            Job.status == "queued",
            Job.type.in_(types),
            Job.run_at <= func.now(),
            or_(Job.execution_id.is_(None), Job.execution_id.not_in(paused)),
        )
        .order_by(Job.priority.desc(), Job.run_at, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = session.execute(stmt).scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    job.locked_by = worker_id
    job.locked_at = func.now()
    session.flush()
    session.refresh(job)
    return job


def complete(session: Session, job_id: int) -> None:
    session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(status="done", locked_by=None, locked_at=None, last_error=None)
    )


def fail(session: Session, job_id: int, error: str, *, retryable: bool) -> str:
    """Registra a falha. Devolve o novo estado: `queued` (vai tentar de novo) ou `failed`."""
    job = session.get(Job, job_id, with_for_update=True)
    job.last_error = redact_text(error)[:2000]
    job.locked_by = None
    job.locked_at = None
    if retryable and job.attempts < job.max_attempts:
        job.status = "queued"
        job.run_at = func.now() + timedelta(seconds=backoff_seconds(job.attempts))
    else:
        job.status = "failed"
    session.flush()
    return job.status


def requeue_stale(session: Session, older_than: timedelta) -> int:
    """Devolve à fila tarefas presas em `running` por um worker que morreu."""
    cutoff = func.now() - older_than
    stale = Job.status == "running", Job.locked_at < cutoff
    exhausted = session.execute(
        update(Job)
        .where(*stale, Job.attempts >= Job.max_attempts)
        .values(status="failed", locked_by=None, locked_at=None, last_error="worker parou no meio")
    ).rowcount
    requeued = session.execute(
        update(Job)
        .where(*stale)
        .values(status="queued", locked_by=None, locked_at=None, run_at=func.now())
    ).rowcount
    return requeued + exhausted


def cancel_execution_jobs(session: Session, execution_id: int) -> int:
    """Cancela as tarefas ainda na fila de uma execução. As que estão rodando terminam."""
    return session.execute(
        update(Job)
        .where(Job.execution_id == execution_id, Job.status == "queued")
        .values(status="cancelled")
    ).rowcount


def queue_counts(session: Session) -> dict[tuple[str, str], int]:
    """Quantidade de tarefas por (tipo, estado), para o dashboard e os testes."""
    rows = session.execute(
        select(Job.type, Job.status, func.count()).group_by(Job.type, Job.status)
    )
    return {(t, s): n for t, s, n in rows}
