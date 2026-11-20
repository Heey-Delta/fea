"""Páginas públicas (sem login) exigidas pelas plataformas para aprovar os apps.

Google (tela de consentimento), TikTok (Login Kit e Content Posting API) e Meta (Instagram)
pedem a URL da página inicial, da política de privacidade, dos termos de uso e das
instruções de exclusão de dados. Os textos descrevem o que a ferramenta realmente faz.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

router = APIRouter()

PAGES = {
    "sobre": ("Sobre", "public/about.html"),
    "privacidade": ("Política de privacidade", "public/privacy.html"),
    "termos": ("Termos de uso", "public/terms.html"),
    "exclusao-de-dados": ("Exclusão de dados", "public/deletion.html"),
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
