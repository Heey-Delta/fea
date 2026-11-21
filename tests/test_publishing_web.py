"""Telas do Postador: Contas (OAuth do Google), Nova publicação e Envios."""

import json
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import core.models as m
from tests.conftest import fake_github, github_login
from tests.test_publish import KEY, FakeAdapter, jobs, make_world
from tests.test_render_job import factory, pytestmark, storage  # noqa: F401


class GoogleFake(FakeAdapter):
    def authorize_url(self, redirect_uri, state):
        from networks.youtube_shorts.adapter import authorize_url

        return authorize_url("gid", redirect_uri, state)

    def exchange_code(self, code, redirect_uri):
        assert code == "codigo" and redirect_uri.endswith("/contas/youtube/retorno")
        return json.dumps({"refresh_token": "novo"})

    def account_info(self, credentials):
        return "UCnovo", "Canal Novo"


@pytest.fixture
def client(settings, storage):  # noqa: F811
    from web.main import create_app

    settings = settings.model_copy(
        update={
            "token_encryption_key": KEY,
            "google_client_id": "gid",
            "google_client_secret": "gs",
            "public_base_url": "https://fea.test",
        }
    )
    app = create_app(settings)
    app.state.storage = storage
    app.state.http_client_factory = fake_github()
    app.state.adapter_factory = lambda platform, current=None: GoogleFake()
    c = TestClient(app)
    github_login(c)
    return c


def test_connect_youtube_account(client, factory):  # noqa: F811
    assert "Conectar conta YouTube" in client.get("/contas").text
    go = client.get("/contas/youtube/conectar", follow_redirects=False)
    q = parse_qs(urlparse(go.headers["location"]).query)
    assert q["redirect_uri"] == ["https://fea.test/contas/youtube/retorno"]
    bad = client.get("/contas/youtube/retorno?code=codigo&state=errado")
    assert "inválido" in bad.text
    client.get("/contas/youtube/conectar", follow_redirects=False)
    state = parse_qs(
        urlparse(
            client.get("/contas/youtube/conectar", follow_redirects=False).headers["location"]
        ).query
    )["state"][0]
    ok = client.get(f"/contas/youtube/retorno?code=codigo&state={state}")
    assert "YouTube: Canal Novo conectada" in ok.text
    with factory() as s:
        account = s.scalars(select(m.Account)).one()
        assert account.token_encrypted and "novo" not in account.token_encrypted
    assert "Canal Novo" in client.get("/contas").text
    client.post(f"/contas/{account.id}/acao", data={"acao": "pause"})
    assert "pausada" in client.get("/contas").text
    saved = client.post(
        f"/contas/{account.id}/config", data={"daily_limit": "5", "timezone": "America/Manaus"}
    )
    assert "limite 5/dia" in saved.text
    assert "Conexão ok" in client.post(f"/contas/{account.id}/testar").text


def test_new_publication_preview_and_create(client, factory, storage, tmp_path):  # noqa: F811
    op_id, items, accounts = make_world(factory, storage, tmp_path, n_items=2)
    page = client.get(f"/publicacoes/nova?op={op_id}")
    assert "Vídeos aprovados sem envio (2)" in page.text
    key = page.text.split('name="request_key" value="')[1].split('"')[0]
    data = {
        "operation_id": op_id,
        "item_ids": items,
        "account_ids": accounts,
        "mode": "rotation",
        "interval_min": "15",
        "first_immediate": "true",
        "request_key": key,
    }
    preview = client.post("/publicacoes/nova", data={**data, "acao": "previa"})
    assert "Prévia" in preview.text and "Canal 0" in preview.text and not jobs(factory)
    created = client.post("/publicacoes/nova", data={**data, "acao": "criar"})
    assert "criado: 2 envios" in created.text
    again = client.post("/publicacoes/nova", data={**data, "acao": "criar"})
    assert "já existia" in again.text and len(jobs(factory)) == 2


def test_jobs_page_and_manual_decision(client, factory, storage, tmp_path):  # noqa: F811
    from tests.test_publish import batch

    op_id, _, accounts = make_world(factory, storage, tmp_path, n_items=1)
    batch(factory, op_id, accounts, first_immediate=True)
    job = jobs(factory)[0]
    with factory() as s:
        s.get(m.PublishJob, job.id).status = "uncertain"
        s.commit()
    page = client.get("/publicacoes?status=uncertain")
    assert "incerto" in page.text and "Tentar de novo" in page.text
    done = client.post(
        f"/publicacoes/{job.id}/decidir",
        data={"decisao": "published", "url": "https://youtube.com/shorts/xyz"},
    )
    assert "publicado" in done.text
    assert jobs(factory)[0].external_id == "xyz"


def test_access_page_saves_keys_and_blocks_connect_without_app(client, factory):  # noqa: F811
    page = client.get("/contas").text
    for name in ("Reddit", "X (Twitter)", "YouTube Shorts", "TikTok", "Instagram Reels"):
        assert name in page
    assert "https://fea.test/contas/tiktok/retorno" in page
    # TikTok sem chaves: não deixa conectar.
    blocked = client.get("/contas/tiktok/conectar")
    assert "Para conectar, preencha antes" in blocked.text
    saved = client.post(
        "/contas/chaves/tiktok",
        data={"tiktok_client_key": "ck1", "tiktok_client_secret": "segredo99"},
    )
    assert "TikTok: 2 campo(s) salvo(s)." in saved.text
    assert "segredo99" not in saved.text and "••••do99" in saved.text
    go = client.get("/contas/tiktok/conectar", follow_redirects=False)
    assert go.status_code == 302
    removed = client.post("/contas/chaves/tiktok/limpar")
    assert "removidas" in removed.text
    with factory() as s:
        assert s.get(m.AppCredential, "tiktok_client_key") is None


def test_edit_title_before_publishing(client, factory, storage, tmp_path):  # noqa: F811
    from tests.test_publish import batch

    op_id, _, accounts = make_world(factory, storage, tmp_path, n_items=1)
    batch(factory, op_id, accounts, first_immediate=True)
    job = jobs(factory)[0]
    page = client.get("/publicacoes")
    assert "Editar título" in page.text
    saved = client.post(
        f"/publicacoes/{job.id}/editar", data={"title": "Meu título", "description": ""}
    )
    assert "título salvo" in saved.text
    job = jobs(factory)[0]
    assert (job.title, job.title_method, job.description) == ("Meu título", "manual", None)
    # No envio, a descrição e as tags são geradas e o título manual fica.
    from tests.test_publish import NOW, FakeAdapter, run_publish

    adapter = FakeAdapter()
    import core.config

    s = core.config.Settings(_env_file=None, token_encryption_key=KEY)
    assert run_publish(factory, storage, s, adapter, job.id, NOW) == "published"
    request = adapter.calls[0][1]
    assert request.title == "Meu título" and request.description.startswith("Meu título")


def test_access_page_shows_database_and_r2(client, factory):  # noqa: F811
    page = client.get("/contas").text
    assert "Cloudflare R2" in page and "Conectado e atualizado" in page
    assert client.get("/static/instalar-vps.sh").status_code == 200


def test_vps_install_command_is_single_use(client, factory, tmp_path):  # noqa: F811
    import re
    import subprocess

    page = client.post("/contas/vps/comando").text
    cmd = re.search(r"bash &lt;\(curl -fsSL (\S+?)\)", page)
    assert cmd, "comando não apareceu"
    url = cmd.group(1).replace("https://fea.test", "")
    script = client.get(url)
    assert script.status_code == 200
    assert "export FEA_DATABASE_URL=" in script.text and "export FEA_TOKEN_KEY=" in script.text
    path = tmp_path / "instalar.sh"
    path.write_text(script.text)
    assert subprocess.run(["bash", "-n", str(path)]).returncode == 0
    again = client.get(url)
    assert again.status_code == 410 and "já foi usado" in again.text
    assert client.get("/vps/instalar/falso").status_code == 404


def test_worker_env_download_for_own_computer(client, factory):  # noqa: F811
    response = client.post("/contas/vps/env")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"].startswith("no-store")
    lines = dict(
        line.split("=", 1) for line in response.text.splitlines() if line and line[0] != "#"
    )
    assert lines["APP_ENV"] == "production"
    assert lines["DATABASE_URL"] and lines["TOKEN_ENCRYPTION_KEY"]


def test_worker_heartbeat_status(factory):  # noqa: F811
    from datetime import UTC, datetime, timedelta

    from core import workers

    now = datetime.now(UTC)
    with factory() as s:
        workers.beat(s, "editor", "vps1", now)
        workers.beat(s, "postador", "vps1", now - timedelta(minutes=10))
        s.commit()
        by_role = {w["role"]: w for w in workers.status(s, now)}
    assert by_role["editor"]["online"] and not by_role["postador"]["online"]
    assert by_role["buscador"]["at"] is None


def test_outdated_workers_are_flagged(client, factory, monkeypatch):  # noqa: F811
    """Worker com commit diferente do site: a tela Acessos manda rodar fea-atualizar."""
    from datetime import UTC, datetime

    from core import workers

    now = datetime.now(UTC)
    with factory() as s:
        workers.beat(s, "buscador", "celular", now, version="aaaaaaa")
        workers.beat(s, "editor", "celular", now, version="bbbbbbb")
        workers.beat(s, "postador", "celular", now)  # código antigo: não informa versão
        s.commit()
        statuses = workers.status(s, now)
    assert workers.outdated(statuses, "bbbbbbb") == ["Buscador"]
    assert workers.outdated(statuses, "") == []  # site sem versão: não acusa nada
    monkeypatch.setattr("web.access.code_version", lambda: "bbbbbbb")
    page = client.get("/contas").text
    assert "Workers com código antigo (Buscador)" in page and "fea-atualizar" in page
    assert "código <code>aaaaaaa</code>" in page


def test_code_version_prefers_env(monkeypatch):
    from core import version

    version.code_version.cache_clear()
    monkeypatch.setenv("FEA_VERSION", "1234567890abcdef")
    assert version.code_version() == "1234567"
    version.code_version.cache_clear()
    monkeypatch.delenv("FEA_VERSION")
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", "")
    assert len(version.code_version()) in (0, 7)  # commit do checkout, se houver Git
    version.code_version.cache_clear()
