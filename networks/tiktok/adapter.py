"""Adaptador TikTok (Task 28.2): Login Kit (OAuth v2) e Content Posting API ("Direct Post").

Fluxo do envio: consulta o criador (privacidades permitidas e duração máxima) → inicia o post
com o tamanho do arquivo → envia o arquivo para a `upload_url` → o TikTok processa de forma
assíncrona. O Postador consulta `status` até `PUBLISH_COMPLETE` ou `FAILED`.

O access token dura 24 h e o refresh token 365 dias, e o refresh token pode mudar a cada
renovação: por isso `fresh_credentials` devolve o JSON novo, que o Postador grava.

Sem a auditoria do app no TikTok, só a privacidade SELF_ONLY é aceita.
"""

import json
import os
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
    Uncertain,
)

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
API = "https://open.tiktokapis.com/v2"
TOKEN_URL = f"{API}/oauth/token/"
SCOPES = ("user.info.basic", "video.publish", "video.list")
MAX_SINGLE_CHUNK = 64 * 1024 * 1024
CHUNK = 10 * 1024 * 1024
RATE_CODES = {"rate_limit_exceeded", "spam_risk_too_many_posts", "spam_risk_too_many_pending_share"}
AUTH_CODES = {"access_token_invalid", "scope_not_authorized", "invalid_grant", "token_expired"}
CAPTION_MAX = 2200


def caption_of(request: PublishRequest) -> str:
    """No TikTok o "title" do post é a legenda inteira: título + descrição (com hashtags)."""
    text = request.title
    if request.description and request.description.strip() != request.title.strip():
        body = request.description.replace(request.title, "", 1).strip()
        text = f"{request.title}\n\n{body}" if body else request.title
    return text[:CAPTION_MAX]


def chunks_for(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) pelas regras da API (até 64 MB vai num pedaço só)."""
    if size <= MAX_SINGLE_CHUNK:
        return size, 1
    return CHUNK, size // CHUNK  # o último pedaço leva o resto


class TikTokAdapter(PlatformAdapter):
    platform = "tiktok"
    capabilities = frozenset({"direct_publish", "async_status"})

    def __init__(
        self,
        client_key: str,
        client_secret: str,
        client_factory: Callable[[], httpx.Client] | None = None,
        now: Callable[[], float] = time.time,
    ):
        self.client_key = client_key
        self.client_secret = client_secret
        self.client_factory = client_factory or (lambda: httpx.Client(timeout=60))
        self.now = now

    # --- OAuth ---------------------------------------------------------------------------

    def authorize_url(self, redirect_uri: str, state: str) -> str:
        return (
            AUTH_URL
            + "?"
            + urlencode(
                {
                    "client_key": self.client_key,
                    "scope": ",".join(SCOPES),
                    "response_type": "code",
                    "redirect_uri": redirect_uri,
                    "state": state,
                }
            )
        )

    def _token(self, data: dict) -> str:
        with self.client_factory() as client:
            try:
                response = client.post(
                    TOKEN_URL,
                    data={
                        "client_key": self.client_key,
                        "client_secret": self.client_secret,
                        **data,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.HTTPError as exc:
                raise TemporaryError(f"Sem resposta do TikTok: {exc}") from exc
        body = response.json() if response.content else {}
        if response.status_code >= 500:
            raise TemporaryError(f"TikTok respondeu {response.status_code}.")
        if response.status_code != 200 or body.get("error") or not body.get("access_token"):
            reason = body.get("error_description") or body.get("error") or response.status_code
            raise AuthError(f"TikTok recusou o token ({reason}).")
        return json.dumps(
            {
                "access_token": body["access_token"],
                "refresh_token": body.get("refresh_token"),
                "open_id": body.get("open_id"),
                "expires_at": int(self.now()) + int(body.get("expires_in", 86400)),
            }
        )

    def exchange_code(self, code: str, redirect_uri: str) -> str:
        return self._token(
            {"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri}
        )

    def fresh_credentials(self, credentials: str) -> str:
        data = self._load(credentials)
        if data.get("expires_at", 0) - 300 > self.now():
            return credentials
        if not data.get("refresh_token"):
            raise AuthError("Conta do TikTok sem refresh token. Conecte de novo.")
        return self._token({"grant_type": "refresh_token", "refresh_token": data["refresh_token"]})

    @staticmethod
    def _load(credentials: str) -> dict:
        try:
            data = json.loads(credentials)
            data["access_token"]  # noqa: B018 - valida a forma
            return data
        except (ValueError, KeyError, TypeError) as exc:
            raise AuthError("Credencial do TikTok ilegível. Conecte de novo.") from exc

    # --- API ------------------------------------------------------------------------------

    def _call(self, client: httpx.Client, credentials: str, method: str, path: str, **kw) -> dict:
        token = self._load(credentials)["access_token"]
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            response = client.request(method, f"{API}{path}", headers=headers, **kw)
        except httpx.HTTPError as exc:
            raise TemporaryError(f"Sem resposta do TikTok: {exc}") from exc
        try:
            body = response.json()
        except ValueError:
            body = {}
        error = body.get("error") or {}
        code = error.get("code", "")
        if response.status_code == 200 and code in ("", "ok"):
            return body.get("data") or {}
        message = error.get("message") or code or response.status_code
        if response.status_code == 401 or code in AUTH_CODES:
            raise AuthError(f"TikTok: acesso negado ({message}).")
        if response.status_code == 429 or code in RATE_CODES:
            raise RateLimited(f"TikTok: limite atingido ({message}).")
        if response.status_code >= 500:
            raise TemporaryError(f"TikTok respondeu {response.status_code}.")
        raise PublishFailed(f"TikTok recusou ({message}).")

    def account_info(self, credentials: str) -> tuple[str, str]:
        with self.client_factory() as client:
            data = self._call(
                client,
                credentials,
                "GET",
                "/user/info/",
                params={"fields": "open_id,display_name,username"},
            )
        user = data.get("user") or {}
        name = user.get("display_name") or user.get("username") or "Conta TikTok"
        return user.get("open_id") or self._load(credentials).get("open_id", ""), name

    def creator_info(self, client: httpx.Client, credentials: str) -> dict:
        return self._call(client, credentials, "POST", "/post/publish/creator_info/query/")

    def publish(self, credentials: str, request: PublishRequest) -> PublishResult:
        size = os.path.getsize(request.file_path)
        chunk_size, total = chunks_for(size)
        with self.client_factory() as client:
            creator = self.creator_info(client, credentials)
            options = creator.get("privacy_level_options") or ["SELF_ONLY"]
            wanted = "PUBLIC_TO_EVERYONE" if request.privacy == "public" else "SELF_ONLY"
            privacy = wanted if wanted in options else options[-1]
            init = self._call(
                client,
                credentials,
                "POST",
                "/post/publish/video/init/",
                json={
                    "post_info": {
                        "title": caption_of(request),
                        "privacy_level": privacy,
                        "disable_comment": False,
                        "disable_duet": False,
                        "disable_stitch": False,
                    },
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": size,
                        "chunk_size": chunk_size,
                        "total_chunk_count": total,
                    },
                },
            )
            publish_id, upload_url = init.get("publish_id"), init.get("upload_url")
            if not publish_id or not upload_url:
                raise TemporaryError("TikTok não devolveu a URL de envio.")
            try:
                with open(request.file_path, "rb") as f:
                    for index in range(total):
                        start = index * chunk_size
                        end = size - 1 if index == total - 1 else start + chunk_size - 1
                        f.seek(start)
                        part = f.read(end - start + 1)
                        done = client.put(
                            upload_url,
                            content=part,
                            headers={
                                "Content-Type": "video/mp4",
                                "Content-Range": f"bytes {start}-{end}/{size}",
                            },
                            timeout=600,
                        )
                        if done.status_code >= 500:
                            raise Uncertain(f"TikTok respondeu {done.status_code} no envio.")
                        if done.status_code >= 400:
                            raise PublishFailed(f"TikTok recusou o arquivo ({done.status_code}).")
            except httpx.HTTPError as exc:
                raise Uncertain(f"Envio ao TikTok interrompido: {exc}") from exc
        return PublishResult(external_id=publish_id, url="", status="processing")

    def status(self, credentials: str, external_id: str) -> PublishResult | None:
        with self.client_factory() as client:
            data = self._call(
                client,
                credentials,
                "POST",
                "/post/publish/status/fetch/",
                json={"publish_id": external_id},
            )
        state = data.get("status", "")
        if state == "FAILED":
            raise PublishFailed(f"TikTok não publicou: {data.get('fail_reason') or 'sem motivo'}.")
        if state != "PUBLISH_COMPLETE":
            return None
        ids = data.get("publicaly_available_post_id") or data.get("publicly_available_post_id")
        post_id = str(ids[0]) if ids else external_id
        open_id = self._load(credentials).get("open_id", "")
        url = f"https://www.tiktok.com/@{open_id}/video/{post_id}" if ids else ""
        return PublishResult(external_id=post_id, url=url, status="published")

    def metrics(self, credentials: str, external_ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        with self.client_factory() as client:
            for start in range(0, len(external_ids), 20):
                data = self._call(
                    client,
                    credentials,
                    "POST",
                    "/video/query/",
                    params={"fields": "id,view_count,like_count,comment_count,share_count"},
                    json={"filters": {"video_ids": external_ids[start : start + 20]}},
                )
                for video in data.get("videos") or []:
                    out[str(video["id"])] = {
                        "views": video.get("view_count", 0),
                        "likes": video.get("like_count", 0),
                        "comments": video.get("comment_count", 0),
                        "shares": video.get("share_count", 0),
                    }
        return out
