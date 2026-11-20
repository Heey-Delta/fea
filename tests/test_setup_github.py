"""Login com GitHub em um clique: fluxo App Manifest grava as chaves no banco."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import core.models as m
from tests.conftest import ALLOWED_ID
from tests.test_publish import KEY
from tests.test_render_job import factory, pytestmark  # noqa: F401


def github(owner_id=ALLOWED_ID):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/app-manifests/codigo/conversions":
            return httpx.Response(
                201,
                json={
                    "slug": "fea-operacoes",
                    "client_id": "Iv23novo",
                    "client_secret": "segredo-do-app",
                    "owner": {"id": owner_id, "login": "Heey-Delta"},
                },
            )
        if request.url.path == "/login/oauth/access_token":
            assert request.content and b"Iv23novo" in request.content
            return httpx.Response(200, json={"access_token": "gho_x"})
        if request.url.path == "/user":
            return httpx.Response(200, json={"id": ALLOWED_ID, "login": "Heey-Delta"})
        return httpx.Response(404)

    return (lambda: httpx.Client(transport=httpx.MockTransport(handler))), seen


@pytest.fixture
def app_client(settings):
    from web.main import create_app

    def make(owner_id=ALLOWED_ID):
        cfg = settings.model_copy(
            update={
                "github_client_id": "",
                "github_client_secret": "",
                "token_encryption_key": KEY,
                "public_base_url": "https://fea.test",
            }
        )
        app = create_app(cfg)
        factory_, _ = github(owner_id)
        app.state.http_client_factory = factory_
        return TestClient(app)

    return make


def start(client):
    page = client.get("/setup/github")
    assert page.status_code == 200 and "Create GitHub App" in page.text
    action = page.text.split('action="')[1].split('"')[0]
    assert action.startswith("https://github.com/settings/apps/new?state=")
    manifest = json.loads(
        page.text.split('name="manifest" value="')[1].split('"')[0].replace("&#34;", '"')
    )
    assert manifest["callback_urls"] == ["https://fea.test/auth/github/callback"]
    assert manifest["redirect_url"] == "https://fea.test/setup/github/retorno"
    return action.split("state=")[1]


def test_one_click_github_login_setup(app_client, factory):  # noqa: F811
    client = app_client()
    assert "Configurar login com GitHub" in client.get("/login").text
    state = start(client)
    done = client.get(f"/setup/github/retorno?code=codigo&state={state}")
    assert "Login configurado" in done.text and "Entrar com GitHub" in done.text
    with factory() as s:
        row = s.get(m.AppCredential, "github_client_secret")
        assert row and "segredo" not in row.value_encrypted
        assert s.scalars(select(m.Event).where(m.Event.action == "github_app_created")).first()
    # O login usa o app criado e a conta autorizada entra.
    go = client.get("/auth/github", follow_redirects=False)
    assert "client_id=Iv23novo" in go.headers["location"]
    st = httpx.URL(go.headers["location"]).params["state"]
    logged = client.get(f"/auth/github/callback?code=abc&state={st}", follow_redirects=False)
    assert logged.status_code == 303 and logged.headers["location"] == "/"
    # Depois de configurado, o setup se fecha.
    assert client.get("/setup/github", follow_redirects=False).status_code == 303


def test_setup_refuses_app_from_another_account(app_client, factory):  # noqa: F811
    client = app_client(owner_id=999)
    state = start(client)
    done = client.get(f"/setup/github/retorno?code=codigo&state={state}")
    assert "conta autorizada" in done.text
    with factory() as s:
        assert s.get(m.AppCredential, "github_client_id") is None


def test_setup_requires_valid_state(app_client, factory):  # noqa: F811
    client = app_client()
    start(client)
    assert "expirada" in client.get("/setup/github/retorno?code=codigo&state=errado").text
