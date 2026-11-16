"""Conector do Reddit pela API oficial (Task 5.5).

Autenticação de aplicativo (client credentials): só lê dados públicos, sem conta de usuário.
Vídeos hospedados no Reddit (v.redd.it) vêm sem marca d'água do Reddit; o vídeo e o áudio
chegam separados e o FFmpeg junta os dois. A API gratuita é só para uso não comercial.
"""

import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx

from core.config import Settings
from core.connectors.base import (
    Page,
    RawItem,
    SourceError,
    SourceRef,
    request_with_retry,
)
from core.queue import PermanentError

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
SUBREDDIT = re.compile(r"^(?:r/)?([A-Za-z0-9_]{2,21})$")


def subreddit_name(reference: str) -> str:
    match = SUBREDDIT.match(reference.strip().removeprefix("/"))
    if not match:
        raise SourceError(f"Comunidade inválida: {reference!r}. Use o formato r/nome.")
    return match.group(1)


def audio_candidates(fallback_url: str) -> tuple[str, ...]:
    """O Reddit não informa a URL do áudio; ela fica na mesma pasta do vídeo."""
    base = fallback_url.split("?")[0].rsplit("/", 1)[0]
    names = ("DASH_AUDIO_128.mp4", "DASH_AUDIO_64.mp4", "DASH_audio.mp4", "audio")
    return tuple(f"{base}/{name}" for name in names)


def parse_post(data: dict) -> RawItem | None:
    """Converte um post da API. Devolve None para posts sem vídeo nem imagem."""
    if data.get("over_18"):
        return None
    published = (
        datetime.fromtimestamp(data["created_utc"], UTC) if data.get("created_utc") else None
    )
    common = {
        "external_id": data["id"],
        "url": "https://www.reddit.com" + data.get("permalink", ""),
        "author": data.get("author"),
        "published_at": published,
        "text": data.get("title") or "",
    }
    video = ((data.get("secure_media") or data.get("media")) or {}).get("reddit_video")
    if data.get("is_video") and video and video.get("fallback_url"):
        return RawItem(
            **common,
            media_type="video",
            media_url=video["fallback_url"],
            audio_urls=audio_candidates(video["fallback_url"])
            if video.get("has_audio", True)
            else (),
            duration_s=video.get("duration"),
            extra={"width": video.get("width"), "height": video.get("height")},
        )
    url = data.get("url_overridden_by_dest") or data.get("url") or ""
    if data.get("post_hint") == "image" or url.lower().split("?")[0].endswith(IMAGE_EXT):
        return RawItem(**common, media_type="image", media_url=url)
    return None


class RedditConnector:
    supports_search = True

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not settings.reddit_client_id or not settings.reddit_client_secret:
            raise SourceError(
                "Reddit não configurado: preencha REDDIT_CLIENT_ID e REDDIT_CLIENT_SECRET."
            )
        self.settings = settings
        self.client = client or httpx.Client(timeout=30, follow_redirects=True)
        self.sleep = sleep
        self._token: str | None = None
        self._token_expires = 0.0

    @property
    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self.settings.reddit_user_agent}

    def _auth(self) -> str:
        if self._token and time.monotonic() < self._token_expires:
            return self._token
        response = request_with_retry(
            lambda: self.client.post(
                TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(self.settings.reddit_client_id, self.settings.reddit_client_secret),
                headers=self._headers,
            ),
            sleep=self.sleep,
        )
        if response.status_code in (400, 401, 403):
            raise SourceError("Credencial do Reddit inválida.")
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires = time.monotonic() + payload.get("expires_in", 3600) - 60
        return self._token

    def _listing(self, path: str, params: dict) -> Page:
        token = self._auth()
        response = request_with_retry(
            lambda: self.client.get(
                f"{API}{path}",
                params=params,
                headers={**self._headers, "Authorization": f"Bearer {token}"},
            ),
            sleep=self.sleep,
        )
        if response.status_code == 401:
            self._token = None
            raise SourceError("Credencial do Reddit inválida ou expirada.")
        if response.status_code in (403, 404):
            raise SourceError("Comunidade privada, banida ou inexistente.")
        if response.status_code != 200:
            raise SourceError(f"Reddit respondeu {response.status_code}.")
        data = response.json().get("data", {})
        items = [
            item
            for child in data.get("children", [])
            if child.get("kind") == "t3" and (item := parse_post(child.get("data", {})))
        ]
        return Page(items=items, next_cursor=data.get("after"))

    def fetch(self, source: SourceRef, cursor: str | None) -> Page:
        name = subreddit_name(source.reference)
        params = {"limit": 100, "raw_json": 1}
        if cursor:
            params["after"] = cursor
        return self._listing(f"/r/{name}/new", params)

    def search(self, source: SourceRef, tags: list[str], cursor: str | None) -> Page:
        name = subreddit_name(source.reference)
        query = " OR ".join(f'"{t}"' if " " in t else t for t in tags if t.strip())
        if not query:
            return self.fetch(source, cursor)
        params = {"q": query, "restrict_sr": 1, "sort": "new", "limit": 100, "raw_json": 1}
        if cursor:
            params["after"] = cursor
        return self._listing(f"/r/{name}/search", params)

    def _get_file(self, url: str, dest: Path) -> bool:
        response = request_with_retry(
            lambda: self.client.get(url, headers=self._headers), sleep=self.sleep
        )
        if response.status_code != 200:
            return False
        dest.write_bytes(response.content)
        return True

    def download(self, item: RawItem, dest: Path) -> Path:
        """Baixa a mídia. Para vídeo, junta vídeo e áudio num MP4 sem recodificar."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        if item.media_type == "image":
            if not self._get_file(item.media_url, dest):
                raise PermanentError("Imagem indisponível no Reddit.")
            return dest
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "video.mp4"
            if not self._get_file(item.media_url, video):
                raise PermanentError("Vídeo indisponível no Reddit.")
            audio = Path(tmp) / "audio.mp4"
            has_audio = any(self._get_file(url, audio) for url in item.audio_urls)
            if not has_audio:
                shutil.copyfile(video, dest)
                return dest
            merge_audio(video, audio, dest)
        return dest


def merge_audio(video: Path, audio: Path, dest: Path) -> None:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c",
            "copy",
            "-shortest",
            str(dest),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise PermanentError(f"Falha ao juntar vídeo e áudio: {result.stderr.strip()[:300]}")
