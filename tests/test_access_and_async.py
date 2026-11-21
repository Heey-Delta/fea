"""Chaves pela interface (Acessos), envios assíncronos e métricas no Postador (Task 28)."""

from datetime import timedelta

from sqlalchemy import select

import core.models as m
from core import credentials as creds
from core.config import Settings
from networks.base import PublishFailed, PublishResult
from tests.test_publish import (  # noqa: F401
    KEY,
    NOW,
    FakeAdapter,
    batch,
    jobs,
    make_world,
    run_publish,
    settings,
)
from tests.test_render_job import factory, pytestmark, storage  # noqa: F401
from worker import publish as pub


def test_credentials_saved_encrypted_and_env_wins(factory, settings):  # noqa: F811
    with factory() as s:
        saved = creds.save(
            s, settings, {"reddit_client_id": "abc", "x_bearer_token": "segredo1234"}
        )
        s.commit()
        assert sorted(saved) == ["reddit_client_id", "x_bearer_token"]
        row = s.get(m.AppCredential, "x_bearer_token")
        assert "segredo" not in row.value_encrypted
        eff = creds.effective(s, settings)
        assert (eff.reddit_client_id, eff.x_bearer_token) == ("abc", "segredo1234")
        env = settings.model_copy(update={"reddit_client_id": "do-env"})
        assert creds.effective(s, env).reddit_client_id == "do-env"
        by_id = {st.service.id: st for st in creds.status(s, settings)}
        x_field = by_id["x"].fields[0]
        assert (x_field.source, x_field.hint) == ("banco", "••••1234")
        assert by_id["x"].ready and not by_id["youtube"].ready
        creds.clear(s, "x")
        s.commit()
        assert creds.effective(s, settings).x_bearer_token == ""


def test_credentials_need_encryption_key(factory):  # noqa: F811
    import pytest

    with factory() as s, pytest.raises(creds.CredentialError):
        creds.save(s, Settings(_env_file=None), {"x_bearer_token": "x"})


class AsyncAdapter(FakeAdapter):
    """Como TikTok/Instagram: aceita o envio e processa depois."""

    capabilities = frozenset({"async_status", "needs_public_url"})

    def __init__(self, final=None, fail=False):
        super().__init__()
        self.final, self.fail, self.urls = final, fail, []
        self.refreshed = False

    def fresh_credentials(self, credentials):
        self.refreshed = True
        return credentials.replace("r0", "r0-novo")

    def publish(self, credentials, request):
        self.calls.append((credentials, request))
        self.urls.append(request.file_url)
        return PublishResult("proc1", "", status="processing")

    def status(self, credentials, external_id):
        if self.fail:
            raise PublishFailed("recusado")
        return self.final

    def metrics(self, credentials, external_ids):
        return {i: {"views": 5} for i in external_ids}


def test_async_publish_processing_then_published(factory, storage, settings, tmp_path):  # noqa: F811
    op_id, items, accounts = make_world(factory, storage, tmp_path, n_items=1, n_accounts=1)
    batch(factory, op_id, accounts, first_immediate=True)
    job_id = jobs(factory)[0].id
    adapter = AsyncAdapter()
    assert run_publish(factory, storage, settings, adapter, job_id) == "processing"
    assert adapter.refreshed and "r0-novo" in adapter.calls[0][0]
    assert adapter.urls[0]  # URL do arquivo para quem precisa (Instagram)
    with factory() as s:
        account = s.get(m.Account, accounts[0])
        from core.security import TokenCipher

        assert "r0-novo" in TokenCipher(KEY).decrypt(account.token_encrypted)  # token gravado
        job = s.get(m.PublishJob, job_id)
        assert job.external_id == "proc1" and s.get(m.Item, items[0]).delete_after is None
        assert s.scalars(select(m.Job).where(m.Job.payload["status"].as_boolean())).first()
    # Ainda processando: continua; depois publica.
    assert pub.run_status(factory, job_id, settings, lambda _: adapter, NOW) == "processing"
    adapter.final = PublishResult("vid9", "https://tiktok.com/@x/video/vid9")
    assert pub.run_status(factory, job_id, settings, lambda _: adapter, NOW) == "published"
    with factory() as s:
        job = s.get(m.PublishJob, job_id)
        assert job.url.endswith("vid9") and s.get(m.Item, items[0]).delete_after is not None


def test_async_publish_failure(factory, storage, settings, tmp_path):  # noqa: F811
    op_id, _, accounts = make_world(factory, storage, tmp_path, n_items=1, n_accounts=1)
    batch(factory, op_id, accounts, first_immediate=True)
    job_id = jobs(factory)[0].id
    adapter = AsyncAdapter(fail=True)
    run_publish(factory, storage, settings, adapter, job_id)
    assert pub.run_status(factory, job_id, settings, lambda _: adapter, NOW) == "failed"


def test_metrics_refresh(factory, storage, settings, tmp_path):  # noqa: F811
    op_id, _, accounts = make_world(factory, storage, tmp_path, n_items=2, n_accounts=1)
    batch(factory, op_id, accounts, first_immediate=True, interval_min=0)
    for job in jobs(factory):
        run_publish(factory, storage, settings, FakeAdapter(), job.id)
    with factory() as s:
        due = pub.metrics_due(s, NOW + timedelta(minutes=5))
        assert list(due) == accounts and len(due[accounts[0]]) == 2
        tick = pub.scheduler_tick(s, NOW + timedelta(minutes=5))
        s.commit()
        assert tick["enqueued"] == 0
        assert s.scalars(select(m.Job).where(m.Job.idempotency_key.like("metrics:%"))).first()
    adapter = AsyncAdapter()
    later = NOW + timedelta(minutes=5)
    assert pub.run_metrics(factory, accounts[0], settings, lambda _: adapter, later) == 2
    assert all(j.metrics == {"views": 5} for j in jobs(factory))
    with factory() as s:
        assert pub.metrics_due(s, later + timedelta(hours=1)) == {}


def test_daily_token_refresh(factory, storage, settings, tmp_path):  # noqa: F811
    from core.security import TokenCipher

    make_world(factory, storage, tmp_path, n_items=1, n_accounts=1)
    with factory() as s:
        account = s.scalars(select(m.Account)).one()
        account.platform = "tiktok"
        s.commit()
        pub.scheduler_tick(s, NOW)
        s.commit()
        job = s.scalars(select(m.Job).where(m.Job.idempotency_key.like("refresh:%"))).one()
        assert job.ref_id == account.id
    assert pub.run_refresh(factory, account.id, settings, lambda _: AsyncAdapter()) is True
    with factory() as s:
        token = TokenCipher(KEY).decrypt(s.get(m.Account, account.id).token_encrypted)
        assert "r0-novo" in token


def test_storage_switches_to_r2_saved_in_access_page(factory, settings, tmp_path):  # noqa: F811
    from core.storage import DynamicStorage, LocalStorage, R2Storage

    settings = settings.model_copy(update={"storage_dir": str(tmp_path)})
    storage = DynamicStorage(settings, factory, ttl=0)
    assert isinstance(storage.current(), LocalStorage)
    with factory() as s:
        creds.save(
            s,
            settings,
            {
                "r2_account_id": "conta",
                "r2_access_key_id": "id",
                "r2_secret_access_key": "segredo",
                "r2_bucket": "fea",
            },
        )
        s.commit()
        assert {st.service.id: st.ready for st in creds.status(s, settings)}["r2"]
    assert isinstance(storage.current(), R2Storage)
    assert "fea" in storage.url("a/b.mp4")  # delega para o R2


def test_migration_status_and_upgrade(factory):  # noqa: F811
    from core.migrate import status, upgrade

    engine = factory.kw["bind"]
    st = status(engine)
    assert st["up_to_date"] and st["head"] == "0011"
    assert upgrade(engine)["up_to_date"]


def test_vps_installer_is_served_and_valid():
    import subprocess
    from pathlib import Path

    script = Path("web/static/instalar-vps.sh")
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0
    text = script.read_text()
    assert "DATABASE_URL" in text and "TOKEN_ENCRYPTION_KEY" in text and "Deploy keys" in text


def test_termux_installer_is_valid_and_safe():
    import subprocess
    from pathlib import Path

    script = Path("web/static/instalar-termux.sh")
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0
    text = script.read_text()
    assert "Deploy keys" in text and "fea-workers" in text
    assert "DATABASE_URL" not in text and "TOKEN_ENCRYPTION_KEY" not in text  # sem segredos


def test_time_zones_work_without_system_tz_database():
    """Android (Termux) não tem /usr/share/zoneinfo: o pacote tzdata precisa bastar."""
    import os
    import subprocess
    import sys

    code = (
        "import zoneinfo; zoneinfo.ZoneInfo('America/Los_Angeles'); "
        "zoneinfo.ZoneInfo('America/Sao_Paulo'); import worker.publish"
    )
    env = {**os.environ, "PYTHONTZPATH": "/nao-existe"}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-500:]
