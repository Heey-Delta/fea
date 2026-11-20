"""Páginas públicas (sem login) exigidas pelas plataformas para aprovar os apps.

Google (tela de consentimento), TikTok (Login Kit e Content Posting API) e Meta (Instagram)
pedem a URL da página inicial, da política de privacidade, dos termos de uso e das
instruções de exclusão de dados. Os textos descrevem o que a ferramenta realmente faz.
"""

import shlex
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select

from core.models import Event

router = APIRouter()

PAGES = {
    "sobre": ("Sobre", "legal/about.html"),
    "privacidade": ("Política de privacidade", "legal/privacy.html"),
    "termos": ("Termos de uso", "legal/terms.html"),
    "exclusao-de-dados": ("Exclusão de dados", "legal/deletion.html"),
}
UPDATED = "20/11/2026"


def page(slug: str):
    title, template = PAGES[slug]

    def view(request: Request) -> Response:
        settings = request.app.state.settings
        templates = request.app.state.templates
        return templates.TemplateResponse(
            request,
            template,
            {
                "title": title,
                "operator": settings.operator_name,
                "contact": settings.contact_email,
                "base": (settings.public_base_url or str(request.base_url)).rstrip("/"),
                "updated": UPDATED,
                "pages": PAGES,
                "slug": slug,
            },
        )

    return view


for _slug in PAGES:
    router.add_api_route(f"/{_slug}", page(_slug), methods=["GET"], response_class=HTMLResponse)


def public_urls(base: str) -> dict[str, str]:
    base = base.rstrip("/")
    return {slug: f"{base}/{slug}" for slug in PAGES}


# --- Instalação da VPS com um comando gerado na tela Acessos ------------------------------

INSTALLER = Path(__file__).parent / "static" / "instalar-vps.sh"
VPS_TOKEN_MAX_AGE = 30 * 60


def vps_serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="fea-vps-install")


def _fail(message: str, status: int) -> PlainTextResponse:
    return PlainTextResponse(
        f"echo {shlex.quote(message)} >&2; exit 1\n",
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/vps/instalar/{token}")
def vps_install(request: Request, token: str) -> Response:
    """Instalador com DATABASE_URL e TOKEN_ENCRYPTION_KEY embutidos. Vale uma vez, 30 min."""
    settings = request.app.state.settings
    try:
        data = vps_serializer(settings.secret_key).loads(token, max_age=VPS_TOKEN_MAX_AGE)
    except SignatureExpired:
        return _fail("Comando expirado. Gere outro na tela Acessos.", 410)
    except BadSignature as exc:
        raise HTTPException(status_code=404) from exc
    nonce = str(data.get("n", ""))
    with request.app.state.session_factory() as session:
        used = session.scalar(
            select(Event.id).where(
                Event.entity == "vps_install",
                Event.action == "used",
                Event.detail["nonce"].astext == nonce,
            )
        )
        if used:
            return _fail("Este comando já foi usado. Gere outro na tela Acessos.", 410)
        session.add(Event(entity="vps_install", action="used", detail={"nonce": nonce}))
        session.commit()
    script = INSTALLER.read_text()
    shebang, rest = script.split("\n", 1)
    header = (
        f"export FEA_DATABASE_URL={shlex.quote(settings.direct_database_url)}\n"
        f"export FEA_TOKEN_KEY={shlex.quote(settings.token_encryption_key)}\n"
    )
    return PlainTextResponse(
        f"{shebang}\n{header}{rest}", headers={"Cache-Control": "no-store, private"}
    )
