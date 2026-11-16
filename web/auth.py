"""Login com GitHub OAuth, liberado só para a conta autorizada (GITHUB_ALLOWED_ID).

Fluxo: /auth/github → GitHub → /auth/github/callback → confere o state, troca o código
por um token, lê o usuário e compara o ID com o autorizado. O token do GitHub não é guardado.
"""

import logging
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from core.config import Settings

log = logging.getLogger("web.auth")

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"


class AuthError(Exception):
    """Falha no login. `status` é o código HTTP a devolver."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class GitHubUser:
    id: int
    login: str


def is_configured(settings: Settings) -> bool:
    return bool(
        settings.github_client_id and settings.github_client_secret and settings.github_allowed_id
    )


def new_state() -> str:
    return secrets.token_urlsafe(32)


def authorize_url(settings: Settings, redirect_uri: str, state: str) -> str:
    query = {
        "client_id": settings.github_client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "allow_signup": "false",
        # Sem escopo: o token só lê o perfil público, que basta para saber quem é.
        "scope": "",
    }
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


def fetch_user(
    settings: Settings, code: str, redirect_uri: str, client: httpx.Client
) -> GitHubUser:
    response = client.post(
        TOKEN_URL,
        data={
            "client_id": settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        headers={"Accept": "application/json"},
    )
    payload = response.json() if response.status_code == 200 else {}
    token = payload.get("access_token")
    if not token:
        log.warning("github recusou o código", extra={"error": payload.get("error")})
        raise AuthError("O GitHub não confirmou o login. Tente de novo.", 400)

    response = client.get(
        USER_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    if response.status_code != 200:
        raise AuthError("Não foi possível ler o usuário do GitHub.", 502)
    data = response.json()
    return GitHubUser(id=int(data["id"]), login=str(data["login"]))


def check_allowed(settings: Settings, user: GitHubUser) -> None:
    if str(user.id) != str(settings.github_allowed_id).strip():
        log.warning("login negado", extra={"github_login": user.login, "github_id": user.id})
        raise AuthError("Esta conta do GitHub não tem acesso à ferramenta.", 403)
