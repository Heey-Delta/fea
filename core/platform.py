"""Plataforma: ambiente isolado de cada operação na VPS (Tasks 32 a 35, `docs/plataforma.md`).

O painel só grava o **estado desejado** (ligado ou parado, limites, versão e pedidos). Quem
executa é o agente da VPS (`agent/`), que lê esse estado, aplica com Docker Compose e devolve
o **estado real**. Nada aqui fala com o Docker: o painel nunca alcança a VPS.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import AppSetting, Event, InfraServer, Operation, OperationRuntime
from core.operations import OperationError

CPU_MIN, CPU_MAX = 0.25, 16.0
MEMORY_MIN, MEMORY_MAX = 256, 32768
SERVER_ONLINE_FOR = timedelta(seconds=90)
MODE_KEY = "workers_mode"  # "plataforma" quando um agente está ativo
STATE_LABEL = {
    "absent": "Não criado",
    "starting": "Subindo",
    "running": "No ar",
    "degraded": "Com falha",
    "stopped": "Parado",
    "error": "Erro",
}


def runtime(session: Session, operation_id: int) -> OperationRuntime:
    """O ambiente da operação; cria o registro (parado) na primeira vez."""
    row = session.get(OperationRuntime, operation_id)
    if row is None:
        row = OperationRuntime(
            operation_id=operation_id,
            desired_state="stopped",
            cpu_limit=1.0,
            memory_mb=1024,
            version="",
            actual_state="absent",
        )
        session.add(row)
        session.flush()
    return row


def _event(session: Session, op_id: int, action: str, detail: dict | None = None) -> None:
    session.add(
        Event(entity="runtime", entity_id=op_id, operation_id=op_id, action=action, detail=detail)
    )


def set_desired(session: Session, op: Operation, state: str) -> OperationRuntime:
    if state not in ("running", "stopped"):
        raise OperationError("Estado inválido.")
    if state == "running" and op.status != "active":
        raise OperationError("Só operações ativas podem ter o ambiente ligado. Ative no editor.")
    row = runtime(session, op.id)
    row.desired_state = state
    _event(session, op.id, "start" if state == "running" else "stop")
    session.flush()
    return row


def set_limits(session: Session, op: Operation, cpu: float, memory_mb: int) -> OperationRuntime:
    if not (CPU_MIN <= cpu <= CPU_MAX):
        raise OperationError(f"CPU entre {CPU_MIN} e {CPU_MAX:g} núcleos.")
    if not (MEMORY_MIN <= memory_mb <= MEMORY_MAX):
        raise OperationError(f"Memória entre {MEMORY_MIN} MB e {MEMORY_MAX} MB.")
    row = runtime(session, op.id)
    row.cpu_limit, row.memory_mb = round(cpu, 2), int(memory_mb)
    _event(session, op.id, "limits", {"cpu": row.cpu_limit, "memory_mb": row.memory_mb})
    session.flush()
    return row


def available_versions(session: Session) -> list[str]:
    """Versões (imagens) disponíveis nos servidores, da mais nova para a mais antiga."""
    seen: list[str] = []
    for server in session.scalars(select(InfraServer).order_by(InfraServer.id)):
        for v in server.versions or []:
            if v not in seen:
                seen.append(v)
    return seen


def set_version(session: Session, op: Operation, version: str) -> OperationRuntime:
    """Fixa a versão da operação ("" = acompanhar a mais nova). Também serve de rollback."""
    version = (version or "").strip()
    if version and version not in available_versions(session):
        raise OperationError("Versão não disponível no servidor.")
    row = runtime(session, op.id)
    previous = row.version
    row.version = version
    _event(session, op.id, "version", {"from": previous, "to": version or "mais nova"})
    session.flush()
    return row


def request_restart(session: Session, op: Operation) -> OperationRuntime:
    row = runtime(session, op.id)
    row.restart_requested_at = datetime.now(UTC)
    _event(session, op.id, "restart")
    session.flush()
    return row


def request_backup(session: Session, op: Operation) -> OperationRuntime:
    row = runtime(session, op.id)
    row.backup_requested_at = datetime.now(UTC)
    _event(session, op.id, "backup")
    session.flush()
    return row


def request_restore(session: Session, op: Operation, name: str) -> OperationRuntime:
    row = runtime(session, op.id)
    names = {b.get("name") for b in row.backups or []}
    if name not in names:
        raise OperationError("Backup não encontrado.")
    row.restore_request = {"name": name, "at": datetime.now(UTC).isoformat()}
    _event(session, op.id, "restore", {"name": name})
    session.flush()
    return row


@dataclass
class ServerView:
    server: InfraServer
    online: bool

    @property
    def mem_pct(self) -> int:
        s = self.server
        return round(100 * (s.mem_used_mb or 0) / s.mem_total_mb) if s.mem_total_mb else 0

    @property
    def disk_pct(self) -> int:
        s = self.server
        if not s.disk_total_gb:
            return 0
        return round(100 * (1 - (s.disk_free_gb or 0) / s.disk_total_gb))


def servers(session: Session, now: datetime | None = None) -> list[ServerView]:
    now = now or datetime.now(UTC)
    return [
        ServerView(s, bool(s.last_seen and now - s.last_seen < SERVER_ONLINE_FOR))
        for s in session.scalars(select(InfraServer).order_by(InfraServer.id))
    ]


def platform_active(session: Session, now: datetime | None = None) -> bool:
    """Há agente no ar: os workers soltos (celular) devem parar (Task 35.2)."""
    row = session.get(AppSetting, MODE_KEY)
    return bool(row and row.value == "plataforma") and any(v.online for v in servers(session, now))
