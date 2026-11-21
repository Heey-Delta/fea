"""Postador (Tasks 16, 19–24): títulos, agenda, envios, falhas e Limpeza."""

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

import core.models as m
from core import accounts as acc
from core import distribution as dist
from core import operations as ops
from core import titles
from core.config import Settings
from core.operations import OperationError
from core.security import TokenCipher
from networks.base import (
    AuthError,
    PlatformAdapter,
    PublishResult,
    RateLimited,
    Uncertain,
)
from tests.test_render_job import factory, pytestmark, storage  # noqa: F401
from worker import publish as pub

SP = ZoneInfo("America/Sao_Paulo")
# Segunda-feira, 10h em São Paulo.
NOW = datetime(2026, 11, 16, 10, 0, tzinfo=SP).astimezone(UTC)
KEY = Fernet.generate_key().decode()


@pytest.fixture
def settings():
    return Settings(_env_file=None, token_encryption_key=KEY, youtube_daily_upload_limit=100)


def make_world(factory, storage, tmp_path, n_items=3, n_accounts=2, daily_limit=3, publish=None):
    """Operação ativa com N vídeos aprovados (render pronto) e M contas conectadas."""
    cipher = TokenCipher(KEY)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 1000)
    with factory() as s:
        accounts = []
        for i in range(n_accounts):
            a = acc.connect(
                s,
                cipher,
                platform="youtube",
                external_id=f"UC{i}",
                name=f"Canal {i}",
                credentials=json.dumps({"refresh_token": f"r{i}"}),
            )
            a.daily_limit = daily_limit
            accounts.append(a)
        config = ops.default_config()
        config["nodes"][3]["config"].update(publish or {})
        config["nodes"] += [
            {
                "id": "f1",
                "type": "source",
                "config": {"type": "reddit", "reference": "r/x", "permission_note": "ok"},
            },
            *[
                {"id": f"c{a.id}", "type": "account", "config": {"account_id": a.id}}
                for a in accounts
            ],
        ]
        config["edges"] += [{"from": "f1", "to": "pesca"}] + [
            {"from": f"c{a.id}", "to": "postagem"} for a in accounts
        ]
        op = ops.create_operation(s, "Postagem", config)
        ops.change_status(s, op, "active")
        source = s.scalars(select(m.Source)).one()
        items = []
        for i in range(n_items):
            item = m.Item(
                operation_id=op.id,
                source_id=source.id,
                external_id=f"p{i}",
                media_type="video",
                status="approved",
                text=f"gato número {i} pulou no sofá da sala",
                sha256=f"{i:064d}",
                original_file=f"operations/{op.id}/items/{i}/original.mp4",
            )
            s.add(item)
            s.flush()
            storage.put_file(item.original_file, video)
            render = m.Render(
                item_id=item.id,
                version=1,
                config_id=ops.current_config(s, op).id,
                status="ok",
                output_file=f"operations/{op.id}/items/{item.id}/renders/1.mp4",
            )
            s.add(render)
            s.flush()
            storage.put_file(render.output_file, video)
            item.approved_render_id = render.id
            item.approved_at = NOW
            items.append(item.id)
        s.commit()
        return op.id, items, [a.id for a in accounts]


class FakeAdapter(PlatformAdapter):
    platform = "youtube"
    capabilities = frozenset({"check"})

    def __init__(self, outcomes=None, found=None):
        self.outcomes = list(outcomes or [])
        self.found = found
        self.calls = []

    def publish(self, credentials, request):
        self.calls.append((credentials, request))
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, Exception):
            raise outcome
        vid = f"vid{len(self.calls)}"
        return PublishResult(vid, f"https://youtube.com/shorts/{vid}")

    def check(self, credentials, title, since_iso):
        return self.found


def batch(factory, op_id, account_ids, **kw):
    with factory() as s:
        op = s.get(m.Operation, op_id)
        b, _ = dist.create_batch(
            s,
            op,
            item_ids=None,
            account_ids=account_ids,
            request_key=kw.pop("request_key", "k1"),
            now=kw.pop("now", NOW),
            **kw,
        )
        s.commit()
        return b.id


def jobs(factory, batch_id=None):
    with factory() as s:
        stmt = select(m.PublishJob).order_by(m.PublishJob.id)
        if batch_id:
            stmt = stmt.where(m.PublishJob.batch_id == batch_id)
        return list(s.scalars(stmt))


# --- Task 16 ------------------------------------------------------------------------------


def test_markov_titles_filter_copies_blocked_and_repeats():
    corpus = [
        "meu gato pulou da mesa e caiu no chão",
        "o cachorro pulou no sofá e dormiu",
        "o gato dormiu no sofá da sala",
        "o gato pulou no sofá e caiu no chão da sala",
    ]
    meta = titles.generate(
        {"hashtags": ["#gatos"]},
        item_text="x",
        corpus=corpus,
        recent_titles=[],
        seed=1,
        platform_tags=["shorts"],
    )
    assert meta.method == "markov" and meta.title[0].isupper()
    assert titles.normalize(meta.title) not in {titles.normalize(c) for c in corpus}
    assert meta.tags == ["gatos", "shorts"] and "#gatos" in meta.description
    blocked = titles.generate(
        {"blocked_words": ["gato", "cachorro"], "templates": ["Veja {texto}"]},
        item_text="isso",
        corpus=corpus,
        recent_titles=[],
        seed=1,
    )
    assert blocked.method == "fallback" and blocked.title == "Veja isso"


def test_fallback_without_corpus_and_title_limit():
    meta = titles.generate(
        {"templates": ["{texto}"]}, item_text="a " * 80, corpus=[], recent_titles=[], title_max=20
    )
    assert meta.method == "fallback" and len(meta.title) <= 20


# --- Tasks 21, 22 e 23 --------------------------------------------------------------------


def test_rotation_alternates_channels_and_respects_interval(factory, storage, tmp_path):  # noqa: F811
    op_id, items, accounts = make_world(factory, storage, tmp_path, n_items=4)
    b = batch(factory, op_id, accounts, interval_min=30, first_immediate=True)
    js = jobs(factory, b)
    assert [j.account_id for j in js] == [accounts[0], accounts[1], accounts[0], accounts[1]]
    assert [(j.planned_at - NOW).total_seconds() / 60 for j in js] == [0, 30, 60, 90]
    assert all(j.status == "planned" for j in js)


def test_request_key_is_idempotent(factory, storage, tmp_path):  # noqa: F811
    op_id, _, accounts = make_world(factory, storage, tmp_path)
    assert batch(factory, op_id, accounts) == batch(factory, op_id, accounts)
    assert len(jobs(factory)) == 3


def test_all_mode_window_daily_limit_and_capacity(factory, storage, tmp_path):  # noqa: F811
    op_id, _, accounts = make_world(
        factory,
        storage,
        tmp_path,
        n_items=10,
        n_accounts=1,
        daily_limit=1,
        publish={"window": {"start": "09:00", "end": "11:00"}},
    )
    b = batch(factory, op_id, accounts, mode="all", interval_min=60, first_immediate=True)
    js = jobs(factory, b)
    planned = [j for j in js if j.status == "planned"]
    local = [j.planned_at.astimezone(SP) for j in planned]
    # 1 por dia, dentro da janela, por 7 dias; o resto fica sem vaga.
    assert local[0] == datetime(2026, 11, 16, 10, 0, tzinfo=SP)
    assert all(t.hour == 9 for t in local[1:]) and len({t.date() for t in local}) == len(local)
    assert len(planned) == 8 and sum(j.status == "pending_capacity" for j in js) == 2


def test_rotation_skips_account_in_error_and_same_hash(factory, storage, tmp_path):  # noqa: F811
    op_id, items, accounts = make_world(factory, storage, tmp_path, n_items=2)
    with factory() as s:
        s.get(m.Account, accounts[1]).status = "error"
        s.commit()
    b = batch(factory, op_id, accounts, first_immediate=True)
    assert {j.account_id for j in jobs(factory, b)} == {accounts[0]}
    # Mesmo vídeo (sha256) já publicado na conta → skipped.
    with factory() as s:
        for j in s.scalars(select(m.PublishJob)):
            j.status = "published"
        item = s.get(m.Item, items[0])
        clone = m.Item(
            operation_id=op_id,
            source_id=item.source_id,
            external_id="clone",
            status="approved",
            sha256=item.sha256,
        )
        s.add(clone)
        s.flush()
        r = m.Render(item_id=clone.id, version=1, config_id=1, status="ok", output_file="x.mp4")
        s.add(r)
        s.flush()
        clone.approved_render_id = r.id
        s.commit()
    b2 = batch(factory, op_id, [accounts[0]], request_key="k2")
    assert [j.status for j in jobs(factory, b2)] == ["skipped"]


def test_pending_capacity_is_reevaluated(factory, storage, tmp_path):  # noqa: F811
    op_id, _, accounts = make_world(
        factory, storage, tmp_path, n_items=1, n_accounts=1, daily_limit=0
    )
    batch(factory, op_id, accounts, first_immediate=True)
    assert jobs(factory)[0].status == "pending_capacity"
    with factory() as s:
        s.get(m.Account, accounts[0]).daily_limit = 2
        assert dist.reevaluate_pending(s, NOW) == 1
        s.commit()
    assert jobs(factory)[0].status == "planned"


def test_automatic_distribution(factory, storage, tmp_path):  # noqa: F811
    op_id, _, _ = make_world(
        factory, storage, tmp_path, n_items=2, publish={"automatic": True, "mode": "rotation"}
    )
    with factory() as s:
        result = pub.scheduler_tick(s, NOW)
        s.commit()
        again = pub.scheduler_tick(s, NOW)
    assert len(result["batches"]) == 1 and again["batches"] == []
    assert len(jobs(factory)) == 2


# --- Task 24 ------------------------------------------------------------------------------


def run_publish(factory, storage, settings, adapter, job_id, now=NOW):  # noqa: F811
    return pub.run_publish(factory, job_id, storage, settings, lambda _: adapter, now=now)


def test_publish_generates_title_and_schedules_cleanup(factory, storage, settings, tmp_path):  # noqa: F811
    op_id, items, accounts = make_world(factory, storage, tmp_path, n_items=1)
    batch(factory, op_id, accounts, first_immediate=True)
    job = jobs(factory)[0]
    with factory() as s:
        assert pub.scheduler_tick(s, NOW)["enqueued"] == 1
        s.commit()
    adapter = FakeAdapter()
    assert run_publish(factory, storage, settings, adapter, job.id) == "published"
    credentials, request = adapter.calls[0]
    assert json.loads(credentials)["refresh_token"] == "r0" and request.title
    job = jobs(factory)[0]
    assert job.url.endswith("/vid1") and job.title_method in ("markov", "fallback")
    # Não publica duas vezes.
    assert run_publish(factory, storage, settings, adapter, job.id) is None
    with factory() as s:
        item = s.get(m.Item, items[0])
        assert item.delete_after == NOW + timedelta(minutes=30)
        assert pub.run_cleanup(s, storage, NOW + timedelta(minutes=29)) == 0
        assert pub.run_cleanup(s, storage, NOW + timedelta(minutes=31)) == 1
        s.commit()
        assert not storage.exists(item.original_file)
        assert s.get(m.Render, item.approved_render_id).files_deleted_at is not None


def test_rate_limit_waits_then_fails(factory, storage, settings, tmp_path):  # noqa: F811
    op_id, _, accounts = make_world(factory, storage, tmp_path, n_items=1)
    batch(factory, op_id, accounts, first_immediate=True)
    job_id = jobs(factory)[0].id
    adapter = FakeAdapter([RateLimited("quota")] * 4)
    waits = []
    now = NOW
    for _ in range(3):
        assert run_publish(factory, storage, settings, adapter, job_id, now) == "retry_wait"
        job = jobs(factory)[0]
        waits.append((job.planned_at - now).total_seconds() / 60)
        now = job.planned_at
    assert waits == [2, 10, 30]
    assert run_publish(factory, storage, settings, adapter, job_id, now) == "failed"


def test_uncertain_checks_before_retry(factory, storage, settings, tmp_path):  # noqa: F811
    op_id, _, accounts = make_world(factory, storage, tmp_path, n_items=1)
    batch(factory, op_id, accounts, first_immediate=True)
    job_id = jobs(factory)[0].id
    adapter = FakeAdapter([Uncertain("timeout")])
    assert run_publish(factory, storage, settings, adapter, job_id) == "uncertain"
    with factory() as s:
        check = s.scalars(select(m.Job).where(m.Job.payload["check"].as_boolean())).one()
        assert check.ref_id == job_id
    adapter.found = PublishResult("abc", "https://youtube.com/shorts/abc")
    assert pub.run_check(factory, job_id, settings, lambda _: adapter, NOW) == "published"
    assert jobs(factory)[0].external_id == "abc" and len(adapter.calls) == 1


def test_uncertain_not_found_goes_to_retry(factory, storage, settings, tmp_path):  # noqa: F811
    op_id, _, accounts = make_world(factory, storage, tmp_path, n_items=1)
    batch(factory, op_id, accounts, first_immediate=True)
    job_id = jobs(factory)[0].id
    adapter = FakeAdapter([Uncertain("timeout")])
    run_publish(factory, storage, settings, adapter, job_id)
    assert pub.run_check(factory, job_id, settings, lambda _: adapter, NOW) == "retry_wait"


def test_auth_error_marks_account_and_waits(factory, storage, settings, tmp_path):  # noqa: F811
    op_id, _, accounts = make_world(factory, storage, tmp_path, n_items=2)
    batch(factory, op_id, accounts, first_immediate=True, interval_min=0)
    first, second = jobs(factory)
    adapter = FakeAdapter([AuthError("invalid_grant")])
    assert run_publish(factory, storage, settings, adapter, first.id) == "planned"
    with factory() as s:
        assert s.get(m.Account, first.account_id).status == "error"
    # A outra conta segue normalmente.
    assert run_publish(factory, storage, settings, adapter, second.id) == "published"
    # O envio da conta em erro espera, sem gastar tentativa.
    assert (
        run_publish(factory, storage, settings, adapter, first.id, NOW + timedelta(hours=1)) is None
    )
    assert jobs(factory)[0].attempts == 0 and "aguardando" in jobs(factory)[0].status_reason


def test_daily_quota_postpones(factory, storage, settings, tmp_path):  # noqa: F811
    op_id, _, accounts = make_world(factory, storage, tmp_path, n_items=1)
    batch(factory, op_id, accounts, first_immediate=True)
    job_id = jobs(factory)[0].id
    tight = Settings(_env_file=None, token_encryption_key=KEY, youtube_daily_upload_limit=0)
    assert run_publish(factory, storage, tight, FakeAdapter(), job_id) is None
    job = jobs(factory)[0]
    assert job.status == "planned" and job.planned_at > NOW and "Cota" in job.status_reason


def test_failed_jobs_keep_files_and_rejected_are_cleaned(factory, storage, settings, tmp_path):  # noqa: F811
    op_id, items, accounts = make_world(factory, storage, tmp_path, n_items=2)
    batch(factory, op_id, accounts, mode="all", first_immediate=True, interval_min=0)
    js = jobs(factory)
    adapter = FakeAdapter()
    for j in js[:-1]:
        run_publish(factory, storage, settings, adapter, j.id)
    with factory() as s:
        last = s.get(m.PublishJob, js[-1].id)
        last.status = "failed"
        rejected = s.get(m.Item, items[1])
        s.commit()
        later = NOW + timedelta(days=1)
        cleaned = pub.run_cleanup(s, storage, later)
        s.commit()
    # O item 0 publicou nas duas contas: limpo. O item 1 tem envio com falha: fica.
    assert cleaned == 1
    with factory() as s:
        assert s.get(m.Item, items[0]).files_deleted_at is not None
        assert s.get(m.Item, items[1]).files_deleted_at is None
        dist.resolve_uncertain(s, s.get(m.PublishJob, js[-1].id), "cancel")
        s.get(m.Item, items[1]).status = "rejected"
        s.commit()
        assert pub.run_cleanup(s, storage, datetime.now(UTC) + timedelta(hours=1)) == 1
    assert rejected.id == items[1]


def test_failed_job_goes_back_to_the_agenda_without_duplicate(factory, storage, tmp_path):  # noqa: F811
    """Envio que falhou: o vídeo pode ser agendado de novo no mesmo registro, sem erro 500."""
    op_id, items, accounts = make_world(factory, storage, tmp_path, n_items=1, n_accounts=1)
    first = batch(factory, op_id, accounts, interval_min=0, request_key="k1")
    with factory() as s:
        job = s.scalars(select(m.PublishJob)).one()
        job.status, job.attempts, job.status_reason = "failed", 2, "erro da API"
        s.commit()
        job_id = job.id
    second = batch(factory, op_id, accounts, interval_min=0, request_key="k2")
    assert second != first
    with factory() as s:
        all_jobs = s.scalars(select(m.PublishJob)).all()
        assert len(all_jobs) == 1 and all_jobs[0].id == job_id
        assert all_jobs[0].status == "planned" and all_jobs[0].attempts == 0
        assert all_jobs[0].batch_id == second
    with factory() as s, pytest.raises(OperationError, match="Nenhum vídeo aprovado"):
        dist.create_batch(  # já está planejado de novo: não entra outra vez
            s,
            s.get(m.Operation, op_id),
            item_ids=None,
            account_ids=accounts,
            request_key="k3",
            now=NOW,
        )
