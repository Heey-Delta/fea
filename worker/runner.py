"""Loop dos workers (Task 3).

Um processo por papel (Buscador, Editor, Postador, Limpeza), com N threads. Cada thread:
pega uma tarefa, chama o handler do tipo dela e registra o resultado. Sem tarefas, espera
um aviso do banco (LISTEN/NOTIFY) com tempo crescente até `idle_max`, para não manter o
Neon acordado à toa (Task 3.7). Falha num handler nunca derruba o loop (Task 3.10).
"""

import logging
import os
import socket
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta

import psycopg
from sqlalchemy.orm import Session, sessionmaker

from core import queue, workers
from core.queue import NOTIFY_CHANNEL, PermanentError, RetryableError

log = logging.getLogger("worker")


HEARTBEAT = os.environ.get("WORKER_HEARTBEAT_FILE", "/tmp/fea-worker-heartbeat")


def beat() -> None:
    """Marca que o worker está vivo (lido pelo healthcheck do Docker)."""
    try:
        with open(HEARTBEAT, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def alive(max_age_s: float = 180) -> bool:
    try:
        return time.time() - os.path.getmtime(HEARTBEAT) < max_age_s
    except OSError:
        return False


@dataclass(frozen=True)
class JobContext:
    """O que um handler recebe: os dados da tarefa e como abrir sessões no banco."""

    id: int
    type: str
    ref_id: int | None
    operation_id: int | None
    execution_id: int | None
    attempts: int
    session_factory: sessionmaker
    payload: dict | None = None


Handler = Callable[[JobContext], None]
Periodic = Callable[[Session], None]


class Waiter:
    """Espera um aviso de tarefa nova, ou o tempo acabar, ou o worker ser parado."""

    def __init__(self, stop: threading.Event, dsn: str | None = None):
        self.stop = stop
        self.conn = None
        if dsn:
            try:
                self.conn = psycopg.connect(dsn, autocommit=True)
                self.conn.execute(f"LISTEN {NOTIFY_CHANNEL}")
            except psycopg.Error as exc:
                log.warning("LISTEN indisponível, usando espera simples", extra={"error": str(exc)})
                self.conn = None

    def wait(self, timeout: float) -> bool:
        """True se chegou aviso de tarefa nova."""
        if self.conn is None:
            self.stop.wait(timeout)
            return False
        deadline = time.monotonic() + timeout
        while not self.stop.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            # Fatias curtas para responder rápido a um pedido de parada.
            for _ in self.conn.notifies(timeout=min(remaining, 1.0), stop_after=1):
                return True
        return False

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()


class Worker:
    def __init__(
        self,
        role: str,
        handlers: Mapping[str, Handler],
        session_factory: sessionmaker,
        *,
        concurrency: int = 1,
        listen_dsn: str | None = None,
        idle_max: float = 60.0,
        stale_after: timedelta = timedelta(minutes=30),
        periodic: Mapping[str, tuple[float, Periodic]] | None = None,
    ):
        if not handlers:
            raise ValueError(f"Nenhum handler para o worker {role}")
        self.role = role
        self.handlers = dict(handlers)
        self.types = sorted(self.handlers)
        self.session_factory = session_factory
        self.concurrency = concurrency
        self.listen_dsn = listen_dsn
        self.idle_max = idle_max
        self.stale_after = stale_after
        self.periodic = dict(periodic or {})
        self.stop = threading.Event()
        self.id = f"{role}@{socket.gethostname()}"

    def run_once(self, thread_name: str = "0") -> bool:
        """Processa no máximo uma tarefa. Devolve True se havia tarefa."""
        worker_id = f"{self.id}#{thread_name}"
        with self.session_factory() as session:
            job = queue.claim(session, self.types, worker_id)
            if job is None:
                session.commit()
                return False
            ctx = JobContext(
                id=job.id,
                type=job.type,
                ref_id=job.ref_id,
                operation_id=job.operation_id,
                execution_id=job.execution_id,
                attempts=job.attempts,
                session_factory=self.session_factory,
                payload=job.payload,
            )
            session.commit()

        extra = {"job_id": ctx.id, "job_type": ctx.type, "attempt": ctx.attempts}
        try:
            self.handlers[ctx.type](ctx)
        except RetryableError as exc:
            self._fail(ctx, str(exc), retryable=True, extra=extra)
        except PermanentError as exc:
            self._fail(ctx, str(exc), retryable=False, extra=extra)
        except Exception as exc:  # noqa: BLE001 - erro inesperado conta como falha de processo
            log.exception("erro inesperado no handler", extra=extra)
            self._fail(ctx, f"{type(exc).__name__}: {exc}", retryable=True, extra=extra)
        else:
            with self.session_factory() as session:
                queue.complete(session, ctx.id)
                session.commit()
            log.info("tarefa concluída", extra=extra)
        return True

    def _fail(self, ctx: JobContext, error: str, *, retryable: bool, extra: dict) -> None:
        with self.session_factory() as session:
            status = queue.fail(session, ctx.id, error, retryable=retryable)
            session.commit()
        log.warning("tarefa falhou", extra={**extra, "status": status, "error": error})

    def _loop(self, thread_name: str) -> None:
        waiter = Waiter(self.stop, self.listen_dsn)
        idle = 1.0
        try:
            while not self.stop.is_set():
                try:
                    worked = self.run_once(thread_name)
                except Exception:  # noqa: BLE001 - banco fora do ar etc.: espera e tenta de novo
                    log.exception("falha ao buscar tarefa")
                    worked = False
                if worked:
                    idle = 1.0
                    continue
                if waiter.wait(idle):
                    idle = 1.0
                else:
                    idle = min(idle * 2, self.idle_max)
        finally:
            waiter.close()

    def _maintenance(self) -> None:
        """Tarefas periódicas: devolver tarefas presas e as rotinas do papel (ex.: agendador)."""
        last_run: dict[str, float] = {}
        jobs = {
            "requeue_stale": (300.0, lambda s: queue.requeue_stale(s, self.stale_after)),
            # Sinal de vida no banco: a tela Acessos mostra se o worker está no ar.
            "heartbeat": (60.0, lambda s: workers.beat(s, self.role, socket.gethostname())),
        }
        jobs.update(self.periodic)
        while not self.stop.is_set():
            now = time.monotonic()
            for name, (interval, fn) in jobs.items():
                if now - last_run.get(name, -interval) >= interval:
                    last_run[name] = now
                    try:
                        with self.session_factory() as session:
                            fn(session)
                            session.commit()
                    except Exception:  # noqa: BLE001
                        log.exception("falha na rotina periódica", extra={"routine": name})
            beat()
            self.stop.wait(1.0)

    def run_forever(self) -> None:
        log.info(
            "worker iniciado",
            extra={"role": self.role, "types": self.types, "concurrency": self.concurrency},
        )
        threads = [
            threading.Thread(target=self._loop, args=(str(i),), daemon=True)
            for i in range(self.concurrency)
        ]
        threads.append(threading.Thread(target=self._maintenance, daemon=True))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        log.info("worker parado", extra={"role": self.role})
