"""Login com GitHub em um clique (fluxo "App Manifest").

Enquanto o login não está configurado, /setup/github envia ao GitHub a definição de um app de
login (nome, endereço de retorno, sem permissões). O dono da conta autorizada confirma em
"Create GitHub App"; o GitHub volta para /setup/github/retorno com um código, que vira o
Client ID e o Client secret. Eles ficam criptografados no banco (tela Acessos). Só é aceito um
app criado pela conta de GITHUB_ALLOWED_ID; depois de configurado, estas rotas se fecham.
"""

import json
import logging
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from core import credentials
from core.models import Event
from web import auth
from web.common import render

log = logging.getLogger("web.setup")
router = APIRouter()
GITHUB_NEW_APP = "https://github.com/settings/apps/new"
CONVERSION_URL = "https://api.github.com/app-manifests/{code}/conversions"


def base_url(request: Request) -> str:
    return (request.app.state.settings.public_base_url or str(request.base_url)).rstrip("/")


def manifest(base: str) -> dict:
    return {
        "name": f"FEA Operacoes {secrets.token_hex(3)}",
        "url": f"{base}/sobre",
        "callback_urls": [f"{base}/auth/github/callback"],
        "redirect_url": f"{base}/setup/github/retorno",
        "description": "Login da Ferramenta de Operações (só leitura do perfil).",
        "public": False,
        "default_permissions": {},
        "request_oauth_on_install": False,
        "hook_attributes": {"url": f"{base}/health", "active": False},
    }


def prepare_database(request: Request) -> str | None:
    """Aplica as migrações (o banco novo ainda não tem tabelas). Devolve o erro, se houver."""
    from web.access import direct_engine

    try:
        from core.migrate import status, upgrade

        engine = direct_engine(request)
        if not status(engine)["up_to_date"]:
            upgrade(engine)
        return None
    except Exception as exc:  # noqa: BLE001
        log.exception("migração no setup falhou")
        return f"Não foi possível preparar o banco: {str(exc)[:200]}"


@router.get("/setup/github", response_class=HTMLResponse)
def start(request: Request) -> Response:
    settings = request.app.state.settings
    if auth.is_configured(request.app.state.login_settings()):
        return RedirectResponse("/login", status_code=303)
    problems = []
    if not settings.github_allowed_id:
        problems.append("Defina GITHUB_ALLOWED_ID na Vercel.")
    if not settings.token_encryption_key:
        problems.append("Defina TOKEN_ENCRYPTION_KEY na Vercel.")
    if not problems and (error := prepare_database(request)):
        problems.append(error)
    state = secrets.token_urlsafe(24)
    request.session["gh_setup_state"] = state
    base = base_url(request)
    return render(
        request,
        "setup_github.html",
        problems=problems,
        action=f"{GITHUB_NEW_APP}?state={state}",
        manifest=json.dumps(manifest(base)),
        base=base,
    )


@router.get("/setup/github/retorno")
def finish(request: Request, code: str = "", state: str = "") -> Response:
    settings = request.app.state.settings
    expected = request.session.pop("gh_setup_state", None)
    if auth.is_configured(request.app.state.login_settings()):
        return RedirectResponse("/login", status_code=303)
    if not code or not expected or not secrets.compare_digest(state, expected):
        request.session["login_notice"] = "Configuração expirada. Tente de novo."
        return RedirectResponse("/login", status_code=303)
    with request.app.state.http_client_factory() as client:
        response = client.post(
            CONVERSION_URL.format(code=code),
            headers={"Accept": "application/vnd.github+json"},
        )
    if response.status_code not in (200, 201):
        request.session["login_notice"] = (
            f"O GitHub recusou ({response.status_code}). Tente de novo."
        )
        return RedirectResponse("/login", status_code=303)
    data = response.json()
    owner = data.get("owner") or {}
    if str(owner.get("id")) != str(settings.github_allowed_id).strip():
        log.warning("app de login de outra conta", extra={"owner": owner.get("login")})
        request.session["login_notice"] = "O app precisa ser criado pela conta autorizada."
        return RedirectResponse("/login", status_code=303)
    with request.app.state.session_factory() as session:
        credentials.save(
            session,
            settings,
            {"github_client_id": data["client_id"], "github_client_secret": data["client_secret"]},
        )
        session.add(
            Event(
                entity="credential",
                action="github_app_created",
                detail={"app": data.get("slug"), "owner": owner.get("login")},
            )
        )
        session.commit()
    request.session["login_notice"] = "Login configurado. Entre com o GitHub."
    return RedirectResponse("/login", status_code=303)
