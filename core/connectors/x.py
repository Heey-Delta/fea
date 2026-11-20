"""Conector do X (Task 28.1): busca recente da API v2 oficial, com Bearer Token do app.

Referência da fonte: `@usuario` (posts dessa conta) ou um termo de busca do X
(ex.: `#academia lang:pt`). A busca recente cobre os últimos 7 dias e exige plano pago da API.
Só entram posts com vídeo ou imagem; retweets e conteúdo sensível ficam de fora.
"""

import re
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import httpx

from core.config import Settings
from core.connectors.base import Page, RawItem, SourceError, SourceRef, request_with_retry
from core.queue import PermanentError

API = "https://api.x.com/2"
HANDLE = re.compile(r"^@?([A-Za-z0-9_]{1,15})$")


def base_query(reference: str) -> str:
    reference = reference.strip()
    if not reference:
        raise SourceError("Fonte do X sem referência: use @usuario ou um termo de busca.")
    match = HANDLE.match(reference)
    if reference.startswith("@") and match:
        return f"from:{match.group(1)}"
    return f"({reference})"


def build_query(reference: str, tags: list[str]) -> str:
    parts = [base_query(reference)]
    terms = [f'"{t}"' if " " in t else t for t in tags if t.strip()]
    if terms:
        parts.append("(" + " OR ".join(terms) + ")")
    parts += ["(has:videos OR has:images)", "-is:retweet"]
    return " ".join(parts)


def best_video(media: dict) -> str | None:
    variants = [v for v in media.get("variants") or [] if v.get("content_type") == "video/mp4"]
    if not variants:
        return None
    return max(variants, key=lambda v: v.get("bit_rate", 0))["url"]


def parse(payload: dict) -> list[RawItem]:
    includes = payload.get("includes") or {}
    media_by_key = {m["media_key"]: m for m in includes.get("media") or []}
    users = {u["id"]: u.get("username", "") for u in includes.get("users") or []}
    items = []
    for tweet in payload.get("data") or []:
        if tweet.get("possibly_sensitive"):
            continue
        keys = (tweet.get("attachments") or {}).get("media_keys") or []
        media = next((media_by_key[k] for k in keys if k in media_by_key), None)
        if media is None:
            continue
        author = users.get(tweet.get("author_id", ""), "")
        published = tweet.get("created_at")
        common = {
            "external_id": tweet["id"],
            "url": f"https://x.com/{author or 'i'}/status/{tweet['id']}",
            "author": author or None,
            "published_at": datetime.fromisoformat(published.replace("Z", "+00:00"))
            if published
            else None,
            "text": tweet.get("text") or "",
        }
        if media.get("type") in ("video", "animated_gif"):
            url = best_video(media)
            if not url:
                continue
            duration = media.get("duration_ms")
            items.append(
                RawItem(
                    **common,
                    media_type="video",
                    media_url=url,
                    duration_s=duration / 1000 if duration else None,
                    extra={"width": media.get("width"), "height": media.get("height")},
                )
            )
        elif media.get("type") == "photo" and media.get("url"):
            items.append(RawItem(**common, media_type="image", media_url=media["url"]))
    return items


class XConnector:
    supports_search = True

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not settings.x_bearer_token:
            raise SourceError("X não configurado: preencha o Bearer Token na tela Acessos.")
        self.token = settings.x_bearer_token
        self.client = client or httpx.Client(timeout=30, follow_redirects=True)
        self.sleep = sleep

    def _search(self, query: str, cursor: str | None) -> Page:
        params = {
            "query": query,
            "max_results": 100,
            "expansions": "attachments.media_keys,author_id",
            "media.fields": "type,url,variants,duration_ms,width,height",
            "tweet.fields": "created_at,possibly_sensitive,attachments",
            "user.fields": "username",
        }
        if cursor:
            params["next_token"] = cursor
        response = request_with_retry(
            lambda: self.client.get(
                f"{API}/tweets/search/recent",
                params=params,
                headers={"Authorization": f"Bearer {self.token}"},
            ),
            sleep=self.sleep,
        )
        if response.status_code in (401, 403):
            raise SourceError("Bearer Token do X inválido ou plano sem acesso à busca recente.")
        if response.status_code == 400:
            raise SourceError("Busca do X recusada: confira a referência da fonte.")
        if response.status_code != 200:
            raise SourceError(f"X respondeu {response.status_code}.")
        payload = response.json()
        return Page(items=parse(payload), next_cursor=(payload.get("meta") or {}).get("next_token"))

    def fetch(self, source: SourceRef, cursor: str | None) -> Page:
        return self._search(build_query(source.reference, []), cursor)

    def search(self, source: SourceRef, tags: list[str], cursor: str | None) -> Page:
        return self._search(build_query(source.reference, tags), cursor)

    def download(self, item: RawItem, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        response = request_with_retry(lambda: self.client.get(item.media_url), sleep=self.sleep)
        if response.status_code != 200:
            raise PermanentError("Mídia indisponível no X.")
        dest.write_bytes(response.content)
        return dest
