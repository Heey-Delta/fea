"""Processos da VPS.

python -m worker check                   # verifica FFmpeg, ffprobe e banco
python -m worker buscador|editor|postador|limpeza   # loops da fila (Task 3)
"""

import sys

from core.config import get_settings
from core.logging import configure_logging
from worker.health import run_checks

ROLES = ("buscador", "editor", "postador", "limpeza")


def main(argv: list[str]) -> int:
    configure_logging(get_settings().log_level)
    command = argv[1] if len(argv) > 1 else ""
    if command == "check":
        return 0 if run_checks() else 1
    if command in ROLES:
        print(f"O worker '{command}' é implementado na Task 3.", file=sys.stderr)
        return 2
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
