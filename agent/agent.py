"""Agente da plataforma (Task 33): Operations Manager, Docker Controller, Resource Manager,
Health Monitor e Version Manager num processo só, na VPS.

A cada ciclo: lê o estado desejado no banco (`operation_runtimes`), aplica com Docker Compose
(um projeto por operação + o núcleo), executa os pedidos (reinício, backup, restauração) e
grava o estado real (containers, CPU, memória, logs recentes sem segredos, erro). Também
reporta o servidor (`infra_servers`) e marca a plataforma como ativa, o que faz os workers
soltos (celular) pararem sozinhos.

Modelo *pull*: o painel nunca fala com a VPS; o agente é quem procura o banco.
"""

import logging
import os
import shutil
import socket
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session, sessionmaker

from agent import compose as cp
from agent.docker import Docker, DockerError
from core import platform as pf
from core.logging import redact_text
from core.models import AppSetting, Event, InfraServer, Operation, OperationRuntime
from core.version import code_version

log = logging.getLogger("agent")
BOOTSTRAP_KEY = "platform_bootstrapped"
KEEP_BACKUPS = 10
LOG_TAIL = 30


def _setting(session: Session, name: str, value: str) -> None:
    row = session.get(AppSetting, name)
    if row is None:
        session.add(AppSetting(name=name, value=value))
    elif row.value != value:
        row.value = value


def _meminfo() -> tuple[int | None, int | None]:
    try:
        info = dict(
            (line.split(":")[0], int(line.split()[1]))
            for line in Path("/proc/meminfo").read_text().splitlines()
            if line.split()[1:2] and line.split()[1].isdigit()
        )
    except OSError:
        return None, None
    total, available = info.get("MemTotal"), info.get("MemAvailable")
    if not total:
        return None, None
    return total // 1024, (total - (available or 0)) // 1024


def state_of(containers: list[dict]) -> str:
    """Estado real a partir dos containers do projeto."""
    if not containers:
        return "absent"
    states = [c["state"] for c in containers]
    if all(s == "running" for s in states):
        if any(c.get("health") == "unhealthy" for c in containers):
            return "degraded"
        if any(c.get("health") == "starting" for c in containers):
            return "starting"
        return "running"
    if any(s in ("restarting", "dead") for s in states) or (
        any(s == "running" for s in states) and any(s == "exited" for s in states)
    ):
        return "degraded"
    if all(s in ("exited", "created") for s in states):
        return "stopped"
    return "starting"


class Agent:
    def __init__(
        self,
        factory: sessionmaker,
        base: Path,
        docker: Docker | None = None,
        server_name: str | None = None,
        clock=lambda: datetime.now(UTC),
    ):
        self.factory = factory
        self.base = Path(base)
        self.docker = docker or Docker()
        self.server_name = server_name or os.environ.get("FEA_SERVER_NAME") or socket.gethostname()
        self.clock = clock

    # --- ciclo ---------------------------------------------------------------------------

    def tick(self) -> None:
        now = self.clock()
        versions = self.docker.images()
        latest = versions[0] if versions else None
        with self.factory() as session:
            self._bootstrap(session)
            self._report_server(session, versions, now)
            session.commit()
            if latest:
                self._ensure_nucleo(latest)
            rows = session.execute(select(OperationRuntime, Operation).join(Operation)).all()
            wanted = set()
            for rt, op in rows:
                wanted.add(cp.project_name(op.id))
                try:
                    self._reconcile(session, rt, op, versions, latest, now)
                except DockerError as exc:
                    rt.actual_state, rt.error = "error", redact_text(str(exc))[:500]
                    log.warning(
                        "falha no ambiente", extra={"operation_id": op.id, "error": str(exc)}
                    )
                session.commit()
            for project in self.docker.projects():
                if project.startswith("fea-op-") and project not in wanted:
                    self.docker.down(project)  # operação apagada: containers saem, pastas ficam
                    log.info("ambiente removido", extra={"project": project})

    def run_forever(self, interval: float = 15.0, stop=None) -> None:
        log.info("agente iniciado", extra={"server": self.server_name, "base": str(self.base)})
        while stop is None or not stop.is_set():
            started = time.monotonic()
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - um ciclo ruim não derruba o agente
                log.exception("falha no ciclo do agente")
            wait = max(1.0, interval - (time.monotonic() - started))
            if stop is not None:
                stop.wait(wait)
            else:
                time.sleep(wait)

    # --- servidor e migração ----------------------------------------------------------------

    def _bootstrap(self, session: Session) -> None:
        """Primeira subida (migração do celular, Task 35.2): liga as operações ativas."""
        _setting(session, pf.MODE_KEY, "plataforma")
        if session.get(AppSetting, BOOTSTRAP_KEY) is not None:
            return
        started = []
        for op in session.scalars(select(Operation).where(Operation.status == "active")):
            pf.runtime(session, op.id).desired_state = "running"
            started.append(op.id)
        session.add(AppSetting(name=BOOTSTRAP_KEY, value=self.clock().isoformat()))
        session.add(Event(entity="platform", action="bootstrapped", detail={"operations": started}))
        log.info("plataforma ativada", extra={"operations": started})

    def _report_server(self, session: Session, versions: list[str], now: datetime) -> None:
        server = session.scalar(select(InfraServer).where(InfraServer.name == self.server_name))
        if server is None:
            server = InfraServer(name=self.server_name)
            session.add(server)
        total, used = _meminfo()
        disk = shutil.disk_usage(self.base if self.base.exists() else "/")
        server.agent_version = code_version() or None
        server.cpu_count = os.cpu_count()
        server.mem_total_mb, server.mem_used_mb = total, used
        server.disk_total_gb = round(disk.total / 1e9, 1)
        server.disk_free_gb = round(disk.free / 1e9, 1)
        server.load1 = round(os.getloadavg()[0], 2) if hasattr(os, "getloadavg") else None
        server.versions = versions
        server.last_seen = now

    def _ensure_nucleo(self, tag: str) -> None:
        file = self.base / "nucleo" / "compose.yml"
        for sub in ("work/buscador", "work/postador", "work/limpeza", "status"):
            (self.base / "nucleo" / sub).mkdir(parents=True, exist_ok=True)
        (self.base / "backups" / "banco").mkdir(parents=True, exist_ok=True)
        text = cp.render(cp.nucleo_compose(self.base, tag))
        changed = not file.exists() or file.read_text() != text
        if changed:
            file.write_text(text)
        running = [c for c in self.docker.ps("fea-nucleo") if c["state"] == "running"]
        if changed or len(running) < 4:
            self.docker.up("fea-nucleo", file)

    # --- cada operação ------------------------------------------------------------------------

    def _reconcile(
        self,
        session: Session,
        rt: OperationRuntime,
        op: Operation,
        versions: list[str],
        latest: str | None,
        now: datetime,
    ) -> None:
        project = cp.project_name(op.id)
        root = cp.op_dir(self.base, op.id)
        file = root / "compose.yml"
        tag = rt.version or latest
        want_running = rt.desired_state == "running" and op.status == "active"
        rt.error = None

        if rt.restore_request and (
            not rt.restore_done_at
            or rt.restore_done_at.isoformat() < rt.restore_request.get("at", "")
        ):
            self._restore(rt, op, root, project)
            rt.restore_done_at = now

        if want_running:
            if not tag or tag not in versions:
                rt.actual_state = "error"
                rt.error = (
                    f"A versão {tag} não existe neste servidor."
                    if tag
                    else "Nenhuma imagem fea-worker no servidor: rode o instalador."
                )
                return
            for sub in [f"work/{r}" for r in cp.ROLES] + ["status"]:
                (root / sub).mkdir(parents=True, exist_ok=True)
            text = cp.render(
                cp.operation_compose(
                    cp.OpSpec(op.id, tag, float(rt.cpu_limit), int(rt.memory_mb)), self.base
                )
            )
            changed = not file.exists() or file.read_text() != text
            if changed:
                file.write_text(text)
            running = [c for c in self.docker.ps(project) if c["state"] == "running"]
            if changed or len(running) < len(cp.ROLES):
                self.docker.up(project, file)
            if rt.restart_requested_at and (
                not rt.restart_done_at or rt.restart_done_at < rt.restart_requested_at
            ):
                self.docker.restart(project, file)
                rt.restart_done_at = now
            rt.actual_version = tag
        else:
            if any(c["state"] == "running" for c in self.docker.ps(project)):
                self.docker.stop(project)

        if rt.backup_requested_at and (
            not rt.backup_done_at or rt.backup_done_at < rt.backup_requested_at
        ):
            rt.backups = self._backup(op, root)
            rt.backup_done_at = now

        self._collect(rt, project, now)

    def _collect(self, rt: OperationRuntime, project: str, now: datetime) -> None:
        containers = self.docker.ps(project)
        stats = self.docker.stats() if any(c["state"] == "running" for c in containers) else {}
        rows, cpu, mem = [], 0.0, 0.0
        for c in containers:
            s = stats.get(c["name"], {})
            cpu += s.get("cpu", 0.0)
            mem += s.get("mem_mb", 0.0)
            rows.append({**c, "cpu": s.get("cpu"), "mem_mb": s.get("mem_mb")})
        rt.containers = rows
        rt.usage = {"cpu": round(cpu, 1), "mem_mb": round(mem, 1)}
        actual = state_of(containers)
        if rt.actual_state != "error" or rt.error is None:
            rt.actual_state = actual
        if actual == "degraded" and not rt.error:
            bad = [c["service"] for c in containers if c["state"] != "running"]
            rt.error = f"Serviço com falha: {', '.join(bad) or 'saúde ruim'}"
        if containers:
            rt.logs = {
                c["service"]: [
                    redact_text(line)[:300]
                    for line in self.docker.logs(project, c["service"], LOG_TAIL)
                ]
                for c in containers
            }
        rt.reported_at = now

    # --- backup e restauração ---------------------------------------------------------------

    def _backup_dir(self, op_id: int) -> Path:
        return self.base / "backups" / f"op-{op_id}"

    def _backup(self, op: Operation, root: Path) -> list[dict]:
        """Arquivos da operação (configuração, estado, logs). A pasta de trabalho fica de fora."""
        folder = self._backup_dir(op.id)
        folder.mkdir(parents=True, exist_ok=True)
        name = f"op-{op.id}-{self.clock().strftime('%Y%m%d-%H%M%S')}.tar.gz"
        with tarfile.open(folder / name, "w:gz") as tar:
            if root.exists():
                for item in sorted(root.iterdir()):
                    if item.name != "work":
                        tar.add(item, arcname=item.name)
        files = sorted(folder.glob(f"op-{op.id}-*.tar.gz"), reverse=True)
        for old in files[KEEP_BACKUPS:]:
            old.unlink(missing_ok=True)
        return [
            {
                "name": f.name,
                "size": f.stat().st_size,
                "at": datetime.fromtimestamp(f.stat().st_mtime, UTC).isoformat(),
            }
            for f in files[:KEEP_BACKUPS]
        ]

    def _restore(self, rt: OperationRuntime, op: Operation, root: Path, project: str) -> None:
        name = Path(rt.restore_request.get("name", "")).name  # sem caminhos
        source = self._backup_dir(op.id) / name
        if not source.is_file():
            raise DockerError(f"Backup {name} não encontrado no servidor.")
        self.docker.stop(project)
        root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(source, "r:gz") as tar:
            tar.extractall(root, filter="data")  # bloqueia caminhos absolutos e "../"
        session = object_session(rt)
        if session is not None:
            session.add(
                Event(
                    entity="runtime",
                    entity_id=op.id,
                    operation_id=op.id,
                    action="restored",
                    detail={"name": name},
                )
            )
