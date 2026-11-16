"""Buscador: tarefa `collect` de uma execução (Tasks 6.3 a 6.5 e Task 7).

Para cada fonte da execução, pagina os posts (busca por tags quando a rede permite) e aplica
as regras do mais barato ao mais caro: já visto → texto (bloqueio, nicho, score) → mídia pelos
metadados → permissão → download → arquivo válido → sha256 e pHash → duplicado. Os elegíveis
vão para o armazenamento e, ao fim, os selecionados viram tarefas `render` do Editor.

Critérios:
- recent: para ao chegar a X elegíveis, ao estourar o orçamento ou ao esgotar as fontes;
- heat: examina até min(orçamento, 3 × X) e seleciona os X de maior score; o resto fica
  elegível com o motivo "reserva".
"""

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from core import executions, fishing, queue, watermark
from core.config import Settings, get_settings
from core.connectors import RawItem, SourceRef, make_connector
from core.connectors.base import SourceError
from core.models import Event, Execution, Item, Source
from core.queue import RetryableError
from core.storage import Storage, get_storage
from worker.handlers import register
from worker.runner import JobContext

log = logging.getLogger("worker.buscador")

EXTENSIONS = {"video": ".mp4", "image": ".jpg"}


@dataclass
class Progress:
    examined: int = 0
    already_seen: int = 0
    eligible: list[tuple[int, int]] = field(default_factory=list)  # (item_id, score)
    stop_reason: str = "fontes esgotadas"


def original_key(operation_id: int, item_id: int, media_type: str) -> str:
    return f"operations/{operation_id}/items/{item_id}/original{EXTENSIONS[media_type]}"


def claim_item(session: Session, ex: Execution, source: Source, raw: RawItem) -> int | None:
    """Cria o item. None se o post já foi visto antes nesta fonte (dedup 7.3.1)."""
    stmt = (
        pg_insert(Item)
        .values(
            operation_id=ex.operation_id,
            execution_id=ex.id,
            source_id=source.id,
            external_id=raw.external_id,
            url=raw.url or None,
            author=raw.author,
            media_type=raw.media_type,
            text=raw.text,
            duration_s=raw.duration_s,
            priority=ex.priority,
            status="discovered",
        )
        .on_conflict_do_nothing(index_elements=["source_id", "external_id"])
        .returning(Item.id)
    )
    return session.execute(stmt).scalar()


def set_status(session: Session, item_id: int, status: str, reason: str | None = None, **values):
    item = session.get(Item, item_id)
    item.status = status
    item.status_reason = reason
    for key, value in values.items():
        setattr(item, key, value)


def process_raw(
    factory: sessionmaker,
    ex: Execution,
    source: Source,
    raw: RawItem,
    rules: dict,
    connector,
    storage: Storage,
) -> tuple[int | None, str]:
    """Aplica as regras a um post. Devolve (item_id, estado final)."""
    with factory() as session:
        item_id = claim_item(session, ex, source, raw)
        if item_id is None:
            session.commit()
            return None, "already_seen"
        text = fishing.classify_text(
            raw.text,
            rules.get("tags") or [],
            rules.get("heat_tags") or [],
            rules.get("blocked_words") or [],
        )
        reason = text.reject_reason or fishing.check_media(
            raw.media_type,
            raw.duration_s,
            rules.get("accepted_media") or [],
            rules.get("max_duration_s"),
        )
        if reason:
            set_status(session, item_id, "rejected", reason, score=text.score)
            session.commit()
            return item_id, "rejected"
        if not source.permission_note:
            # Sem permissão registrada: nem baixa (REQ-UI-004). Liberado depois, na fila.
            set_status(
                session, item_id, "pending_permission", "fonte sem permissão", score=text.score
            )
            # Guarda o post para baixar depois, se a permissão for liberada na fila (Task 8).
            session.add(
                Event(
                    entity="item",
                    entity_id=item_id,
                    operation_id=ex.operation_id,
                    action="pending_permission",
                    detail={"raw": raw_to_dict(raw)},
                )
            )
            session.commit()
            return item_id, "pending_permission"
        session.commit()
    return fetch_and_check(
        factory, ex.operation_id, item_id, raw, rules, connector, storage, text.score
    )


def raw_to_dict(raw: RawItem) -> dict:
    data = asdict(raw)
    data["published_at"] = raw.published_at.isoformat() if raw.published_at else None
    data["audio_urls"] = list(raw.audio_urls)
    return data


def raw_from_dict(data: dict) -> RawItem:
    data = dict(data)
    if data.get("published_at"):
        data["published_at"] = datetime.fromisoformat(data["published_at"])
    data["audio_urls"] = tuple(data.get("audio_urls") or ())
    return RawItem(**data)


def fetch_and_check(
    factory: sessionmaker,
    operation_id: int,
    item_id: int,
    raw: RawItem,
    rules: dict,
    connector,
    storage: Storage,
    score: int,
) -> tuple[int | None, str]:
    """Baixa, valida, confere marca d'água e duplicidade e guarda o original."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"original{EXTENSIONS[raw.media_type]}"
        try:
            connector.download(raw, path)
            if raw.media_type == "video":
                duration = fishing.video_duration(path)
                reason = fishing.check_media("video", duration, [], rules.get("max_duration_s"))
            else:
                fishing.image_phash(path)  # abre a imagem: arquivo corrompido falha aqui
                duration, reason = None, None
            sha256 = fishing.sha256_file(path)
            phash = fishing.media_phash(path, raw.media_type, duration)
            if not reason and rules.get("reject_watermarks", True):
                reason = watermark.detect(path, raw.media_type, duration)
        except RetryableError as exc:
            # Falha de rede: apaga o item para o post ser tentado de novo numa próxima busca.
            with factory() as session:
                session.delete(session.get(Item, item_id))
                session.commit()
            log.warning("download falhou, post fica para depois", extra={"error": str(exc)})
            return None, "retry_later"
        except Exception as exc:  # noqa: BLE001 - arquivo corrompido, vídeo removido etc.
            with factory() as session:
                set_status(session, item_id, "rejected", f"arquivo inválido: {exc}"[:500])
                session.commit()
            return item_id, "rejected"

        with factory() as session:
            if reason:
                set_status(session, item_id, "rejected", reason, duration_s=duration)
                session.commit()
                return item_id, "rejected"
            duplicate = fishing.find_duplicate(session, sha256, phash, exclude_item_id=item_id)
            if duplicate:
                original_id, why = duplicate
                set_status(
                    session,
                    item_id,
                    "duplicate",
                    why,
                    duplicate_of=original_id,
                    sha256=sha256,
                    phash=phash,
                )
                session.commit()
                return item_id, "duplicate"
            key = original_key(operation_id, item_id, raw.media_type)
            storage.put_file(key, path)
            set_status(
                session,
                item_id,
                "eligible",
                None,
                score=score,
                sha256=sha256,
                phash=phash,
                original_file=key,
                duration_s=duration,
            )
            session.commit()
            return item_id, "eligible"


def run_collect(
    factory: sessionmaker,
    execution_id: int,
    settings: Settings,
    storage: Storage,
    connector_kwargs: dict | None = None,
) -> Progress:
    with factory() as session:
        ex = session.get(Execution, execution_id)
        if ex is None or ex.status in executions.FINISHED:
            return Progress(stop_reason="execução encerrada")
        rules = executions.fishing_config(executions.config_of(session, ex))
        query = select(Source).where(Source.operation_id == ex.operation_id, Source.status == "ok")
        if ex.source_ids:
            query = query.where(Source.id.in_(ex.source_ids))
        sources = list(session.scalars(query.order_by(Source.id)))
        session.expunge_all()

    target = ex.target_x
    limit = ex.search_budget if ex.criteria == "recent" else min(ex.search_budget, 3 * target)
    tags = (rules.get("tags") or []) + (rules.get("heat_tags") or [])
    progress = Progress()

    def done() -> bool:
        if progress.examined >= limit:
            progress.stop_reason = f"orçamento de {limit} itens esgotado"
            return True
        return ex.criteria == "recent" and len(progress.eligible) >= target

    for source in sources:
        if done():
            break
        try:
            connector = make_connector(
                source.type, settings, storage, ex.operation_id, **(connector_kwargs or {})
            )
        except SourceError as exc:
            mark_source_error(factory, source.id, str(exc))
            continue
        ref = SourceRef(source.id, source.type, source.reference)
        cursor = None
        while not done():
            try:
                if tags and connector.supports_search:
                    page = connector.search(ref, tags, cursor)
                else:
                    page = connector.fetch(ref, cursor)
            except SourceError as exc:
                mark_source_error(factory, source.id, str(exc))
                break
            for raw in page.items:
                if done() or cancelled(factory, execution_id):
                    break
                progress.examined += 1
                item_id, status = process_raw(factory, ex, source, raw, rules, connector, storage)
                if status == "already_seen":
                    progress.already_seen += 1
                elif status == "eligible":
                    score = fishing.classify_text(
                        raw.text, rules.get("tags") or [], rules.get("heat_tags") or [], []
                    ).score
                    progress.eligible.append((item_id, score))
            if not page.next_cursor or cancelled(factory, execution_id):
                break
            cursor = page.next_cursor

    finish_collect(factory, execution_id, progress)
    return progress


def cancelled(factory: sessionmaker, execution_id: int) -> bool:
    with factory() as session:
        return session.get(Execution, execution_id).status == "cancelled"


def mark_source_error(factory: sessionmaker, source_id: int, message: str) -> None:
    """A fonte vai para erro e a execução segue com as outras (Task 5.7)."""
    with factory() as session:
        source = session.get(Source, source_id)
        source.status = "error"
        source.last_error = message
        session.commit()
    log.warning("fonte com erro", extra={"source_id": source_id, "error": message})


def finish_collect(factory: sessionmaker, execution_id: int, progress: Progress) -> None:
    with factory() as session:
        ex = session.get(Execution, execution_id)
        ranked = sorted(progress.eligible, key=lambda pair: (-pair[1], pair[0]))
        if ex.criteria == "heat":
            selected, reserve = ranked[: ex.target_x], ranked[ex.target_x :]
        else:
            selected, reserve = progress.eligible[: ex.target_x], progress.eligible[ex.target_x :]
        for item_id, _ in reserve:
            session.get(Item, item_id).status_reason = "reserva"
        if ex.status != "cancelled":
            for item_id, _ in selected:
                queue.enqueue(
                    session,
                    "render",
                    f"render:{item_id}:{ex.config_id}",
                    ref_id=item_id,
                    operation_id=ex.operation_id,
                    execution_id=ex.id,
                    priority=ex.priority,
                )
        ex.stats = {"examined": progress.examined, "already_seen": progress.already_seen}
        executions.finish(session, ex, len(selected), progress.stop_reason)
        session.commit()


def run_release(
    factory: sessionmaker,
    item_id: int,
    settings: Settings,
    storage: Storage,
    connector_kwargs: dict | None = None,
) -> str:
    """Permissão liberada na fila: baixa o post guardado e segue a pesca (Task 8)."""
    with factory() as session:
        item = session.get(Item, item_id)
        if item is None or item.status != "discovered":
            return "ignorado"
        source = session.get(Source, item.source_id)
        event = session.scalar(
            select(Event)
            .where(
                Event.entity == "item",
                Event.entity_id == item_id,
                Event.action == "pending_permission",
            )
            .order_by(Event.id.desc())
            .limit(1)
        )
        ex = session.get(Execution, item.execution_id) if item.execution_id else None
        if event is None or ex is None or not source.permission_note:
            set_status(session, item_id, "pending_permission", "post sem dados para baixar")
            session.commit()
            return "pending_permission"
        raw = raw_from_dict(event.detail["raw"])
        rules = executions.fishing_config(executions.config_of(session, ex))
        operation_id, config_id, priority, score = (
            ex.operation_id,
            ex.config_id,
            item.priority,
            item.score,
        )
        source_type, execution_id = source.type, ex.id
        session.commit()
    connector = make_connector(
        source_type, settings, storage, operation_id, **(connector_kwargs or {})
    )
    _, status = fetch_and_check(
        factory, operation_id, item_id, raw, rules, connector, storage, score
    )
    if status == "eligible":
        with factory() as session:
            queue.enqueue(
                session,
                "render",
                f"render:{item_id}:{config_id}",
                ref_id=item_id,
                operation_id=operation_id,
                execution_id=execution_id,
                priority=priority,
            )
            session.commit()
    return status


@register("collect")
def collect(ctx: JobContext) -> None:
    if (ctx.payload or {}).get("release_item"):
        run_release(ctx.session_factory, ctx.payload["release_item"], get_settings(), get_storage())
        return
    run_collect(ctx.session_factory, ctx.ref_id, get_settings(), get_storage())
