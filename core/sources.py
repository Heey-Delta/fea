"""Fontes da operação (Task 5).

Cada bloco Fonte do canvas vira uma linha em `sources`, sincronizada a cada salvamento:
o canvas é onde se configura; a tabela guarda o estado (cursor, erro, última checagem).
Uma fonte cujo bloco saiu do canvas fica pausada, para não perder o histórico dos itens.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.connectors import SOURCE_TYPES, SourceRef, make_connector
from core.connectors.base import SourceError
from core.models import Event, Operation, Source
from core.queue import RetryableError
from core.storage import Storage


def source_nodes(config: dict) -> list[dict]:
    return [n for n in config.get("nodes") or [] if n.get("type") == "source"]


def sync_sources(session: Session, op: Operation, config: dict) -> list[Source]:
    existing = {
        s.node_id: s for s in session.scalars(select(Source).where(Source.operation_id == op.id))
    }
    active: list[Source] = []
    seen: set[str] = set()
    for node in source_nodes(config):
        cfg = node.get("config") or {}
        source_type = cfg.get("type") or "reddit"
        if source_type not in SOURCE_TYPES:
            continue  # a validação do fluxo já aponta o erro
        source = existing.get(node["id"])
        if source is None:
            source = Source(operation_id=op.id, node_id=node["id"], status="ok")
            session.add(source)
        changed_target = (source.type, source.reference) != (source_type, cfg.get("reference", ""))
        source.type = source_type
        source.reference = (cfg.get("reference") or "").strip()
        source.permission_note = (cfg.get("permission_note") or "").strip() or None
        if changed_target:
            source.cursor = None  # outra comunidade: começa do zero
        if source.status == "paused":
            source.status = "ok"
        seen.add(node["id"])
        active.append(source)
    for node_id, source in existing.items():
        if node_id not in seen and source.status != "paused":
            source.status = "paused"
    session.flush()
    return active


@dataclass(frozen=True)
class ConnectionResult:
    ok: bool
    message: str
    sample: int = 0


def test_connection(
    session: Session,
    source: Source,
    settings: Settings,
    storage: Storage,
    **connector_kwargs,
) -> ConnectionResult:
    """Busca uma página da fonte e registra o resultado na própria fonte."""
    now = datetime.now(UTC)
    try:
        connector = make_connector(
            source.type, settings, storage, source.operation_id, **connector_kwargs
        )
        page = connector.fetch(SourceRef(source.id, source.type, source.reference), None)
    except (SourceError, RetryableError) as exc:
        source.status = "error"
        source.last_error = str(exc)
        source.last_checked_at = now
        result = ConnectionResult(False, str(exc))
    else:
        source.status = "ok"
        source.last_error = None
        source.last_checked_at = now
        result = ConnectionResult(
            True, f"Conexão ok: {len(page.items)} itens na primeira página.", len(page.items)
        )
    session.add(
        Event(
            entity="source",
            entity_id=source.id,
            operation_id=source.operation_id,
            action="connection_tested",
            detail={"ok": result.ok, "message": result.message},
        )
    )
    session.flush()
    return result


def list_sources(session: Session, operation_id: int) -> list[Source]:
    return list(
        session.scalars(
            select(Source).where(Source.operation_id == operation_id).order_by(Source.id)
        )
    )
