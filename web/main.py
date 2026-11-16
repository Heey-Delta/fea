"""Interface da ferramenta (roda na Vercel). Task 1.4, 1.5 e 1.9.

Login: OAuth do GitHub, só para a conta em GITHUB_ALLOWED_ID (ver web/auth.py).
"""

import logging
import secrets
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from core.config import Settings, get_settings
from core.db import sqlalchemy_url
from core.logging import configure_logging
from core.storage import LocalStorage, make_storage
from networks import make_adapter
from web import approval, auth, editing, executions, operations, publishing
from web.common import MENU, NotLoggedIn, render, require_user

BASE_DIR = Path(__file__).parent
log = logging.getLogger("web")

__all__ = ["MENU", "app", "create_app"]


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
    app.state.templates = Jinja2Templates(directory=BASE_DIR / "templates")
    # Os testes trocam este cliente por um que simula o GitHub.
    app.state.http_client_factory = lambda: httpx.Client(timeout=10)
    # A conexão só abre na primeira consulta; pool pequeno para funções serverless.
    engine = create_engine(
        sqlalchemy_url(settings.database_url), pool_pre_ping=True, pool_size=2, max_overflow=2
    )
    app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    app.state.storage = make_storage(settings)
    app.state.adapter_factory = lambda platform: make_adapter(platform, settings)
    # Os testes injetam aqui um cliente HTTP simulado para os conectores.
    app.state.connector_kwargs = {}
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="fea_session",
        max_age=60 * 60 * 12,
        same_site="lax",
        https_only=settings.is_production,
    )
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

    @app.exception_handler(NotLoggedIn)
    def to_login(request: Request, exc: NotLoggedIn) -> Response:
        return RedirectResponse("/login", status_code=303)

    @app.exception_handler(OperationalError)
    def database_down(request: Request, exc: OperationalError) -> Response:
        log.error("banco indisponível", extra={"error": str(exc.orig)})
        return render(request, "database_down.html", status_code=503)

    def callback_url(request: Request) -> str:
        if settings.public_base_url:
            return settings.public_base_url.rstrip("/") + "/auth/github/callback"
        return str(request.url_for("github_callback"))

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request) -> Response:
        if request.session.get("user"):
            return RedirectResponse("/", status_code=303)
        return render(request, "login.html", configured=auth.is_configured(settings))

    @app.get("/auth/github")
    def github_start(request: Request) -> Response:
        if not auth.is_configured(settings):
            return render(request, "login.html", status_code=503, configured=False)
        state = auth.new_state()
        request.session["oauth_state"] = state
        url = auth.authorize_url(settings, callback_url(request), state)
        return RedirectResponse(url, status_code=303)

    @app.get("/auth/github/callback", name="github_callback")
    def github_callback(request: Request, code: str = "", state: str = "") -> Response:
        expected = request.session.pop("oauth_state", None)
        try:
            if not code or not expected or not secrets.compare_digest(state, expected):
                raise auth.AuthError("Login expirado ou inválido. Tente de novo.", 400)
            with app.state.http_client_factory() as client:
                user = auth.fetch_user(settings, code, callback_url(request), client)
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
    def dashboard(request: Request, user: str = Depends(require_user)) -> Response:
        return render(request, "dashboard.html", active="/")

    app.include_router(operations.router)
    app.include_router(executions.router)
    app.include_router(approval.router)
    app.include_router(editing.router)
    app.include_router(publishing.router)

    @app.get("/arquivos/{key:path}")
    def local_file(key: str, user: str = Depends(require_user)) -> Response:
        """Serve arquivos do disco local em desenvolvimento. Com R2, as URLs são assinadas."""
        storage = app.state.storage
        if not isinstance(storage, LocalStorage):
            return Response(status_code=404)
        try:
            path = storage._path(key)
        except ValueError:
            return Response(status_code=404)
        if not path.is_file():
            return Response(status_code=404)
        return FileResponse(path)

    def placeholder(item: dict):
        def view(request: Request, user: str = Depends(require_user)) -> Response:
            return render(request, "placeholder.html", active=item["href"], item=item)

        return view

    built = {"/", "/operacoes", "/aprovacao", "/publicacoes", "/contas"}
    for item in MENU:
        if item["href"] not in built:
            app.add_api_route(
                item["href"], placeholder(item), methods=["GET"], response_class=HTMLResponse
            )

    return app


app = create_app()
