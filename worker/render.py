"""Editor: tarefa `render` (Tasks 10, 15.5, 17 e 18.5).

Pega um item da fila de pesca, renderiza com o preset congelado na execução (ou com a versão
pedida em "nova versão"), roda o QC e solta na fila de editados: `awaiting_approval`, ou
`approved` direto quando a aprovação automática está ligada. QC impeditivo vai para
`needs_fix`. Cada render é uma versão nova; nunca sobrescreve a anterior.
"""

import logging
import tempfile
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core import masks
from core.config import Settings, get_settings
from core.editor import overlay as ov
from core.editor import preset as pr
from core.editor import qc
from core.editor import render as rd
from core.models import Event, Execution, Item, OperationConfig, Render, Source
from core.operations import linked_account_ids
from core.queue import PermanentError, RetryableError
from core.storage import Storage, get_storage
from networks import profile_of_config
from worker.handlers import register
from worker.runner import JobContext

log = logging.getLogger("worker.editor")

RENDERABLE = ("eligible", "needs_fix", "awaiting_approval", "approved", "rendering")


def render_key(operation_id: int, item_id: int, version: int) -> str:
    return f"operations/{operation_id}/items/{item_id}/renders/{version}.mp4"


def config_for(session: Session, item: Item, payload: dict | None) -> OperationConfig:
    """Snapshot da execução, ou a versão pedida em "nova versão" (payload)."""
    if payload and payload.get("config_id"):
        return session.get(OperationConfig, payload["config_id"])
    ex = session.get(Execution, item.execution_id) if item.execution_id else None
    if ex is None:
        raise PermanentError("Item sem execução nem versão de configuração.")
    return session.get(OperationConfig, ex.config_id)


def start(session: Session, item_id: int, payload: dict | None) -> tuple[Item, Render, dict]:
    item = session.get(Item, item_id, with_for_update=True)
    if item is None or item.status not in RENDERABLE:
        raise PermanentError(f"Item {item_id} não está pronto para editar.")
    if not item.original_file:
        raise PermanentError("Item sem arquivo original.")
    config = config_for(session, item, payload)
    version = (
        session.scalar(select(func.max(Render.version)).where(Render.item_id == item.id)) or 0
    ) + 1
    render = Render(item_id=item.id, version=version, config_id=config.id, status="rendering")
    session.add(render)
    # Novo render invalida a aprovação anterior (REQ-APP-004).
    item.status = "rendering"
    item.status_reason = None
    item.approved_render_id = None
    item.approved_account_ids = None
    item.approved_by = None
    item.approved_at = None
    session.flush()
    return item, render, config.config


def fetch(storage: Storage, key: str, tmp: Path, name: str) -> Path:
    path = tmp / name
    storage.get_file(key, path)
    return path


def run_render(
    factory: sessionmaker,
    item_id: int,
    storage: Storage,
    settings: Settings | None = None,
    payload: dict | None = None,
    attempt: int = 1,
) -> Render:
    with factory() as session:
        item, render, config = start(session, item_id, payload)
        preset = pr.from_config(config)
        profile = profile_of_config(config)
        problems = pr.validate(preset) + profile.validate_preset(preset)
        mask_version = None
        if preset["mask"]["mask_id"]:
            mask_version = masks.latest_version(session, int(preset["mask"]["mask_id"]))
            if mask_version is None:
                problems.append("Máscara configurada não existe.")
        render_id, operation_id = render.id, item.operation_id
        media_type, original = item.media_type or "video", item.original_file
        session.commit()

    if problems:
        return fail(factory, render_id, item_id, "; ".join(problems), qa=None)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = fetch(storage, original, tmp, "original" + Path(original).suffix)
            info = rd.analyze(source, media_type)
            mask_path = (
                fetch(storage, mask_version.file_key, tmp, "mask.png") if mask_version else None
            )
            elements = [
                fetch(storage, e["file_key"], tmp, f"el{i}{Path(e['file_key']).suffix}")
                for i, e in enumerate(preset["elements"])
            ]
            audio_key = preset["audio"]["file_key"]
            music = (
                fetch(storage, audio_key, tmp, "audio" + Path(audio_key).suffix)
                if preset["audio"]["mode"] == "replace" and audio_key
                else None
            )
            layer = ov.build_overlay(preset, tmp / "overlay.png", mask_path, elements)
            out = tmp / "render.mp4"
            plan = rd.plan_render(
                preset,
                source,
                media_type,
                info,
                out,
                overlay=layer.path,
                replacement_audio=music,
                max_duration_s=profile.max_duration_s,
            )
            rd.run(plan)
            report = qc.check_render(
                out,
                preset,
                expected_audio=plan.has_audio,
                audio_required=bool(preset["audio"]["required"]),
                used_mask=layer.used_mask,
                mask_configured=bool(preset["mask"]["mask_id"]),
                max_duration_s=profile.max_duration_s,
                extra_warnings=layer.warnings + plan.warnings,
            )
            key = render_key(operation_id, item_id, render_id_version(factory, render_id))
            if report.passed:
                storage.put_file(key, out, "video/mp4")
                report.add("arquivo armazenado", storage.exists(key), key)
    except (ValueError, OSError) as exc:
        # Conteúdo ou arquivo ruim: tentar de novo não resolve.
        return fail(factory, render_id, item_id, f"arquivo inválido: {exc}", qa=None)
    except RuntimeError as exc:
        # Erro de processo do FFmpeg: tenta de novo até o limite do preset (Task 17.4).
        if attempt <= int(preset.get("max_retries", 2)):
            fail(factory, render_id, item_id, str(exc), qa=None, final=False)
            raise RetryableError(str(exc)) from exc
        return fail(factory, render_id, item_id, str(exc), qa=None)

    if not report.passed:
        return fail(factory, render_id, item_id, "; ".join(report.errors), qa=report.as_dict())
    return succeed(factory, render_id, item_id, key, report, config, mask_version)


def render_id_version(factory: sessionmaker, render_id: int) -> int:
    with factory() as session:
        return session.get(Render, render_id).version


def fail(
    factory: sessionmaker,
    render_id: int,
    item_id: int,
    reason: str,
    qa: dict | None,
    final: bool = True,
) -> Render:
    with factory() as session:
        render = session.get(Render, render_id)
        render.status = "failed"
        render.error = reason[:2000]
        render.qa_result = qa
        item = session.get(Item, item_id)
        item.status = "needs_fix" if final else "eligible"
        item.status_reason = reason[:500]
        session.add(
            Event(
                entity="render",
                entity_id=render_id,
                operation_id=item.operation_id,
                action="failed",
                detail={"reason": reason[:500], "final": final},
            )
        )
        session.commit()
        log.warning("render falhou", extra={"item_id": item_id, "reason": reason[:300]})
        return render


def succeed(
    factory: sessionmaker,
    render_id: int,
    item_id: int,
    key: str,
    report: qc.QCReport,
    config: dict,
    mask_version,
) -> Render:
    from datetime import UTC, datetime

    with factory() as session:
        render = session.get(Render, render_id)
        render.status = "ok"
        render.output_file = key
        render.qa_result = report.as_dict()
        render.mask_version_id = mask_version.id if mask_version else None
        item = session.get(Item, item_id)
        approval = next(
            (n.get("config") or {} for n in config.get("nodes", []) if n.get("type") == "approval"),
            {},
        )
        source = session.get(Source, item.source_id)
        if approval.get("auto_approve") and source and source.permission_note:
            # Aprovação automática (Task 18.5): QC ok, permissão registrada, não duplicado.
            item.status = "approved"
            item.approved_by = "auto"
            item.approved_render_id = render.id
            item.approved_account_ids = linked_account_ids(config) or None
            item.approved_at = datetime.now(UTC)
        else:
            item.status = "awaiting_approval"
        item.status_reason = "; ".join(report.warnings) or None
        session.add(
            Event(
                entity="render",
                entity_id=render_id,
                operation_id=item.operation_id,
                action="rendered",
                detail={"version": render.version, "status": item.status},
            )
        )
        session.commit()
        return render


@register("render")
def render_job(ctx: JobContext) -> None:
    run_render(
        ctx.session_factory, ctx.ref_id, get_storage(), get_settings(), ctx.payload, ctx.attempts
    )
