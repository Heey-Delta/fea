"""Adaptador YouTube Shorts (Task 20): OAuth, upload resumível e conferência de envios.

Usa a YouTube Data API v3 diretamente com httpx. Cada upload custa cota do projeto no Google
(no máximo 100 por dia, somando todas as operações; quem controla é o Postador). Sem a
auditoria do projeto, a API deixa os vídeos privados, qualquer que seja o `privacy` pedido.
"""

import json
import os
import re
from collections.abc import Callable
from urllib.parse import urlencode

import httpx

from networks.base import (
    AuthError,
    PlatformAdapter,
    PublishFailed,
    PublishRequest,
    PublishResult,
    RateLimited,
    TemporaryError,
    Uncertain,
)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
)
RATE_REASONS = {
    "quotaExceeded",
    "uploadLimitExceeded",
    "rateLimitExceeded",
    "userRateLimitExceeded",
}


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    return (
        AUTH_URL
        + "?"
        + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(SCOPES),
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": state,
            }
        )
    )


def _reason(response: httpx.Response) -> str:
    try:
        errors = response.json().get("error", {})
        if isinstance(errors, str):
            return errors
        return (errors.get("errors") or [{}])[0].get("reason") or errors.get("status", "")
    except ValueError:
        return ""


def _normalize(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", "", text.lower()).split())


class YouTubeAdapter(PlatformAdapter):
    platform = "youtube"
    capabilities = frozenset({"direct_publish", "native_schedule", "check"})

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        client_factory: Callable[[], httpx.Client] | None = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.client_factory = client_factory or (lambda: httpx.Client(timeout=60))

    # --- OAuth ---------------------------------------------------------------------------

    def exchange_code(self, code: str, redirect_uri: str) -> str:
        """Troca o código do retorno do OAuth pelas credenciais (JSON com o refresh token)."""
        with self.client_factory() as client:
            response = client.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        if response.status_code != 200:
            raise AuthError(
                f"Google recusou o código ({_reason(response) or response.status_code})."
            )
        data = response.json()
        if not data.get("refresh_token"):
            raise AuthError(
                "Google não devolveu refresh token. Revogue o acesso e conecte de novo."
            )
        return json.dumps({"refresh_token": data["refresh_token"]})

    def access_token(self, client: httpx.Client, credentials: str) -> str:
        try:
            refresh = json.loads(credentials)["refresh_token"]
        except (ValueError, KeyError) as exc:
            raise AuthError("Credencial da conta ilegível.") from exc
        try:
            response = client.post(
                TOKEN_URL,
                data={
                    "refresh_token": refresh,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                },
            )
        except httpx.HTTPError as exc:
            raise TemporaryError(f"Sem resposta do Google: {exc}") from exc
        if response.status_code in (400, 401):
            raise AuthError(f"Token recusado ({_reason(response) or response.status_code}).")
        if response.status_code != 200:
            raise TemporaryError(f"Google respondeu {response.status_code} ao renovar o token.")
        return response.json()["access_token"]

    def _get(self, client: httpx.Client, token: str, path: str, **params) -> dict:
        try:
            response = client.get(
                f"{API}/{path}", params=params, headers={"Authorization": f"Bearer {token}"}
            )
        except httpx.HTTPError as exc:
            raise TemporaryError(str(exc)) from exc
        self._raise_for(response, uploading=False)
        return response.json()

    @staticmethod
    def _raise_for(response: httpx.Response, uploading: bool) -> None:
        if response.status_code < 300:
            return
        reason = _reason(response)
        if response.status_code == 401:
            raise AuthError(f"Acesso negado ({reason or 401}).")
        if response.status_code in (403, 429) and (
            reason in RATE_REASONS or response.status_code == 429
        ):
            raise RateLimited(f"Limite do YouTube: {reason or response.status_code}.")
        if response.status_code == 403:
            raise AuthError(f"Sem permissão ({reason or 403}).")
        if response.status_code >= 500:
            if uploading:
                raise Uncertain(f"YouTube respondeu {response.status_code} durante o envio.")
            raise TemporaryError(f"YouTube respondeu {response.status_code}.")
        raise PublishFailed(f"YouTube recusou ({response.status_code} {reason}).")

    # --- Interface ------------------------------------------------------------------------

    def account_info(self, credentials: str) -> tuple[str, str]:
        with self.client_factory() as client:
            token = self.access_token(client, credentials)
            data = self._get(client, token, "channels", part="snippet", mine="true")
        items = data.get("items") or []
        if not items:
            raise AuthError("A conta Google não tem canal no YouTube.")
        return items[0]["id"], items[0]["snippet"]["title"]

    def publish(self, credentials: str, request: PublishRequest) -> PublishResult:
        status = {"privacyStatus": request.privacy, "selfDeclaredMadeForKids": False}
        if request.publish_at:
            # Agendamento nativo exige privado até a hora marcada.
            status.update(privacyStatus="private", publishAt=request.publish_at)
        body = {
            "snippet": {
                "title": request.title,
                "description": request.description,
                "tags": request.tags,
                "categoryId": "22",
            },
            "status": status,
        }
        size = os.path.getsize(request.file_path)
        with self.client_factory() as client:
            token = self.access_token(client, credentials)
            try:
                start = client.post(
                    UPLOAD,
                    params={"uploadType": "resumable", "part": "snippet,status"},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Upload-Content-Type": "video/mp4",
                        "X-Upload-Content-Length": str(size),
                    },
                    json=body,
                )
            except httpx.HTTPError as exc:
                raise TemporaryError(f"Sem resposta ao iniciar o envio: {exc}") from exc
            self._raise_for(start, uploading=False)
            location = start.headers.get("Location")
            if not location:
                raise TemporaryError("YouTube não devolveu a URL de envio.")
            try:
                with open(request.file_path, "rb") as f:
                    done = client.put(
                        location,
                        content=f.read(),
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4"},
                        timeout=600,
                    )
            except httpx.HTTPError as exc:
                raise Uncertain(f"Envio interrompido: {exc}") from exc
            self._raise_for(done, uploading=True)
        video = done.json()
        state = "scheduled_platform" if request.publish_at else "published"
        return PublishResult(
            external_id=video["id"], url=f"https://youtube.com/shorts/{video['id']}", status=state
        )

    def check(self, credentials: str, title: str, since_iso: str) -> PublishResult | None:
        """Lista os últimos envios do canal (1 unidade de cota por chamada) e procura o título."""
        with self.client_factory() as client:
            token = self.access_token(client, credentials)
            channel = self._get(client, token, "channels", part="contentDetails", mine="true")
            items = channel.get("items") or []
            if not items:
                return None
            uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
            data = self._get(
                client, token, "playlistItems", part="snippet", playlistId=uploads, maxResults=25
            )
        wanted = _normalize(title)
        for entry in data.get("items") or []:
            snippet = entry["snippet"]
            if (
                _normalize(snippet.get("title", "")) == wanted
                and snippet.get("publishedAt", "") >= since_iso[:19]
            ):
                video_id = snippet["resourceId"]["videoId"]
                return PublishResult(
                    external_id=video_id, url=f"https://youtube.com/shorts/{video_id}"
                )
        return None
