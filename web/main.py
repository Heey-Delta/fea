"""Interface da ferramenta (roda na Vercel). Task 1.4, 1.5 e 1.9.

Login: OAuth do GitHub, só para a conta em GITHUB_ALLOWED_ID (ver web/auth.py).
"""

import logging
import secrets
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from core.config import Settings, get_settings
from core.logging import configure_logging
from web import auth

BASE_DIR = Path(__file__).parent
log = logging.getLogger("web")

# Menu lateral (Task 25.1). As telas ainda não construídas mostram a task que as entrega.
MENU = [
    {"label": "Dashboard", "href": "/", "task": "Task 25"},
    {"label": "Operações", "href": "/operacoes", "task": "Task 4"},
    {"label": "Fila", "href": "/fila", "task": "Task 8"},
    {"label": "Aprovação", "href": "/aprovacao", "task": "Task 18"},
    {"label": "Publicações", "href": "/publicacoes", "task": "Task 21"},
    {"label": "Contas", "href": "/contas", "task": "Task 19"},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.check_production()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Ferramenta de Operações",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings
    # Os testes trocam este cliente por um que simula o GitHub.
    app.state.http_client_factory = lambda: httpx.Client(timeout=10)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="fea_session",
        max_age=60 * 60 * 12,
        same_site="lax",
        https_only=settings.is_production,
    )
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=BASE_DIR / "templates")

    def render(request: Request, name: str, status_code: int = 200, **context) -> Response:
        context.setdefault("menu", MENU)
        context.setdefault("user", request.session.get("user"))
        return templates.TemplateResponse(request, name, context, status_code=status_code)

    def callback_url(request: Request) -> str:
        if settings.public_base_url:
            return settings.public_base_url.rstrip("/") + "/auth/github/callback"
        return str(request.url_for("github_callback"))

    def logged_in(request: Request) -> bool:
        return bool(request.session.get("user"))

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request) -> Response:
        if logged_in(request):
            return RedirectResponse("/", status_code=303)
        return render(request, "login.html", configured=auth.is_configured(settings))

    @app.get("/auth/github")
    def github_start(request: Request) -> Response:
        if not auth.is_configured(settings):
            return render(
                request,
                "login.html",
                status_code=503,
                configured=False,
            )
        state = auth.new_state()
        request.session["oauth_state"] = state
        redirect_uri = callback_url(request)
        return RedirectResponse(auth.authorize_url(settings, redirect_uri, state), status_code=303)

    @app.get("/auth/github/callback", name="github_callback")
    def github_callback(request: Request, code: str = "", state: str = "") -> Response:
        expected = request.session.pop("oauth_state", None)
        try:
            if not code or not expected or not secrets.compare_digest(state, expected):
                raise auth.AuthError("Login expirado ou inválido. Tente de novo.", 400)
            redirect_uri = callback_url(request)
            with app.state.http_client_factory() as client:
                user = auth.fetch_user(settings, code, redirect_uri, client)
            auth.check_allowed(settings, user)
        except auth.AuthError as exc:
            return render(
                request,
                "login.html",
                status_code=exc.status,
                configured=auth.is_configured(settings),
                error=str(exc),
            )
        request.session.clear()
        request.session["user"] = user.login
        request.session["github_id"] = user.id
        log.info("login", extra={"github_login": user.login})
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    def logout(request: Request) -> Response:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> Response:
        if not logged_in(request):
            return RedirectResponse("/login", status_code=303)
        return render(request, "dashboard.html", active="/")

    def placeholder(item: dict):
        def view(request: Request) -> Response:
            if not logged_in(request):
                return RedirectResponse("/login", status_code=303)
            return render(request, "placeholder.html", active=item["href"], item=item)

        return view

    for item in MENU[1:]:
        app.add_api_route(
            item["href"], placeholder(item), methods=["GET"], response_class=HTMLResponse
        )

    return app


app = create_app()
