"""Conector de upload manual (Task 5.4).

Os arquivos ficam em `uploads/{operação}/{fonte}/` no armazenamento. Com R2, o navegador
envia direto para o bucket por URL assinada, sem passar pela Vercel (limite de tamanho por
requisição). O cursor é a última chave já lida.
"""

from datetime import UTC, datetime
from pathlib import Path

from core.connectors.base import Page, RawItem, SourceRef
from core.storage import Storage

VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
PAGE_SIZE = 100


def upload_prefix(operation_id: int, source_id: int) -> str:
    return f"uploads/{operation_id}/{source_id}/"


def media_type(key: str) -> str | None:
    lower = key.lower()
    if lower.endswith(VIDEO_EXT):
        return "video"
    if lower.endswith(IMAGE_EXT):
        return "image"
    return None


class UploadConnector:
    # Upload não pesquisa: as tags valem só como filtro (docs/fluxo-operacao.md).
    supports_search = False

    def __init__(self, storage: Storage, operation_id: int):
        self.storage = storage
        self.operation_id = operation_id

    def fetch(self, source: SourceRef, cursor: str | None) -> Page:
        keys = self.storage.list(upload_prefix(self.operation_id, source.id), after=cursor)
        items = []
        for key in keys[:PAGE_SIZE]:
            kind = media_type(key)
            if kind is None:
                continue
            name = key.rsplit("/", 1)[-1]
            items.append(
                RawItem(
                    external_id=key,
                    url="",
                    author=None,
                    published_at=datetime.now(UTC),
                    media_type=kind,
                    text=Path(name).stem.replace("_", " ").replace("-", " "),
                    media_url=key,
                )
            )
        next_cursor = keys[PAGE_SIZE - 1] if len(keys) > PAGE_SIZE else None
        return Page(items=items, next_cursor=next_cursor)

    def search(self, source: SourceRef, tags: list[str], cursor: str | None) -> Page:
        return self.fetch(source, cursor)

    def download(self, item: RawItem, dest: Path) -> Path:
        self.storage.get_file(item.media_url, dest)
        return dest
