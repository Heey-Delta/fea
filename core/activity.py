"""O que cada worker está fazendo agora, para o painel do terminal (`python -m worker painel`).

Cada worker grava um arquivo JSON pequeno em `logs/status/<papel>.json` (ou em FEA_STATUS_DIR):
estado (aguardando, ocupado, erro, parado), o verbo da tarefa no gerúndio, a porcentagem
quando ela é conhecida e quando o arquivo foi atualizado. A gravação é atômica e barata, e o
painel só lê esses arquivos: não toca no banco.
"""

import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Verbo de cada tipo de tarefa, como aparece no painel.
VERBS = {
    "collect": "Buscando",
    "render": "Editando",
    "publish": "Publicando",
    "scheduler": "Agendando",
    "cleanup": "Limpando",
}


def status_dir() -> Path:
    return Path(os.environ.get("FEA_STATUS_DIR") or ROOT / "logs" / "status")


class Activity:
    """Estado de um worker (um por processo). Seguro entre as threads do mesmo worker."""

    def __init__(self, role: str, folder: Path | None = None, clock=time.time):
        self.role = role
        self.folder = folder or status_dir()
        self.clock = clock
        self.lock = threading.Lock()
        self.data = {
            "role": role,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "state": "idle",
            "label": "Aguardando",
            "percent": None,
            "detail": "",
            "error": "",
            "error_at": None,
            "since": clock(),
            "updated_at": clock(),
        }
        self._last_write = 0.0
        self._dirty = False

    @property
    def path(self) -> Path:
        return self.folder / f"{self.role}.json"

    def _write(self) -> None:
        self.data["updated_at"] = self.clock()
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.folder, prefix=f".{self.role}.")
            with os.fdopen(fd, "w") as out:
                json.dump(self.data, out)
            os.replace(tmp, self.path)
            self._last_write = self.clock()
            self._dirty = False
        except OSError:
            pass  # o painel é um extra: nunca derruba o worker

    def _set(self, **values) -> None:
        with self.lock:
            changed_state = values.get("state", self.data["state"]) != self.data["state"]
            changed_label = values.get("label", self.data["label"]) != self.data["label"]
            self.data.update(values)
            if changed_state or changed_label:
                self.data["since"] = self.clock()
            self._write()

    def idle(self) -> None:
        self._set(state="idle", label="Aguardando", percent=None, detail="")

    def busy(self, job_type: str, detail: str = "") -> None:
        label = VERBS.get(job_type, "Trabalhando")
        self._set(state="busy", label=label, percent=None, detail=detail)

    def progress(self, percent: float, detail: str | None = None) -> None:
        """Atualiza a barra. Grava no máximo 2 vezes por segundo."""
        with self.lock:
            self.data["percent"] = max(0.0, min(100.0, float(percent)))
            if detail is not None:
                self.data["detail"] = detail
            if self.clock() - self._last_write >= 0.5 or percent >= 100:
                self._write()
            else:
                self._dirty = True  # o próximo touch grava o valor mais recente

    def failed(self, message: str) -> None:
        """A falha fica visível no painel por um tempo, mesmo depois de voltar a aguardar."""
        self._set(
            state="idle",
            label="Aguardando",
            percent=None,
            error=message[:300],
            error_at=self.clock(),
        )

    def stopped(self) -> None:
        self._set(state="stopped", label="Parado", percent=None, detail="")

    def touch(self) -> None:
        """Sinal de vida para o painel (chamado periodicamente pelo worker)."""
        with self.lock:
            if self._dirty or self.clock() - self._last_write >= 5:
                self._write()


_current: Activity | None = None


def start(role: str) -> Activity:
    global _current
    _current = Activity(role)
    _current.idle()
    return _current


def current() -> Activity | None:
    return _current


def report_progress(percent: float, detail: str | None = None) -> None:
    """Para o código das tarefas (busca, edição): não faz nada fora de um worker."""
    if _current is not None:
        _current.progress(percent, detail)
