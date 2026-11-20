"""Conectores de fonte. Um tipo novo de fonte = um conector novo aqui (Task 5.8)."""

from core.config import Settings
from core.connectors.base import Page, RawItem, SourceConnector, SourceError, SourceRef
from core.storage import Storage

SOURCE_TYPES = {
    "drive": "Google Drive",
    "upload": "Upload manual",
    "reddit": "Reddit",
    "x": "X (Twitter)",
}


def make_connector(
    source_type: str, settings: Settings, storage: Storage, operation_id: int, **kwargs
) -> SourceConnector:
    if source_type == "reddit":
        from core.connectors.reddit import RedditConnector

        return RedditConnector(settings, **kwargs)
    if source_type == "x":
        from core.connectors.x import XConnector

        return XConnector(settings, **kwargs)
    if source_type == "drive":
        from core.connectors.drive import DriveConnector

        return DriveConnector(settings, **kwargs)
    if source_type == "upload":
        from core.connectors.upload import UploadConnector

        return UploadConnector(storage, operation_id)
    raise SourceError(f"Tipo de fonte desconhecido: {source_type}")


__all__ = [
    "SOURCE_TYPES",
    "Page",
    "RawItem",
    "SourceConnector",
    "SourceError",
    "SourceRef",
    "make_connector",
]
