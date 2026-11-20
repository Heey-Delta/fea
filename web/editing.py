"""Tela da Edição (Tasks 12 e 15): preset por formulário, máscaras, arquivos e Testar preset.

Sem área de edição: o vídeo é definido só pelo preset. Salvar cria uma versão nova da
configuração da operação; a única prévia é o render de amostra do "Testar preset".
"""

import copy
import re
import shutil
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import masks, queue
from core import operations as ops
from core.editor import preset as pr
from core.models import Event, Item, Operation
from networks import PROFILES, profile_of_config
from web.common import db_session, render, require_user

router = APIRouter(dependencies=[Depends(require_user)])

ASSET_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".wav": "audio/wav",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
}
TEXT_SLOTS = 2
ELEMENT_SLOTS = 2


def flash(request: Request, kind: str, text: str) -> None:
    request.session["flash"] = {"kind": kind, "text": text}


def get_op(session: Session, operation_id: int) -> Operation:
    op = session.get(Operation, operation_id)
    if op is None:
        raise HTTPException(status_code=404, detail="Operação não encontrada")
    return op


def num(form, key: str, cast=float, default=None):
    value = form.get(key)
    if value in (None, ""):
        return default
    try:
        return cast(value)
    except ValueError as exc:
        raise ValueError(f"Valor inválido em {key}") from exc


def preset_from_form(form) -> dict:
    """Converte o formulário em preset (porcentagens da tela viram frações)."""
    width, height = (form.get("resolution") or "1080x1920").split("x")
    preset = {
        "video": {
            "width": int(width),
            "height": int(height),
            "fps": num(form, "fps", int, 30),
            "fit": form.get("fit", "blur"),
            "crop_position": form.get("crop_position", "center"),
            "background": form.get("background", "#000000"),
            "blur": num(form, "blur", int, 40),
            "image_duration_s": num(form, "image_duration_s", float, 6),
        },
        "mask": {
            "mask_id": num(form, "mask_id", int),
            "x": num(form, "mask_x", int, 0),
            "y": num(form, "mask_y", int, 0),
            "width_pct": num(form, "mask_width_pct", float, 100),
            "height_pct": num(form, "mask_height_pct", float, 100),
            "scale": num(form, "mask_scale_pct", float, 100) / 100,
            "opacity": num(form, "mask_opacity_pct", float, 100) / 100,
            "align": form.get("mask_align", "center"),
        },
        "texts": [],
        "elements": [],
        "audio": {
            "mode": form.get("audio_mode", "keep"),
            "file_key": form.get("audio_file_key") or None,
            "permission_note": form.get("audio_permission", ""),
            "volume": num(form, "audio_volume_pct", float, 100) / 100,
            "normalize": form.get("audio_normalize") == "on",
            "fade_in_s": num(form, "audio_fade_in", float, 0),
            "fade_out_s": num(form, "audio_fade_out", float, 0),
            "required": form.get("audio_required") == "on",
        },
        "export": {"crf": num(form, "crf", int, 20)},
    }
    for i in range(TEXT_SLOTS):
        content = (form.get(f"t{i}_content") or "").strip()
        if content:
            preset["texts"].append(
                {
                    "content": content,
                    "font": form.get(f"t{i}_font") or "DejaVuSans-Bold",
                    "size": num(form, f"t{i}_size", int, 64),
                    "color": form.get(f"t{i}_color", "#FFFFFF"),
                    "outline": num(form, f"t{i}_outline", int, 4),
                    "outline_color": form.get(f"t{i}_outline_color", "#000000"),
                    "shadow": form.get(f"t{i}_shadow") == "on",
                    "align": form.get(f"t{i}_align", "center"),
                    "position": form.get(f"t{i}_position", "top"),
                    "margin": num(form, f"t{i}_margin", int, 120),
                    "max_lines": num(form, f"t{i}_max_lines", int, 3),
                }
            )
    for i in range(ELEMENT_SLOTS):
        key = (form.get(f"e{i}_file_key") or "").strip()
        if key:
            preset["elements"].append(
                {
                    "file_key": key,
                    "position": form.get(f"e{i}_position", "bottom_right"),
                    "scale": num(form, f"e{i}_scale_pct", float, 20) / 100,
                    "opacity": num(form, f"e{i}_opacity_pct", float, 100) / 100,
                    "margin": num(form, f"e{i}_margin", int, 60),
                }
            )
    return preset


def with_preset(config: dict, preset: dict) -> dict:
    config = copy.deepcopy(config)
    for node in config.get("nodes", []):
        if node.get("type") == "edit":
            node.setdefault("config", {})["preset"] = preset
    return config


def tests_of(session: Session, operation_id: int) -> list[Event]:
    return list(
        session.scalars(
            select(Event)
            .where(Event.operation_id == operation_id, Event.entity == "preset_test")
            .order_by(Event.id.desc())
            .limit(5)
        )
    )


@router.get("/operacoes/{operation_id}/edicao", response_class=HTMLResponse)
def page(request: Request, operation_id: int, session: Session = Depends(db_session)) -> Response:
    op = get_op(session, operation_id)
    config = ops.current_config(session, op)
    storage = request.app.state.storage
    samples = list(
        session.scalars(
            select(Item)
            .where(Item.operation_id == op.id, Item.original_file.is_not(None))
            .order_by(Item.id.desc())
            .limit(20)
        )
    )
    return render(
        request,
        "edit_preset.html",
        active="/operacoes",
        op=op,
        config=config,
        p=pr.from_config(config.config),
        profile=profile_of_config(config.config),
        profiles=PROFILES,
        masks=masks.list_masks(session, op.id),
        samples=samples,
        tests=tests_of(session, op.id),
        url=storage.url,
        text_slots=TEXT_SLOTS,
        element_slots=ELEMENT_SLOTS,
        default_text=pr.DEFAULT_TEXT,
        default_element=pr.DEFAULT_ELEMENT,
        read_only=op.status == "archived",
        flash=request.session.pop("flash", None),
    )


@router.post("/operacoes/{operation_id}/edicao")
async def save(request: Request, operation_id: int, session: Session = Depends(db_session)):
    op = get_op(session, operation_id)
    form = await request.form()
    try:
        preset = preset_from_form(form)
    except ValueError as exc:
        flash(request, "error", str(exc))
        return RedirectResponse(f"/operacoes/{op.id}/edicao", status_code=303)
    config = ops.current_config(session, op).config
    errors = pr.validate(preset) + profile_of_config(config).validate_preset(preset)
    if errors:
        flash(request, "error", "Preset não salvo: " + " ".join(errors))
        return RedirectResponse(f"/operacoes/{op.id}/edicao", status_code=303)
    try:
        version = ops.save_config(session, op, with_preset(config, preset))
        flash(request, "ok", f"Preset salvo na versão v{version.version}.")
    except ops.OperationError as exc:
        flash(request, "error", str(exc))
    return RedirectResponse(f"/operacoes/{op.id}/edicao", status_code=303)


@router.post("/operacoes/{operation_id}/mascaras")
def upload_mask(
    request: Request,
    operation_id: int,
    file: UploadFile = File(...),
    name: str = Form(""),
    mask_id: int | None = Form(None),
    session: Session = Depends(db_session),
):
    op = get_op(session, operation_id)
    output = profile_of_config(ops.current_config(session, op).config).output
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
    wants_json = "application/json" in request.headers.get("accept", "")
    ok, text = False, ""
    try:
        version, check = masks.import_mask(
            session,
            request.app.state.storage,
            op.id,
            Path(tmp.name),
            name=name or Path(file.filename or "mascara").stem,
            mask_id=mask_id,
            output=(output.width, output.height),
        )
        ok, text = True, f"Máscara importada (versão {version.version})."
        if check.warnings:
            text += " Avisos: " + " ".join(check.warnings)
    except masks.MaskError as exc:
        text = f"Máscara recusada: {exc}"
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    if wants_json:
        # Canvas: devolve a lista atualizada para o painel do Motor Editor.
        session.flush()
        return JSONResponse(
            {"ok": ok, "message": text, "masks": mask_list(request, session, op.id)},
            status_code=200 if ok else 422,
        )
    flash(request, "ok" if ok else "error", text)
    return RedirectResponse(f"/operacoes/{op.id}/edicao", status_code=303)


def mask_list(request: Request, session: Session, operation_id: int) -> list[dict]:
    storage = request.app.state.storage
    out = []
    for mask, versions in masks.list_masks(session, operation_id):
        if not versions:
            continue
        latest = versions[0]
        out.append(
            {
                "id": mask.id,
                "name": mask.name,
                "version": latest.version,
                "url": storage.url(latest.file_key),
                "size": f"{latest.width}×{latest.height}",
                "alpha": latest.has_alpha,
            }
        )
    return out


def asset_key(operation_id: int, filename: str) -> str:
    name = Path(filename).name
    ext = Path(name).suffix.lower()
    if ext not in ASSET_TYPES:
        raise HTTPException(status_code=400, detail=f"Formato não aceito: {ext or 'sem extensão'}")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(name).stem).strip("_")[:60] or "arquivo"
    return f"operations/{operation_id}/assets/{int(time.time() * 1000)}_{stem}{ext}"


@router.post("/operacoes/{operation_id}/arquivos/upload-url")
def asset_upload_url(
    request: Request,
    operation_id: int,
    filename: str = Body(..., embed=True),
    session: Session = Depends(db_session),
) -> JSONResponse:
    """Logo, marca d'água, áudio ou vídeo de amostra: direto ao R2 ou pela interface."""
    get_op(session, operation_id)
    key = asset_key(operation_id, filename)
    content_type = ASSET_TYPES[Path(key).suffix]
    url = request.app.state.storage.upload_url(key, content_type)
    if url:
        return JSONResponse(
            {"mode": "direct", "url": url, "key": key, "content_type": content_type}
        )
    return JSONResponse(
        {
            "mode": "local",
            "url": f"/operacoes/{operation_id}/arquivos/upload",
            "key": key,
            "content_type": content_type,
        }
    )


@router.post("/operacoes/{operation_id}/arquivos/upload")
def asset_upload_local(
    request: Request,
    operation_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(db_session),
) -> JSONResponse:
    get_op(session, operation_id)
    storage = request.app.state.storage
    if storage.upload_url("x.png", "image/png"):
        raise HTTPException(status_code=409, detail="Com R2, envie pela URL assinada.")
    key = asset_key(operation_id, file.filename or "")
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
    try:
        storage.put_file(key, Path(tmp.name), ASSET_TYPES[Path(key).suffix])
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    return JSONResponse({"key": key})


@router.post("/operacoes/{operation_id}/edicao/testar")
def test_preset(
    request: Request,
    operation_id: int,
    sample_key: str = Form(...),
    session: Session = Depends(db_session),
):
    """Põe um render de amostra na fila do Editor com o preset salvo (Task 15.4)."""
    op = get_op(session, operation_id)
    if not sample_key.startswith(f"operations/{op.id}/"):
        raise HTTPException(status_code=400, detail="Amostra de outra operação")
    config = ops.current_config(session, op)
    media_type = (
        "image"
        if Path(sample_key).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
        else "video"
    )
    queue.enqueue(
        session,
        "render",
        f"render-test:{op.id}:{time.time_ns()}",
        operation_id=op.id,
        priority="high",
        max_attempts=1,
        payload={
            "test": True,
            "config_id": config.id,
            "sample_key": sample_key,
            "media_type": media_type,
        },
    )
    flash(
        request,
        "ok",
        f"Teste na fila do Editor com o preset v{config.version}. "
        "Atualize a página em alguns segundos.",
    )
    return RedirectResponse(f"/operacoes/{op.id}/edicao#testes", status_code=303)
