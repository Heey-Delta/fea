"""Comandos do Docker usados pelo agente (Docker Controller, Task 33).

Só usa o socket local (`/var/run/docker.sock`): nada aqui abre porta para a internet.
Os comandos recebem listas de argumentos (nunca texto montado em shell).
"""

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

IMAGE = "fea-worker"


class DockerError(RuntimeError):
    pass


def _json_rows(text: str) -> list[dict]:
    """`--format json` devolve uma lista JSON ou uma linha JSON por objeto, conforme a versão."""
    text = text.strip()
    if not text:
        return []
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _mb(value: str) -> float:
    """'512.3MiB' / '1.2GiB' / '900kB' → MB."""
    value = value.strip()
    units = {"KIB": 1 / 1024, "KB": 1 / 1000, "MIB": 1, "MB": 1, "GIB": 1024, "GB": 1000, "B": 0}
    for unit, factor in sorted(units.items(), key=lambda kv: -len(kv[0])):
        if value.upper().endswith(unit):
            try:
                return float(value[: -len(unit)]) * factor
            except ValueError:
                return 0.0
    return 0.0


class Docker:
    def __init__(self, run: Callable[..., subprocess.CompletedProcess] = subprocess.run):
        self._run = run

    def _cmd(self, args: list[str], timeout: int = 600, check: bool = True) -> str:
        result = self._run(["docker", *args], capture_output=True, text=True, timeout=timeout)
        if check and result.returncode != 0:
            raise DockerError(
                f"docker {' '.join(args[:3])}…: {(result.stderr or '').strip()[-400:]}"
            )
        return result.stdout or ""

    def _compose(self, project: str, file: Path | None, *args: str, **kw) -> str:
        base = ["compose", "-p", project]
        if file is not None:
            base += ["-f", str(file)]
        return self._cmd([*base, *args], **kw)

    def up(self, project: str, file: Path) -> None:
        self._compose(project, file, "up", "-d", "--remove-orphans")

    def stop(self, project: str) -> None:
        self._compose(project, None, "stop")

    def down(self, project: str) -> None:
        """Remove os containers e a rede do projeto. Os dados da operação (pastas) ficam."""
        self._compose(project, None, "down", "--remove-orphans")

    def restart(self, project: str, file: Path) -> None:
        self._compose(project, file, "restart")

    def ps(self, project: str) -> list[dict]:
        rows = _json_rows(self._compose(project, None, "ps", "-a", "--format", "json", check=False))
        return [
            {
                "service": r.get("Service", ""),
                "name": r.get("Name", ""),
                "state": r.get("State", ""),
                "health": r.get("Health", ""),
                "status": r.get("Status", ""),
            }
            for r in rows
        ]

    def projects(self) -> list[str]:
        rows = _json_rows(self._cmd(["compose", "ls", "-a", "--format", "json"], check=False))
        return [r.get("Name", "") for r in rows]

    def stats(self) -> dict[str, dict]:
        rows = _json_rows(
            self._cmd(["stats", "--no-stream", "--format", "{{json .}}"], timeout=60, check=False)
        )
        out = {}
        for r in rows:
            try:
                cpu = float(str(r.get("CPUPerc", "0")).rstrip("%") or 0)
            except ValueError:
                cpu = 0.0
            used = str(r.get("MemUsage", "0B / 0B")).split("/")[0]
            out[r.get("Name", "")] = {"cpu": round(cpu, 1), "mem_mb": round(_mb(used), 1)}
        return out

    def logs(self, project: str, service: str, tail: int = 30) -> list[str]:
        text = self._compose(
            project,
            None,
            "logs",
            "--no-color",
            "--no-log-prefix",
            "--tail",
            str(tail),
            service,
            check=False,
            timeout=60,
        )
        return text.splitlines()[-tail:]

    def images(self) -> list[str]:
        """Tags de `fea-worker`, da mais nova para a mais antiga (sem `latest`)."""
        rows = _json_rows(
            self._cmd(["images", IMAGE, "--format", "{{json .}}"], check=False, timeout=60)
        )
        tagged = [
            (r.get("CreatedAt", ""), r.get("Tag", ""))
            for r in rows
            if r.get("Tag") not in (None, "", "<none>", "latest")
        ]
        seen, out = set(), []
        for _, tag in sorted(tagged, reverse=True):
            if tag not in seen:
                seen.add(tag)
                out.append(tag)
        return out
