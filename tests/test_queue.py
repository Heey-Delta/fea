"""Fila de tarefas e workers (Task 3), contra o Postgres de teste."""

import os
import threading
import time
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.orm import sessionmaker

import core.models as m
from core import queue
from core.db import sqlalchemy_url
from core.queue import PermanentError, RetryableError
from worker.handlers import ROLE_TYPES, enqueue_scheduler_tick, handlers_for, register
from worker.runner import Waiter, Worker

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL não definida")


@pytest.fixture(scope="module")
def factory():
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", sqlalchemy_url(DATABASE_URL))
    command.upgrade(config, "head")
    engine = create_engine(sqlalchemy_url(DATABASE_URL))
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture(autouse=True)
def clean(factory):
    with factory() as s:
        s.execute(text("TRUNCATE jobs, executions, operations RESTART IDENTITY CASCADE"))
        s.commit()


def add_job(factory, type="collect", key=None, **kw):
    with factory() as s:
        result = queue.enqueue(s, type, key or f"{type}:{time.monotonic_ns()}", **kw)
        s.commit()
        return result.id


def job(factory, job_id) -> m.Job:
    with factory() as s:
        return s.get(m.Job, job_id)


def make_execution(factory, status="running") -> int:
    with factory() as s:
        op = m.Operation(name="Op")
        s.add(op)
        s.flush()
        cfg = m.OperationConfig(operation_id=op.id, version=1, config={})
        s.add(cfg)
        s.flush()
        ex = m.Execution(
            operation_id=op.id, config_id=cfg.id, target_x=10, search_budget=100, status=status
        )
        s.add(ex)
        s.commit()
        return ex.id


# --- fila -------------------------------------------------------------------------------


def test_enqueue_is_idempotent(factory):
    with factory() as s:
        first = queue.enqueue(s, "render", "render:1:1")
        second = queue.enqueue(s, "render", "render:1:1")
        s.commit()
    assert first.created and not second.created
    assert first.id == second.id
    with factory() as s:
        assert queue.queue_counts(s) == {("render", "queued"): 1}


def test_claim_respects_priority_then_age(factory):
    low = add_job(factory, priority="low")
    normal = add_job(factory)
    high = add_job(factory, priority="high")
    order = []
    with factory() as s:
        for _ in range(3):
            order.append(queue.claim(s, ["collect"], "t").id)
        s.commit()
    assert order == [high, normal, low]


def test_claim_only_takes_its_types(factory):
    add_job(factory, type="render")
    with factory() as s:
        assert queue.claim(s, ["collect"], "t") is None


def test_future_jobs_wait(factory):
    add_job(factory, run_at=datetime.now(UTC) + timedelta(hours=1))
    with factory() as s:
        assert queue.claim(s, ["collect"], "t") is None


def test_claim_marks_running(factory):
    job_id = add_job(factory)
    with factory() as s:
        claimed = queue.claim(s, ["collect"], "w1")
        s.commit()
    j = job(factory, job_id)
    assert claimed.id == job_id
    assert (j.status, j.attempts, j.locked_by) == ("running", 1, "w1")


def test_skip_locked_gives_different_jobs(factory):
    a = add_job(factory)
    b = add_job(factory)
    s1, s2 = factory(), factory()
    try:
        first = queue.claim(s1, ["collect"], "w1")
        second = queue.claim(s2, ["collect"], "w2")  # s1 ainda segura o lock
        assert {first.id, second.id} == {a, b}
        with factory() as s3:
            assert queue.claim(s3, ["collect"], "w3") is None
            s3.rollback()
    finally:
        s1.rollback()
        s2.rollback()
        s1.close()
        s2.close()


def test_paused_execution_jobs_stay_queued(factory):
    paused = make_execution(factory, status="paused")
    running = make_execution(factory)
    add_job(factory, execution_id=paused, priority="high")
    wanted = add_job(factory, execution_id=running)
    with factory() as s:
        assert queue.claim(s, ["collect"], "t").id == wanted
        assert queue.claim(s, ["collect"], "t") is None


def test_retry_then_fail(factory):
    job_id = add_job(factory, max_attempts=2)
    with factory() as s:
        queue.claim(s, ["collect"], "t")
        assert queue.fail(s, job_id, "timeout", retryable=True) == "queued"
        s.commit()
    j = job(factory, job_id)
    assert j.run_at > datetime.now(UTC) + timedelta(seconds=20)  # espera 30 s
    with factory() as s:
        s.execute(update(m.Job).where(m.Job.id == job_id).values(run_at=datetime.now(UTC)))
        queue.claim(s, ["collect"], "t")
        assert queue.fail(s, job_id, "timeout", retryable=True) == "failed"
        s.commit()


def test_permanent_error_fails_at_once(factory):
    job_id = add_job(factory)
    with factory() as s:
        queue.claim(s, ["collect"], "t")
        assert queue.fail(s, job_id, "arquivo corrompido", retryable=False) == "failed"
        s.commit()


def test_error_text_is_redacted(factory):
    job_id = add_job(factory)
    with factory() as s:
        queue.claim(s, ["collect"], "t")
        queue.fail(s, job_id, "401 Bearer ya29.secreto", retryable=False)
        s.commit()
    assert "ya29" not in job(factory, job_id).last_error


def test_backoff_grows_and_caps():
    assert [queue.backoff_seconds(n) for n in (1, 2, 3)] == [30, 60, 120]
    assert queue.backoff_seconds(50) == queue.MAX_BACKOFF_S


def test_requeue_stale(factory):
    stuck = add_job(factory)
    exhausted = add_job(factory, max_attempts=1)
    with factory() as s:
        queue.claim(s, ["collect"], "morto")
        queue.claim(s, ["collect"], "morto")
        s.execute(update(m.Job).values(locked_at=datetime.now(UTC) - timedelta(hours=2)))
        assert queue.requeue_stale(s, timedelta(minutes=30)) == 2
        s.commit()
    assert job(factory, stuck).status == "queued"
    assert job(factory, exhausted).status == "failed"


def test_worker_reiniciado_devolve_as_proprias_tarefas_na_hora(factory):
    mine = add_job(factory)
    other = add_job(factory)
    with factory() as s:
        queue.claim(s, ["collect"], "buscador@celular#0")
        queue.claim(s, ["collect"], "buscador@outro#0")
        assert queue.release_own(s, "buscador@celular") == 1
        s.commit()
    assert job(factory, mine).status == "queued"  # sem esperar os 30 minutos
    assert job(factory, other).status == "running"


def test_cancel_execution_jobs(factory):
    ex = make_execution(factory)
    queued = add_job(factory, execution_id=ex)
    running = add_job(factory, execution_id=ex)
    with factory() as s:
        s.execute(update(m.Job).where(m.Job.id == running).values(status="running"))
        assert queue.cancel_execution_jobs(s, ex) == 1
        s.commit()
    assert job(factory, queued).status == "cancelled"
    assert job(factory, running).status == "running"


# --- worker -----------------------------------------------------------------------------


def make_worker(factory, handler, **kw) -> Worker:
    return Worker("buscador", {"collect": handler}, factory, **kw)


def test_worker_completes_job(factory):
    seen = []
    job_id = add_job(factory, ref_id=42)
    worker = make_worker(factory, lambda ctx: seen.append((ctx.id, ctx.ref_id, ctx.attempts)))
    assert worker.run_once() is True
    assert seen == [(job_id, 42, 1)]
    assert job(factory, job_id).status == "done"
    assert worker.run_once() is False


def test_worker_handles_each_error_kind(factory):
    def retryable(ctx):
        raise RetryableError("rate limit")

    def permanent(ctx):
        raise PermanentError("vídeo sem áudio")

    def crash(ctx):
        raise KeyError("bug")

    for handler, expected in ((retryable, "queued"), (permanent, "failed"), (crash, "queued")):
        job_id = add_job(factory)
        make_worker(factory, handler).run_once()
        assert job(factory, job_id).status == expected, handler.__name__


def test_handler_failure_does_not_stop_the_loop(factory):
    calls = Counter()

    def handler(ctx):
        calls[ctx.ref_id] += 1
        if ctx.ref_id == 1:
            raise PermanentError("ruim")

    for ref in (1, 2, 3):
        add_job(factory, ref_id=ref)
    worker = make_worker(factory, handler)
    while worker.run_once():
        pass
    assert calls == {1: 1, 2: 1, 3: 1}


def test_concurrent_threads_process_each_job_once(factory):
    for i in range(30):
        add_job(factory, ref_id=i)
    lock = threading.Lock()
    done = Counter()

    def handler(ctx):
        time.sleep(0.005)
        with lock:
            done[ctx.ref_id] += 1

    worker = make_worker(factory, handler, concurrency=4, idle_max=0.2)
    thread = threading.Thread(target=worker.run_forever)
    thread.start()
    deadline = time.monotonic() + 15
    while sum(done.values()) < 30 and time.monotonic() < deadline:
        time.sleep(0.05)
    worker.stop.set()
    thread.join(timeout=10)
    assert sorted(done) == list(range(30))
    assert set(done.values()) == {1}
    with factory() as s:
        assert queue.queue_counts(s) == {("collect", "done"): 30}


def test_notify_wakes_waiting_worker(factory):
    stop = threading.Event()
    waiter = Waiter(stop, DATABASE_URL)
    try:
        assert waiter.conn is not None
        threading.Timer(0.3, lambda: add_job(factory)).start()
        started = time.monotonic()
        assert waiter.wait(10) is True
        assert time.monotonic() - started < 5
    finally:
        waiter.close()


def test_waiter_without_listen_just_sleeps():
    stop = threading.Event()
    started = time.monotonic()
    assert Waiter(stop).wait(0.2) is False
    assert time.monotonic() - started >= 0.19


def test_stop_interrupts_waiting(factory):
    stop = threading.Event()
    waiter = Waiter(stop, DATABASE_URL)
    threading.Timer(0.2, stop.set).start()
    started = time.monotonic()
    assert waiter.wait(30) is False
    assert time.monotonic() - started < 5
    waiter.close()


# --- papéis -----------------------------------------------------------------------------


def test_roles_cover_every_job_type():
    from core.states import JOB_TYPE

    covered = {t for types in ROLE_TYPES.values() for t in types}
    assert covered == set(JOB_TYPE)


def test_register_adds_handler_to_role():
    from worker.handlers import HANDLERS

    @register("cleanup")
    def fake(ctx):
        pass

    try:
        assert handlers_for("limpeza") == {"cleanup": fake}
    finally:
        HANDLERS.pop("cleanup")


def test_scheduler_tick_once_per_minute(factory):
    with factory() as s:
        enqueue_scheduler_tick(s)
        enqueue_scheduler_tick(s)
        s.commit()
        total = s.execute(select(m.Job).where(m.Job.type == "scheduler")).scalars().all()
    assert len(total) == 1


# --- Task 31: filas separadas por operação ----------------------------------------------


def make_operation(factory, name) -> int:
    with factory() as s:
        op = m.Operation(name=name)
        s.add(op)
        s.commit()
        return op.id


def test_escopo_separa_operacoes_e_nucleo(factory):
    a, b = make_operation(factory, "A"), make_operation(factory, "B")
    ja = add_job(factory, "collect", operation_id=a)
    jb = add_job(factory, "collect", operation_id=b)
    jn = add_job(factory, "scheduler")  # sem operação: núcleo
    with factory() as s:
        assert queue.claim(s, ["collect", "scheduler"], "w", scope=b).id == jb
        assert queue.claim(s, ["collect", "scheduler"], "w", scope=b) is None  # nada mais de B
        assert queue.claim(s, ["collect", "scheduler"], "w", scope="nucleo").id == jn
        assert queue.claim(s, ["collect", "scheduler"], "w", scope="nucleo") is None
        assert queue.claim(s, ["collect"], "w", scope=a).id == ja
        s.commit()


def test_sem_escopo_pega_tudo_como_antes(factory):
    a = make_operation(factory, "A")
    ids = {add_job(factory, "collect", operation_id=a), add_job(factory, "collect")}
    with factory() as s:
        got = {queue.claim(s, ["collect"], "w").id, queue.claim(s, ["collect"], "w").id}
        s.commit()
    assert got == ids


def test_falha_numa_operacao_nao_toca_a_outra(factory):
    a, b = make_operation(factory, "A"), make_operation(factory, "B")
    calls = []

    def handler(ctx):
        calls.append(ctx.operation_id)
        if ctx.operation_id == a:
            raise PermanentError("quebrou em A")

    ja = add_job(factory, "collect", operation_id=a)
    jb = add_job(factory, "collect", operation_id=b)
    Worker("buscador", {"collect": handler}, factory, scope=a).run_once()
    assert job(factory, ja).status == "failed" and job(factory, jb).status == "queued"
    Worker("buscador", {"collect": handler}, factory, scope=b).run_once()
    assert job(factory, jb).status == "done" and calls == [a, b]


def test_worker_le_o_escopo_do_ambiente(monkeypatch):
    from worker.__main__ import worker_scope

    monkeypatch.delenv("OPERATION_ID", raising=False)
    monkeypatch.delenv("FEA_SCOPE", raising=False)
    assert worker_scope() is None
    monkeypatch.setenv("FEA_SCOPE", "nucleo")
    assert worker_scope() == "nucleo"
    monkeypatch.setenv("OPERATION_ID", "7")
    assert worker_scope() == 7
    monkeypatch.setenv("OPERATION_ID", "x; rm -rf")
    with pytest.raises(SystemExit):
        worker_scope()
