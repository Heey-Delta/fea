"""Registro dos handlers de cada fila e das rotinas periódicas de cada papel.

As tasks seguintes registram aqui o que cada fila faz:
- collect   → Buscador (Tasks 5 a 7)
- render    → Editor (Tasks 10 a 17)
- publish   → Postador (Tasks 20 a 24)
- scheduler → Postador: promove envios planejados (Task 22)
- cleanup   → Limpeza: apaga arquivos X minutos após publicar (Task 24.5)
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from core import queue
from worker.runner import Handler, Periodic

ROLE_TYPES: dict[str, tuple[str, ...]] = {
    "buscador": ("collect",),
    "editor": ("render",),
    "postador": ("publish", "scheduler"),
    "limpeza": ("cleanup",),
}

ROLE_CONCURRENCY = {"buscador": 2, "editor": 1, "postador": 2, "limpeza": 1}

HANDLERS: dict[str, Handler] = {}


def register(job_type: str):
    """Decorador usado pelas tasks seguintes: @register("collect")."""

    def decorator(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn

    return decorator


def enqueue_scheduler_tick(session: Session) -> None:
    """Uma tarefa `scheduler` por minuto; a chave por minuto evita duplicar entre réplicas."""
    minute = datetime.now(UTC).strftime("%Y%m%d%H%M")
    queue.enqueue(session, "scheduler", f"scheduler:{minute}", max_attempts=1)


def automation(session: Session) -> None:
    """Play diário e reposição de estoque (Tasks 6.8 e 6.9)."""
    from core.automation import automation_tick

    automation_tick(session)


def enqueue_cleanup_tick(session: Session) -> None:
    """Uma varredura da Limpeza por minuto (Task 24.5)."""
    minute = datetime.now(UTC).strftime("%Y%m%d%H%M")
    queue.enqueue(session, "cleanup", f"cleanup:{minute}", max_attempts=1)


ROLE_PERIODIC: dict[str, dict[str, tuple[float, Periodic]]] = {
    "buscador": {"automation": (60.0, automation)},
    "postador": {"scheduler_tick": (60.0, enqueue_scheduler_tick)},
    "limpeza": {"cleanup_tick": (60.0, enqueue_cleanup_tick)},
}


def load_handlers() -> None:
    """Importa os módulos que registram handlers (cada um usa @register)."""
    import worker.collect  # noqa: F401
    import worker.publish  # noqa: F401
    import worker.render  # noqa: F401


def handlers_for(role: str) -> dict[str, Handler]:
    load_handlers()
    return {t: HANDLERS[t] for t in ROLE_TYPES[role] if t in HANDLERS}
