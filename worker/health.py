"""Verificações do ambiente do worker (Task 1.9)."""

import logging
import shutil
import subprocess

from sqlalchemy import text

log = logging.getLogger("worker.health")


def tool_version(binary: str) -> str | None:
    """Primeira linha de `<binary> -version`, ou None se não estiver instalado."""
    path = shutil.which(binary)
    if not path:
        return None
    result = subprocess.run(
        [path, "-hide_banner", "-version"], capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        return None
    return result.stdout.splitlines()[0] if result.stdout else None


def database_ok() -> bool:
    from core.db import get_engine

    try:
        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - qualquer falha de conexão conta como indisponível
        log.error("banco indisponível", extra={"error": str(exc)})
        return False


def run_checks(check_database: bool = True) -> bool:
    ok = True
    for binary in ("ffmpeg", "ffprobe"):
        version = tool_version(binary)
        if version:
            log.info(f"{binary} ok", extra={"version": version})
        else:
            log.error(f"{binary} não encontrado")
            ok = False
    if check_database and not database_ok():
        ok = False
    return ok
