import os

import httpx
import pytest
from fastapi.testclient import TestClient

from core.config import Settings

ALLOWED_ID = 84813286


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="development",
        secret_key="chave-de-teste-com-tamanho-suficiente",
        github_client_id="cliente-teste",
        github_client_secret="segredo-teste",
        github_allowed_id=str(ALLOWED_ID),
        database_url=os.environ.get("TEST_DATABASE_URL", "postgresql://fea:fea@localhost:5432/fea"),
    )


def fake_github(user_id: int = ALLOWED_ID, login: str = "Heey-Delta", token_ok: bool = True):
    """Cliente httpx que responde como o GitHub."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            if not token_ok:
                return httpx.Response(200, json={"error": "bad_verification_code"})
            return httpx.Response(200, json={"access_token": "gho_teste", "token_type": "bearer"})
        if request.url.path == "/user":
            assert request.headers["authorization"] == "Bearer gho_teste"
            return httpx.Response(200, json={"id": user_id, "login": login})
        return httpx.Response(404)

    return lambda: httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def client(settings: Settings) -> TestClient:
    from web.main import create_app

    app = create_app(settings)
    app.state.http_client_factory = fake_github()
    return TestClient(app)


def github_login(client: TestClient) -> httpx.Response:
    start = client.get("/auth/github", follow_redirects=False)
    assert start.status_code == 303
    state = httpx.URL(start.headers["location"]).params["state"]
    return client.get(f"/auth/github/callback?code=abc&state={state}", follow_redirects=False)


@pytest.fixture
def logged_client(client: TestClient) -> TestClient:
    response = github_login(client)
    assert response.status_code == 303 and response.headers["location"] == "/"
    return client
