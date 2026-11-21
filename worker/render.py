"""Editor: tarefa `render` (Tasks 10, 15.5, 17 e 18.5).

Pega um item da fila de pesca, renderiza com o preset congelado na execução (ou com a versão
pedida em "nova versão"), roda o QC e solta na fila de editados: `awaiting_approval`, ou
`approved` direto quando a aprovação automática está ligada. QC impeditivo vai para
`needs_fix`. Cada render é uma versão nova; nunca sobrescreve a anterior.
"""

import logging
import random
import tempfile
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core import activity, masks
from core.config import Settings, get_settings
from core.editor import overlay as ov
from core.editor import preset as pr
from core.editor import qc
from core.editor import render as rd
from core.models import Event, Execution, Item, OperationConfig, Render
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


def claim_group(session: Session, item: Item, count: int) -> list[Item] | None:
    """Junta `count` imagens elegíveis da operação num só Short (a deste item é a principal).

    None quando ainda não há imagens suficientes: o item continua elegível e a tarefa do
    próximo item que chegar tenta de novo. As extras ficam `grouped` até o render terminar.
    """
    others = list(
        session.scalars(
            select(Item)
            .where(
                Item.operation_id == item.operation_id,
                Item.media_type == "image",
                Item.status == "eligible",
                Item.id != item.id,
                Item.original_file.is_not(None),
            )
            .order_by(Item.id)
            .limit(count - 1)
            .with_for_update(skip_locked=True)
        )
    )
    if len(others) < count - 1:
        return None
    for other in others:
        other.status = "grouped"
        other.status_reason = f"agrupado no item {item.id}"
    return others


def release_group(factory: sessionmaker, member_ids: list[int]) -> None:
    """Devolve as imagens extras à pesca quando o render do grupo não deu certo."""
    if not member_ids:
        return
    with factory() as session:
        for item in session.scalars(
            select(Item).where(Item.id.in_(member_ids), Item.status == "grouped")
        ):
            item.status, item.status_reason = "eligible", None
        session.commit()


def fetch(storage: Storage, key: str, tmp: Path, name: str) -> Path:
    path = tmp / name
    storage.get_file(key, path)
    return path


def check_image(path: Path) -> None:
    """Imagem corrompida faria o FFmpeg ficar em laço para sempre: valida antes de renderizar."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError(f"imagem inválida ({path.name})") from exc


def pick_music(preset: dict) -> str | None:
    """Chave da música do vídeo: a fixa (substituir), uma sorteada (aleatória) ou nenhuma."""
    audio = preset["audio"]
    if audio["mode"] == "replace":
        return audio["file_key"]
    if audio["mode"] == "random" and audio["library"]:
        return random.choice(audio["library"])
    return None


def produce(
    storage: Storage,
    preset: dict,
    profile,
    mask_version,
    original: str,
    media_type: str,
    tmp: Path,
    group: list[str] | None = None,
) -> tuple[Path, qc.QCReport]:
    """Baixa os arquivos, monta a camada fixa, renderiza e roda o QC (sem tocar no banco).

    `group`: chaves das imagens extras de um Short com várias imagens (a principal é `original`).
    """
    source = fetch(storage, original, tmp, "original" + Path(original).suffix)
    extras = [
        fetch(storage, key, tmp, f"grupo{i}" + Path(key).suffix)
        for i, key in enumerate(group or [], 1)
    ]
    for path in [source, *extras] if extras else []:
        check_image(path)
    info = rd.analyze(source, media_type)
    mask_path = fetch(storage, mask_version.file_key, tmp, "mask.png") if mask_version else None
    elements = [
        fetch(storage, e["file_key"], tmp, f"el{i}{Path(e['file_key']).suffix}")
        for i, e in enumerate(preset["elements"])
    ]
    audio_key = pick_music(preset)
    music = fetch(storage, audio_key, tmp, "audio" + Path(audio_key).suffix) if audio_key else None
    layer = ov.build_overlay(preset, tmp / "overlay.png", mask_path, elements)
    out = tmp / "render.mp4"
    if extras:
        plan = rd.plan_slideshow(
            preset,
            [source, *extras],
            out,
            overlay=layer.path,
            replacement_audio=music,
            max_duration_s=profile.max_duration_s,
        )
    else:
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
    rd.run(plan, on_progress=lambda p: activity.report_progress(p, f"{p:.0f}% do vídeo"))
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
    return out, report


def run_render(
    factory: sessionmaker,
    item_id: int,
    storage: Storage,
    settings: Settings | None = None,
    payload: dict | None = None,
    attempt: int = 1,
) -> Render | None:
    with factory() as session:
        current = session.get(Item, item_id)
        if current is not None and current.status == "grouped":
            # Já entrou no Short de outra imagem: a tarefa desta imagem não tem o que fazer.
            return None
        item, render, config = start(session, item_id, payload)
        preset = pr.from_config(config)
        profile = profile_of_config(config)
        group_keys: list[str] = []
        member_ids: list[int] = []
        group_count = int(preset["video"].get("group_images") or 0)
        if group_count >= 2 and (item.media_type or "video") == "image":
            members = claim_group(session, item, group_count)
            if members is None:  # ainda faltam imagens: espera as próximas da pesca
                item.status = "eligible"
                session.delete(render)
                session.commit()
                log.info("aguardando imagens para o grupo", extra={"item_id": item_id})
                return None
            group_keys = [m.original_file for m in members]
            member_ids = [m.id for m in members]
        problems = pr.validate(preset) + profile.validate_preset(preset)
        mask_version = None
        if preset["mask"]["mask_id"]:
            mask_version = masks.latest_version(session, int(preset["mask"]["mask_id"]))
            if mask_version is None:
                problems.append("Máscara configurada não existe.")
        render_id, operation_id = render.id, item.operation_id
        media_type, original = item.media_type or "video", item.original_file
        session.commit()

    def give_up(reason: str, qa: dict | None = None) -> Render:
        release_group(factory, member_ids)  # as imagens extras voltam para a pesca
        return fail(factory, render_id, item_id, reason, qa=qa)

    if problems:
        return give_up("; ".join(problems))

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out, report = produce(
                storage, preset, profile, mask_version, original, media_type, tmp, group_keys
            )
            key = render_key(operation_id, item_id, render_id_version(factory, render_id))
            if report.passed:
                storage.put_file(key, out, "video/mp4")
                report.add("arquivo armazenado", storage.exists(key), key)
    except (ValueError, OSError) as exc:
        # Conteúdo ou arquivo ruim: tentar de novo não resolve.
        return give_up(f"arquivo inválido: {exc}")
    except RuntimeError as exc:
        # Erro de processo do FFmpeg: tenta de novo até o limite do preset (Task 17.4).
        if attempt <= int(preset.get("max_retries", 2)):
            release_group(factory, member_ids)
            fail(factory, render_id, item_id, str(exc), qa=None, final=False)
            raise RetryableError(str(exc)) from exc
        return give_up(str(exc))

    if not report.passed:
        return give_up("; ".join(report.errors), report.as_dict())
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
        if approval.get("auto_approve"):
            # "Autorizar tudo": QC ok e não duplicado já basta, sem depender de aprovação manual.
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


def run_test(factory: sessionmaker, job_id: int, payload: dict, storage: Storage) -> dict:
    """Testar preset (Task 15.4): render de amostra, sem item e sem fila de editados.

    Guarda o resultado num evento `preset_test` que a tela da Edição mostra.
    """
    import time

    with factory() as session:
        config = session.get(OperationConfig, payload["config_id"])
        if config is None:
            raise PermanentError("Versão de configuração não encontrada.")
        operation_id, data = config.operation_id, config.config
        preset = pr.from_config(data)
        profile = profile_of_config(data)
        problems = pr.validate(preset) + profile.validate_preset(preset)
        mask_version = None
        if preset["mask"]["mask_id"]:
            mask_version = masks.latest_version(session, int(preset["mask"]["mask_id"]))
            if mask_version is None:
                problems.append("Máscara configurada não existe.")
            else:
                session.expunge(mask_version)
    detail: dict = {"ok": False, "config_id": payload["config_id"], "sample": payload["sample_key"]}
    started = time.monotonic()
    if problems:
        detail["error"] = "; ".join(problems)
    else:
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                out, report = produce(
                    storage,
                    preset,
                    profile,
                    mask_version,
                    payload["sample_key"],
                    payload.get("media_type") or "video",
                    Path(tmpdir),
                )
                detail["qa"] = {**report.as_dict(), "errors": report.errors}
                info = rd.analyze(out, "video") if out.exists() else None
                if report.passed:
                    key = f"operations/{operation_id}/tests/{job_id}.mp4"
                    storage.put_file(key, out, "video/mp4")
                    detail.update(
                        ok=True,
                        output_file=key,
                        size_bytes=out.stat().st_size,
                        duration_s=round(info.duration, 2) if info and info.duration else None,
                    )
                else:
                    detail["error"] = "; ".join(report.errors)
        except (ValueError, OSError, RuntimeError) as exc:
            detail["error"] = str(exc)[:1000]
    detail["elapsed_s"] = round(time.monotonic() - started, 1)
    with factory() as session:
        session.add(
            Event(
                entity="preset_test",
                entity_id=job_id,
                operation_id=operation_id,
                action="finished",
                detail=detail,
            )
        )
        session.commit()
    return detail


@register("render")
def render_job(ctx: JobContext) -> None:
    if (ctx.payload or {}).get("test"):
        run_test(ctx.session_factory, ctx.id, ctx.payload, get_storage())
        return
    run_render(
        ctx.session_factory, ctx.ref_id, get_storage(), get_settings(), ctx.payload, ctx.attempts
    )
