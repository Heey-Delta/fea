"""Interface da ferramenta (roda na Vercel). Task 1.4, 1.5 e 1.9."""

import logging
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from core.config import Settings, get_settings
from core.logging import configure_logging
from core.security import verify_password

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

    def logged_in(request: Request) -> bool:
        return bool(request.session.get("user"))

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request) -> Response:
        if logged_in(request):
            return RedirectResponse("/", status_code=303)
        return render(request, "login.html")

    @app.post("/login")
    def login(request: Request, username: str = Form(...), password: str = Form(...)) -> Response:
        valid = username == settings.app_user and verify_password(
            password, settings.app_password_hash
        )
        if not valid:
            log.warning("login recusado", extra={"username": username})
            return render(
                request, "login.html", status_code=401, error="Usuário ou senha incorretos."
            )
        request.session.clear()
        request.session["user"] = username
        log.info("login", extra={"username": username})
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
