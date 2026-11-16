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


def test_wrong_password_is_rejected(client):
    response = client.post("/login", data={"username": "admin", "password": "errada"})
    assert response.status_code == 401
    assert "Usuário ou senha incorretos." in response.text
    assert client.get("/", follow_redirects=False).status_code == 303


def test_wrong_user_is_rejected(client):
    from tests.conftest import TEST_PASSWORD

    response = client.post("/login", data={"username": "outro", "password": TEST_PASSWORD})
    assert response.status_code == 401


def test_login_shows_dashboard_and_menu(logged_client):
    response = logged_client.get("/")
    assert response.status_code == 200
    assert "Dashboard" in response.text
    for item in MENU:
        assert f'href="{item["href"]}"' in response.text


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
