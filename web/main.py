"""Interface da ferramenta (roda na Vercel). Task 1.4, 1.5 e 1.9.

Login: OAuth do GitHub, só para a conta em GITHUB_ALLOWED_ID (ver web/auth.py).
"""

import logging
import secrets
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Form, Request
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

from core import credentials, live, usage
from core import dashboard as dash
from core.config import Settings, get_settings
from core.db import sqlalchemy_url
from core.logging import configure_logging
from core.storage import DynamicStorage, LocalStorage, unwrap
from networks import make_adapter
from web import (
    access,
    approval,
    auth,
    editing,
    executions,
    icons,
    operations,
    public,
    publishing,
    queue_view,
    setup_github,
)
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
    app.state.templates.env.globals.update(icon=icons.icon, icon_sprite=icons.sprite)
    # Os testes trocam este cliente por um que simula o GitHub.
    app.state.http_client_factory = lambda: httpx.Client(timeout=10)
    # A conexão só abre na primeira consulta; pool pequeno para funções serverless.
    engine = create_engine(
        sqlalchemy_url(settings.database_url), pool_pre_ping=True, pool_size=2, max_overflow=2
    )
    app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    app.state.storage = DynamicStorage(settings, app.state.session_factory)
    app.state.adapter_factory = lambda platform, current=None: make_adapter(
        platform, current or settings
    )
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

    @app.exception_handler(usage.QuotaExceeded)
    def quota_exceeded(request: Request, exc: usage.QuotaExceeded) -> Response:
        log.warning("limite do R2", extra={"error": str(exc)})
        if "application/json" in request.headers.get("accept", "") or request.url.path.endswith(
            "upload-url"
        ):
            return JSONResponse({"detail": str(exc)}, status_code=429)
        return render(request, "quota.html", message=str(exc), status_code=429)

    @app.exception_handler(OperationalError)
    def database_down(request: Request, exc: OperationalError) -> Response:
        log.error("banco indisponível", extra={"error": str(exc.orig)})
        return render(request, "database_down.html", status_code=503)

    def login_settings() -> Settings:
        """Settings do login: variável de ambiente ou o app criado pela tela /setup/github."""
        try:
            with app.state.session_factory() as session:
                return credentials.effective(session, settings)
        except Exception:  # noqa: BLE001 - sem banco: só as variáveis de ambiente
            return settings

    app.state.login_settings = login_settings

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
        return render(
            request,
            "login.html",
            configured=auth.is_configured(login_settings()),
            notice=request.session.pop("login_notice", None),
        )

    @app.get("/auth/github")
    def github_start(request: Request) -> Response:
        cfg = login_settings()
        if not auth.is_configured(cfg):
            return render(request, "login.html", status_code=503, configured=False)
        state = auth.new_state()
        request.session["oauth_state"] = state
        url = auth.authorize_url(cfg, callback_url(request), state)
        return RedirectResponse(url, status_code=303)

    @app.get("/auth/github/callback", name="github_callback")
    def github_callback(request: Request, code: str = "", state: str = "") -> Response:
        expected = request.session.pop("oauth_state", None)
        cfg = login_settings()
        try:
            if not code or not expected or not secrets.compare_digest(state, expected):
                raise auth.AuthError("Login expirado ou inválido. Tente de novo.", 400)
            with app.state.http_client_factory() as client:
                user = auth.fetch_user(cfg, code, callback_url(request), client)
            auth.check_allowed(cfg, user)
        except auth.AuthError as exc:
            return render(
                request,
                "login.html",
                status_code=exc.status,
                configured=auth.is_configured(cfg),
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
        try:
            with app.state.session_factory() as session:
                kpis, errors = dash.kpis(session), dash.recent_errors(session)
                active_ops = dash.active_operations(session)
                recent = dash.recent_publications(session)
                pending = [
                    st.service.name for st in credentials.status(session, settings) if not st.ready
                ]
                series = dash.published_by_day(session)
                funnel = dash.pipeline(session)
                health = dash.health(session)
                live_state = live.operations_live(session, [op.id for op in active_ops])
        except OperationalError:
            # Sem banco, o painel abre com o aviso (as outras telas mostram a página de erro).
            log.exception("banco indisponível no dashboard")
            kpis, errors, pending, active_ops, recent = None, [], [], [], []
            series, funnel, health, live_state = [], [], {}, {}
        r2_usage = None
        if kpis is not None:
            try:
                with app.state.session_factory() as session:
                    r2_usage = usage.report(session)
            except Exception:  # noqa: BLE001 - migração 0008 ainda não aplicada
                log.exception("uso do R2 indisponível")
        return render(
            request,
            "dashboard.html",
            active="/",
            kpis=kpis,
            errors=errors,
            pending=pending,
            active_ops=active_ops,
            recent=recent,
            r2_usage=r2_usage,
            link_for=dash.link_for,
            series=series,
            funnel=funnel,
            health=health,
            more=dash.secondary(kpis or []),
            live=live_state,
        )

    @app.post("/uso/limite")
    def usage_limit(
        request: Request, pct: int = Form(...), user: str = Depends(require_user)
    ) -> Response:
        """Percentual da franquia grátis do R2 em que a ferramenta para (10 a 100)."""
        with app.state.session_factory() as session:
            usage.set_setting(session, usage.PCT_KEY, str(max(10, min(100, pct))))
            session.commit()
        return RedirectResponse("/#uso", status_code=303)

    app.include_router(operations.router)
    app.include_router(executions.router)
    app.include_router(approval.router)
    app.include_router(editing.router)
    app.include_router(public.router)
    app.include_router(setup_github.router)
    app.include_router(access.router)
    app.include_router(publishing.router)
    app.include_router(queue_view.router)

    @app.get("/arquivos/{key:path}")
    def local_file(key: str, user: str = Depends(require_user)) -> Response:
        """Serve arquivos do disco local em desenvolvimento. Com R2, as URLs são assinadas."""
        storage = unwrap(app.state.storage)
        if not isinstance(storage, LocalStorage):
            return Response(status_code=404)
        try:
            path = storage._path(key)
        except ValueError:
            return Response(status_code=404)
        if not path.is_file():
            return Response(status_code=404)
        return FileResponse(path)

    return app


app = create_app()
