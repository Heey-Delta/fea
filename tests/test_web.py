import httpx

from tests.conftest import fake_github, github_login
from web.main import MENU


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_pages_require_login(client):
    for item in MENU:
        response = client.get(item["href"], follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


def test_login_page_offers_github(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert 'href="/auth/github"' in response.text
    assert "password" not in response.text


def test_github_redirect_has_client_and_state(client):
    response = client.get("/auth/github", follow_redirects=False)
    url = httpx.URL(response.headers["location"])
    assert url.host == "github.com"
    assert url.params["client_id"] == "cliente-teste"
    assert url.params["redirect_uri"].endswith("/auth/github/callback")
    assert len(url.params["state"]) > 20
    assert url.params["allow_signup"] == "false"


def test_allowed_account_logs_in(logged_client):
    response = logged_client.get("/")
    assert response.status_code == 200
    assert "Dashboard" in response.text
    for item in MENU:
        assert f'href="{item["href"]}"' in response.text


def test_other_account_is_refused(client):
    client.app.state.http_client_factory = fake_github(user_id=1, login="intruso")
    response = github_login(client)
    assert response.status_code == 403
    assert "não tem acesso" in response.text
    assert client.get("/", follow_redirects=False).status_code == 303


def test_same_login_name_with_other_id_is_refused(client):
    client.app.state.http_client_factory = fake_github(user_id=999, login="Heey-Delta")
    assert github_login(client).status_code == 403


def test_wrong_state_is_refused(client):
    client.get("/auth/github", follow_redirects=False)
    response = client.get("/auth/github/callback?code=abc&state=forjado")
    assert response.status_code == 400
    assert client.get("/", follow_redirects=False).status_code == 303


def test_callback_without_starting_is_refused(client):
    response = client.get("/auth/github/callback?code=abc&state=qualquer")
    assert response.status_code == 400


def test_state_cannot_be_reused(client):
    start = client.get("/auth/github", follow_redirects=False)
    state = httpx.URL(start.headers["location"]).params["state"]
    assert client.get(f"/auth/github/callback?code=a&state={state}").status_code == 200
    client.post("/logout")
    assert client.get(f"/auth/github/callback?code=a&state={state}").status_code == 400


def test_github_rejecting_code(client):
    client.app.state.http_client_factory = fake_github(token_ok=False)
    assert github_login(client).status_code == 400


def test_login_disabled_when_not_configured(settings):
    from fastapi.testclient import TestClient

    from web.main import create_app

    app = create_app(settings.model_copy(update={"github_client_secret": ""}))
    client = TestClient(app)
    assert "ainda não está configurado" in client.get("/login").text
    assert client.get("/auth/github", follow_redirects=False).status_code == 503


def test_placeholder_pages_name_their_task(logged_client):
    response = logged_client.get("/operacoes")
    assert response.status_code == 200
    assert "Task 4" in response.text


def test_logout_ends_session(logged_client):
    response = logged_client.post("/logout", follow_redirects=False)
    assert response.status_code == 303
    assert logged_client.get("/", follow_redirects=False).status_code == 303


def test_static_htmx_is_served(client):
    response = client.get("/static/htmx.min.js")
    assert response.status_code == 200
    assert "htmx" in response.text[:2000]


def test_vercel_entrypoint_exposes_app():
    import app as entry

    assert entry.app.title == "Ferramenta de Operações"


def test_public_base_url_fixes_callback(settings):
    from fastapi.testclient import TestClient

    from web.main import create_app

    fixed = settings.model_copy(update={"public_base_url": "https://fea-oh-alla.vercel.app/"})
    client = TestClient(create_app(fixed))
    url = httpx.URL(client.get("/auth/github", follow_redirects=False).headers["location"])
    assert url.params["redirect_uri"] == "https://fea-oh-alla.vercel.app/auth/github/callback"
