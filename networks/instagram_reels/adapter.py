"""Adaptador Instagram Reels (Task 28.2): "Instagram API with Instagram Login".

Fluxo do envio: cria um contêiner REELS apontando para a URL pública do vídeo (URL assinada do
R2) → o Instagram baixa e processa de forma assíncrona → quando o contêiner fica `FINISHED`,
publica (`media_publish`). O Postador consulta `status`, que faz a publicação final.

Token de longa duração vale 60 dias e é renovado quando passa da metade (`fresh_credentials`).
A conta precisa ser profissional (Criador ou Empresa).
"""

import json
import time
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
)

AUTH_URL = "https://www.instagram.com/oauth/authorize"
SHORT_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
GRAPH = "https://graph.instagram.com"
VERSION = "v21.0"
SCOPES = ("instagram_business_basic", "instagram_business_content_publish")
CAPTION_MAX = 2200
RATE_CODES = {4, 17, 32, 613, 9004}
AUTH_CODES = {102, 190, 10, 200}
REFRESH_AFTER_S = 30 * 86400


def caption_of(request: PublishRequest) -> str:
    text = request.description or request.title
    if request.title and request.title not in text:
        text = f"{request.title}\n\n{text}"
    return text[:CAPTION_MAX]


class InstagramAdapter(PlatformAdapter):
    platform = "instagram"
    capabilities = frozenset({"direct_publish", "async_status", "needs_public_url"})

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        client_factory: Callable[[], httpx.Client] | None = None,
        now: Callable[[], float] = time.time,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.client_factory = client_factory or (lambda: httpx.Client(timeout=60))
        self.now = now

    # --- OAuth ---------------------------------------------------------------------------

    def authorize_url(self, redirect_uri: str, state: str) -> str:
        return (
            AUTH_URL
            + "?"
            + urlencode(
                {
                    "client_id": self.app_id,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": ",".join(SCOPES),
                    "state": state,
                }
            )
        )

    @staticmethod
    def _raise_for(response: httpx.Response) -> dict:
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code < 300 and "error" not in body:
            return body
        error = body.get("error") or {}
        if isinstance(error, str):
            error = {"message": body.get("error_message") or error}
        code, message = error.get("code"), error.get("message") or response.status_code
        oauth = error.get("type") == "OAuthException"
        if response.status_code == 401 or code in AUTH_CODES or oauth:
            if code in RATE_CODES:
                raise RateLimited(f"Instagram: limite atingido ({message}).")
            raise AuthError(f"Instagram: acesso negado ({message}).")
        if response.status_code == 429 or code in RATE_CODES:
            raise RateLimited(f"Instagram: limite atingido ({message}).")
        if response.status_code >= 500:
            raise TemporaryError(f"Instagram respondeu {response.status_code}.")
        raise PublishFailed(f"Instagram recusou ({message}).")

    def _send(self, client: httpx.Client, method: str, url: str, **kw) -> dict:
        try:
            response = client.request(method, url, **kw)
        except httpx.HTTPError as exc:
            raise TemporaryError(f"Sem resposta do Instagram: {exc}") from exc
        return self._raise_for(response)

    def exchange_code(self, code: str, redirect_uri: str) -> str:
        with self.client_factory() as client:
            short = self._send(
                client,
                "POST",
                SHORT_TOKEN_URL,
                data={
                    "client_id": self.app_id,
                    "client_secret": self.app_secret,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
            )
            if "data" in short:  # formato antigo da resposta
                short = (short["data"] or [{}])[0]
            long = self._send(
                client,
                "GET",
                f"{GRAPH}/access_token",
                params={
                    "grant_type": "ig_exchange_token",
                    "client_secret": self.app_secret,
                    "access_token": short["access_token"],
                },
            )
        return self._credentials(long, str(short.get("user_id", "")))

    def _credentials(self, token: dict, user_id: str) -> str:
        return json.dumps(
            {
                "access_token": token["access_token"],
                "user_id": user_id,
                "issued_at": int(self.now()),
                "expires_at": int(self.now()) + int(token.get("expires_in", 60 * 86400)),
            }
        )

    @staticmethod
    def _load(credentials: str) -> dict:
        try:
            data = json.loads(credentials)
            data["access_token"]  # noqa: B018 - valida a forma
            return data
        except (ValueError, KeyError, TypeError) as exc:
            raise AuthError("Credencial do Instagram ilegível. Conecte de novo.") from exc

    def fresh_credentials(self, credentials: str) -> str:
        data = self._load(credentials)
        if (
            self.now() < data.get("expires_at", 0)
            and self.now() - data.get("issued_at", 0) < REFRESH_AFTER_S
        ):
            return credentials
        with self.client_factory() as client:
            token = self._send(
                client,
                "GET",
                f"{GRAPH}/refresh_access_token",
                params={"grant_type": "ig_refresh_token", "access_token": data["access_token"]},
            )
        return self._credentials(token, data.get("user_id", ""))

    # --- Interface ------------------------------------------------------------------------

    def _api(self, client, credentials: str, method: str, path: str, **params) -> dict:
        token = self._load(credentials)["access_token"]
        return self._send(
            client,
            method,
            f"{GRAPH}/{VERSION}/{path}",
            params={**params, "access_token": token},
        )

    def account_info(self, credentials: str) -> tuple[str, str]:
        with self.client_factory() as client:
            me = self._api(client, credentials, "GET", "me", fields="user_id,username")
        return str(me.get("user_id") or me.get("id")), me.get("username") or "Conta Instagram"

    def _user_id(self, credentials: str) -> str:
        user_id = self._load(credentials).get("user_id")
        if not user_id:
            raise AuthError("Conta do Instagram sem user_id. Conecte de novo.")
        return user_id

    def publish(self, credentials: str, request: PublishRequest) -> PublishResult:
        if not request.file_url or not request.file_url.startswith("https://"):
            raise PublishFailed("O Instagram precisa de uma URL pública do vídeo: configure o R2.")
        with self.client_factory() as client:
            container = self._api(
                client,
                credentials,
                "POST",
                f"{self._user_id(credentials)}/media",
                media_type="REELS",
                video_url=request.file_url,
                caption=caption_of(request),
                share_to_feed="true",
            )
        if not container.get("id"):
            raise TemporaryError("Instagram não devolveu o contêiner.")
        return PublishResult(
            external_id=f"container:{container['id']}", url="", status="processing"
        )

    def status(self, credentials: str, external_id: str) -> PublishResult | None:
        if not external_id.startswith("container:"):
            return None
        container_id = external_id.split(":", 1)[1]
        with self.client_factory() as client:
            state = self._api(client, credentials, "GET", container_id, fields="status_code,status")
            code = state.get("status_code", "")
            if code in ("ERROR", "EXPIRED"):
                reason = state.get("status") or code
                raise PublishFailed(f"Instagram não processou o vídeo: {reason}.")
            if code != "FINISHED":
                return None
            media = self._api(
                client,
                credentials,
                "POST",
                f"{self._user_id(credentials)}/media_publish",
                creation_id=container_id,
            )
            media_id = str(media["id"])
            info = self._api(client, credentials, "GET", media_id, fields="permalink")
        return PublishResult(
            external_id=media_id, url=info.get("permalink", ""), status="published"
        )

    def metrics(self, credentials: str, external_ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        with self.client_factory() as client:
            for media_id in external_ids:
                if media_id.startswith("container:"):
                    continue
                data = self._api(
                    client, credentials, "GET", media_id, fields="like_count,comments_count"
                )
                row = {
                    "likes": data.get("like_count", 0),
                    "comments": data.get("comments_count", 0),
                }
                try:
                    insights = self._api(
                        client, credentials, "GET", f"{media_id}/insights", metric="views"
                    )
                    for metric in insights.get("data") or []:
                        values = metric.get("values") or [{}]
                        row[metric.get("name", "views")] = values[0].get("value", 0)
                except (PublishFailed, TemporaryError):
                    pass  # métrica indisponível para esta conta ou versão
                out[media_id] = row
        return out
