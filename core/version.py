"""Versão do código em execução (commit do Git), para comparar o site com os workers.

Os workers do celular e da VPS rodam o código que foi baixado na instalação e não se
atualizam sozinhos. Comparar o commit deles com o do site mostra quando falta atualizar.
"""

import os
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@lru_cache
def code_version() -> str:
    """Os 7 primeiros caracteres do commit, ou "" quando não dá para saber."""
    for name in ("FEA_VERSION", "VERCEL_GIT_COMMIT_SHA"):
        value = os.environ.get(name, "").strip()
        if value:
            return value[:7]
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()[:7] if out.returncode == 0 else ""
