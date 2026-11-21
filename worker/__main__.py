"""Processos da VPS.

python -m worker check                              # verifica FFmpeg, ffprobe e banco
python -m worker alive                              # healthcheck: o worker deu sinal de vida?
python -m worker painel                             # painel dos workers no terminal
python -m worker buscador|editor|postador|limpeza   # roda o worker do papel
"""

import os
import signal
import sys

from core.config import get_settings
from core.db import get_sessionmaker
from core.logging import configure_logging
from worker.handlers import ROLE_CONCURRENCY, ROLE_PERIODIC, ROLE_TYPES, handlers_for
from worker.health import run_checks

ROLES = tuple(ROLE_TYPES)


def worker_scope() -> int | str | None:
    """OPERATION_ID=<n> → só a operação n; FEA_SCOPE=nucleo → só tarefas sem operação."""
    op = os.environ.get("OPERATION_ID", "").strip()
    if op:
        if not op.isdigit():
            raise SystemExit(f"OPERATION_ID inválido: {op!r}")
        return int(op)
    return "nucleo" if os.environ.get("FEA_SCOPE", "").strip() == "nucleo" else None


def main(argv: list[str]) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    command = argv[1] if len(argv) > 1 else ""
    if command == "painel":
        from worker import painel

        return painel.main(argv[2:])
    if command == "check":
        return 0 if run_checks() else 1
    if command == "alive":
        from worker.runner import alive

        return 0 if alive() else 1
    if command not in ROLES:
        print(__doc__, file=sys.stderr)
        return 1

    handlers = handlers_for(command)
    if not handlers:
        print(
            f"O worker '{command}' ainda não tem handler para {', '.join(ROLE_TYPES[command])}.",
            file=sys.stderr,
        )
        return 2

    from worker.runner import Worker

    concurrency = int(os.environ.get("WORKER_CONCURRENCY", ROLE_CONCURRENCY[command]))
    scope = worker_scope()
    worker = Worker(
        command,
        handlers,
        get_sessionmaker(),
        concurrency=concurrency,
        listen_dsn=settings.database_url if settings.worker_listen else None,
        idle_max=settings.worker_idle_max_s,
        # Rotinas periódicas (agenda, automação, limpeza) só no núcleo ou na instalação única:
        # um ambiente de operação só trabalha nas tarefas da própria operação.
        periodic=None if isinstance(scope, int) else ROLE_PERIODIC.get(command),
        scope=scope,
    )
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: worker.stop.set())
    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
