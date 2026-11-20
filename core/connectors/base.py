"""Interface comum dos conectores de fonte (Task 5.3).

Cada rede (Reddit hoje; X e TikTok no futuro) é um conector com:
- fetch: os itens mais recentes da fonte, paginados por cursor;
- search: itens que batem com as tags, quando a rede permite busca;
- download: baixa a mídia de um item para um arquivo local.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx

from core.queue import PermanentError, RetryableError


class SourceError(PermanentError):
    """A fonte não pode ser usada (credencial inválida, comunidade removida ou privada).

    A fonte vai para status=error e a execução segue com as outras (Task 5.7).
    """


@dataclass(frozen=True)
class RawItem:
    external_id: str
    url: str
    author: str | None
    published_at: datetime | None
    media_type: str  # "video" | "image"
    text: str
    media_url: str
    audio_urls: tuple[str, ...] = ()
    duration_s: float | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Page:
    items: list[RawItem]
    next_cursor: str | None


@dataclass(frozen=True)
class SourceRef:
    """O que o conector precisa saber da fonte."""

    id: int
    type: str
    reference: str


class SourceConnector(Protocol):
    supports_search: bool

    def fetch(self, source: SourceRef, cursor: str | None) -> Page: ...
    def search(self, source: SourceRef, tags: list[str], cursor: str | None) -> Page: ...
    def download(self, item: RawItem, dest: Path) -> Path: ...


def request_with_retry(
    send: Callable[[], httpx.Response],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """Até 3 tentativas com espera crescente para erros temporários (Task 5.6).

    429 e 5xx e falhas de rede são temporários; o resto volta para quem chamou.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            response = send()
        except httpx.TransportError as exc:
            last = exc
        else:
            if response.status_code != 429 and response.status_code < 500:
                return response
            last = RetryableError(f"HTTP {response.status_code}")
        if attempt < attempts - 1:
            sleep(base_delay * 2**attempt)
    raise RetryableError(f"falha temporária após {attempts} tentativas: {last}")
