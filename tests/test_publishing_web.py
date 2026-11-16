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
    app.state.adapter_factory = lambda platform: GoogleFake()
    c = TestClient(app)
    github_login(c)
    return c


def test_connect_youtube_account(client, factory):  # noqa: F811
    assert "Conectar canal do YouTube" in client.get("/contas").text
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
    assert "Canal Novo conectado" in ok.text
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
