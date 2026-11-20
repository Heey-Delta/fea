"""Limite de uso do R2: conta as operações, mede o bucket e trava antes de sair do grátis."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core import usage
from core.storage import R2Storage
from tests.test_render_job import factory, pytestmark  # noqa: F401


class FakeS3:
    def __init__(self):
        self.objects: dict[str, int] = {}

    def upload_file(self, src, bucket, key, ExtraArgs=None, Config=None):  # noqa: N803
        self.objects[key] = Path(src).stat().st_size

    def download_file(self, bucket, key, dst, Config=None):  # noqa: N803
        Path(dst).write_bytes(b"x" * self.objects[key])

    def delete_object(self, Bucket, Key):  # noqa: N803
        self.objects.pop(Key, None)

    def generate_presigned_url(self, op, Params, ExpiresIn):  # noqa: N803
        return f"https://r2.test/{Params['Key']}"

    def get_paginator(self, name):
        objects = self.objects

        class P:
            def paginate(self, **kw):
                yield {"Contents": [{"Key": k, "Size": s} for k, s in sorted(objects.items())]}

        return P()


def r2(meter) -> R2Storage:
    st = R2Storage.__new__(R2Storage)
    st.meter, st.bucket, st.client = meter, "fea", FakeS3()
    st.transfer = None
    return st


def test_conta_operacoes_e_bloqueia_no_limite(factory, tmp_path):  # noqa: F811
    meter = usage.UsageMeter(factory, ttl=0)
    st = r2(meter)
    f = tmp_path / "v.mp4"
    f.write_bytes(b"abc")
    st.put_file("a.mp4", f, "video/mp4")
    st.get_file("a.mp4", tmp_path / "out.mp4")
    st.url("a.mp4")
    st.list("")
    with factory() as s:
        vals = usage.values(s)
    assert vals == {"class_a": 2, "class_b": 2, "storage_bytes": 3}

    with factory() as s:
        usage.set_setting(s, usage.PCT_KEY, "10")
        usage.add(s, "class_a", 100_000)
        s.commit()
    with pytest.raises(usage.QuotaExceeded):
        st.put_file("b.mp4", f)
    with pytest.raises(usage.QuotaExceeded):
        st.upload_url("c.mp4", "video/mp4")
    assert "b.mp4" not in st.client.objects
    st.get_file("a.mp4", tmp_path / "ok.mp4")  # leituras têm limite próprio
    st.delete("a.mp4")  # apagar é grátis e nunca trava
    assert st.client.objects == {}


def test_medicao_guarda_o_pico_do_mes(factory):  # noqa: F811
    now = datetime(2026, 11, 20, 12, tzinfo=UTC)
    with factory() as s:
        usage.set_storage(s, 5_000, now)
        usage.set_storage(s, 2_000, now + timedelta(hours=1))
        s.commit()
        assert usage.values(s, "2026-11")["storage_bytes"] == 5_000
        usage.set_storage(s, 1_000, datetime(2026, 12, 1, tzinfo=UTC))
        s.commit()
        assert usage.values(s, "2026-12")["storage_bytes"] == 1_000


def test_limpeza_mede_o_bucket_de_hora_em_hora(factory, tmp_path):  # noqa: F811
    from worker.publish import measure_bucket

    st = r2(usage.UsageMeter(factory, ttl=0))
    st.client.objects = {"a": 10, "b": 20}
    now = datetime.now(UTC)
    with factory() as s:
        assert measure_bucket(s, st, now) == 30
        assert measure_bucket(s, st, now + timedelta(minutes=30)) is None
        assert measure_bucket(s, st, now + timedelta(minutes=61)) == 30
        s.commit()


def test_dashboard_mostra_o_uso_e_salva_o_limite(factory, settings):  # noqa: F811
    from fastapi.testclient import TestClient

    from tests.conftest import fake_github, github_login
    from web.main import create_app

    app = create_app(settings)
    app.state.http_client_factory = fake_github()
    client = TestClient(app)
    github_login(client)
    page = client.get("/")
    assert "Limite de uso do R2" in page.text and "80% da franquia" in page.text
    r = client.post("/uso/limite", data={"pct": "50"}, follow_redirects=False)
    assert r.status_code == 303
    with factory() as s:
        assert usage.limit_pct(s) == 50
        assert usage.limits(50)["class_a"] == 500_000
