"""Modelos de Docker Compose: um projeto por operação e o núcleo (Task 33.1).

Os arquivos são gerados em JSON, que o Compose aceita como YAML, sem dependência extra.

Isolamento de cada operação (segurança e continuidade, não anonimato):
- projeto e rede próprios (`fea-op-<id>`); nenhuma porta publicada;
- raiz só de leitura, `no-new-privileges`, sem capabilities, limite de processos;
- volumes só da operação (`/opt/fea/operations/op-<id>/…`);
- limites de CPU e memória divididos entre busca, edição e publicação;
- `OPERATION_ID`: cada worker só pega tarefas da própria operação.
"""

import json
from dataclasses import dataclass
from pathlib import Path

IMAGE = "fea-worker"
APP = "/srv/fea"  # pasta do código dentro da imagem
ROLES = ("buscador", "editor", "postador")
# Fatia dos limites da operação por serviço: a edição (FFmpeg) é a que mais pesa.
SHARE = {"buscador": 0.2, "editor": 0.6, "postador": 0.2}


@dataclass(frozen=True)
class OpSpec:
    operation_id: int
    image_tag: str
    cpu_limit: float
    memory_mb: int


def project_name(operation_id: int) -> str:
    return f"fea-op-{int(operation_id)}"


def op_dir(base: Path, operation_id: int) -> Path:
    return base / "operations" / f"op-{int(operation_id)}"


def _hardening() -> dict:
    return {
        "read_only": True,
        "tmpfs": ["/tmp:size=64m"],
        "security_opt": ["no-new-privileges:true"],
        "cap_drop": ["ALL"],
        "pids_limit": 256,
        "restart": "unless-stopped",
        "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}},
        "healthcheck": {
            "test": ["CMD", "python", "-m", "worker", "alive"],
            "interval": "60s",
            "timeout": "10s",
            "retries": 3,
            "start_period": "30s",
        },
    }


def _worker(role: str, image_tag: str, base: Path, root: Path, env: dict) -> dict:
    return {
        "image": f"{IMAGE}:{image_tag}",
        "command": ["python", "-m", "worker", role],
        "env_file": [str(base / "secrets" / "worker.env")],
        "environment": {
            **env,
            "WORKER_CONCURRENCY": "1",
            "TMPDIR": "/work",
            "HOME": "/work",
            "FEA_STATUS_DIR": f"{APP}/logs/status",
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        "volumes": [f"{root / 'work' / role}:/work", f"{root / 'status'}:{APP}/logs/status"],
        **_hardening(),
    }


def operation_compose(spec: OpSpec, base: Path) -> dict:
    root = op_dir(base, spec.operation_id)
    services = {}
    for role in ROLES:
        service = _worker(
            role, spec.image_tag, base, root, {"OPERATION_ID": str(spec.operation_id)}
        )
        service["cpus"] = max(0.1, round(spec.cpu_limit * SHARE[role], 2))
        service["mem_limit"] = f"{max(128, int(spec.memory_mb * SHARE[role]))}m"
        service["labels"] = {"fea.operation": str(spec.operation_id), "fea.service": role}
        services[role] = service
    return {"name": project_name(spec.operation_id), "services": services}


BACKUP_LOOP = (
    "while true; do f=/backups/fea-$$(date +%Y%m%d-%H%M).sql.gz; "
    'pg_dump --no-owner --no-privileges "$$DATABASE_URL" | gzip > "$$f.parcial" '
    '&& mv "$$f.parcial" "$$f" && echo "backup ok: $$f" || echo "backup FALHOU"; '
    "find /backups -name 'fea-*' -mtime +14 -delete; sleep 86400; done"
)


def nucleo_compose(base: Path, image_tag: str) -> dict:
    """Rotinas sem operação: agenda, automação, renovação de tokens, limpeza e backup do banco."""
    root = base / "nucleo"
    services = {}
    for role in ("buscador", "postador", "limpeza"):
        service = _worker(role, image_tag, base, root, {"FEA_SCOPE": "nucleo"})
        service["cpus"] = 0.5
        service["mem_limit"] = "384m"
        service["labels"] = {"fea.operation": "nucleo", "fea.service": role}
        services[role] = service
    # Backup diário do banco, 14 dias (o Neon também guarda o próprio histórico).
    services["backup"] = {
        "image": "postgres:17-alpine",
        "env_file": [str(base / "secrets" / "worker.env")],
        "restart": "unless-stopped",
        "volumes": [f"{base / 'backups' / 'banco'}:/backups"],
        "entrypoint": ["/bin/sh", "-c"],
        "command": [BACKUP_LOOP],
        "mem_limit": "256m",
        "security_opt": ["no-new-privileges:true"],
        "labels": {"fea.operation": "nucleo", "fea.service": "backup"},
        "logging": {"driver": "json-file", "options": {"max-size": "1m", "max-file": "2"}},
    }
    return {"name": "fea-nucleo", "services": services}


def render(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
