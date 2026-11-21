"""Estado ao vivo das operações: em que estágio cada uma está agora (Busca, Edição, Publicação).

Lê a fila de tarefas (`jobs`): o que está rodando ou esperando, por operação. As tarefas de
publicação não guardam a operação; ela vem do envio (`publish_jobs` → render → item).
Erro = tarefa que falhou de vez nas últimas horas, tarefa que vai tentar de novo depois de
falhar, ou fonte com erro.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Execution, Item, Job, PublishJob, Render, Source

STAGES = (
    ("busca", "Buscando", "collect"),
    ("edicao", "Editando", "render"),
    ("publicacao", "Publicando", "publish"),
)
ERROR_WINDOW = timedelta(hours=6)


@dataclass
class OperationLive:
    operation_id: int
    stages: dict[str, str] = field(default_factory=dict)  # estágio → "running" | "queued"
    error: str = ""
    execution_id: int | None = None

    @property
    def active(self) -> bool:
        return bool(self.stages) or self.execution_id is not None

    @property
    def running(self) -> list[str]:
        """Rótulos dos estágios em andamento, na ordem do fluxo."""
        return [label for key, label, _ in STAGES if self.stages.get(key) == "running"]

    @property
    def headline(self) -> str:
        if self.running:
            return " · ".join(self.running)
        if self.stages:
            return "Na fila"
        return "Em execução" if self.execution_id else ""


def _job_operation_ids(session: Session, jobs: list[Job]) -> dict[int, int]:
    """Operação de cada tarefa, inclusive das publicações (que não guardam a operação)."""
    out = {j.id: j.operation_id for j in jobs if j.operation_id}
    publish = {j.ref_id: j.id for j in jobs if j.type == "publish" and j.ref_id and j.id not in out}
    if publish:
        rows = session.execute(
            select(PublishJob.id, Item.operation_id)
            .join(Render, Render.id == PublishJob.render_id)
            .join(Item, Item.id == Render.item_id)
            .where(PublishJob.id.in_(publish))
        )
        for publish_id, operation_id in rows:
            out[publish[publish_id]] = operation_id
    return out


def operations_live(
    session: Session, operation_ids: list[int] | None = None, now: datetime | None = None
) -> dict[int, OperationLive]:
    now = now or datetime.now(UTC)
    stage_of = {job_type: key for key, _, job_type in STAGES}
    recent = now - ERROR_WINDOW
    jobs = list(
        session.scalars(
            select(Job).where(
                Job.type.in_(stage_of),
                (Job.status.in_(("queued", "running")))
                | ((Job.status == "failed") & (Job.updated_at >= recent)),
            )
        )
    )
    op_of = _job_operation_ids(session, jobs)
    live: dict[int, OperationLive] = {}

    def get(op_id: int) -> OperationLive:
        return live.setdefault(op_id, OperationLive(op_id))

    for job in sorted(jobs, key=lambda j: j.id):
        op_id = op_of.get(job.id)
        if op_id is None or (operation_ids is not None and op_id not in operation_ids):
            continue
        entry = get(op_id)
        stage = stage_of[job.type]
        if job.status == "running":
            entry.stages[stage] = "running"
        elif job.status == "queued":
            entry.stages.setdefault(stage, "queued")
            if job.last_error:  # falhou e vai tentar de novo
                entry.error = entry.error or f"Tentando de novo: {job.last_error[:160]}"
        else:
            entry.error = f"Falhou: {(job.last_error or 'erro sem detalhe')[:160]}"

    running_ex = select(Execution.id, Execution.operation_id).where(Execution.status == "running")
    for ex_id, op_id in session.execute(running_ex):
        if operation_ids is None or op_id in operation_ids:
            get(op_id).execution_id = ex_id

    bad_sources = select(Source.operation_id, Source.last_error).where(Source.status == "error")
    for op_id, message in session.execute(bad_sources):
        if operation_ids is None or op_id in operation_ids:
            entry = get(op_id)
            entry.error = entry.error or f"Fonte com erro: {(message or '')[:160]}"
    return live
