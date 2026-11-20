"""Telas e API das operações (Task 4).

O fluxo (Pesca → Motor Editor → Publicador) salva por POST /operacoes/{id}/config em JSON.
"""

import json
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import credentials
from core import executions as exe
from core import operations as ops
from core import sources as src
from core.connectors import SOURCE_TYPES
from core.connectors.upload import IMAGE_EXT, VIDEO_EXT, upload_prefix
from core.models import Account, Event, Operation, Source
from core.states import OPERATION_STATUS
from networks import PLATFORM_LABEL, PROFILES
from web import editing
from web.common import db_session, render, require_user

router = APIRouter(dependencies=[Depends(require_user)])

STATUS_LABEL = {
    "draft": "Rascunho",
    "active": "Ativa",
    "paused": "Pausada",
    "archived": "Arquivada",
}
TABS = [
    ("geral", "Visão geral"),
    ("config", "Configuração"),
    ("fontes", "Fontes"),
    ("contas", "Contas"),
    ("execucoes", "Execuções"),
    ("historico", "Histórico de versões"),
]
# Ações de estado oferecidas a partir de cada estado.
ACTIONS = {
    "draft": [("active", "Ativar")],
    "active": [("paused", "Pausar")],
    "paused": [("active", "Retomar")],
    "archived": [],
}


def flash(request: Request, kind: str, text: str) -> None:
    request.session["flash"] = {"kind": kind, "text": text}


def get_operation(session: Session, operation_id: int) -> Operation:
    op = session.get(Operation, operation_id)
    if op is None:
        raise HTTPException(status_code=404, detail="Operação não encontrada")
    return op


@router.get("/operacoes", response_class=HTMLResponse)
def list_page(
    request: Request, status: str = "", session: Session = Depends(db_session)
) -> Response:
    status = status if status in OPERATION_STATUS else ""
    return render(
        request,
        "operations_list.html",
        active="/operacoes",
        operations=ops.list_operations(session, status or None),
        counts=ops.status_counts(session),
        status=status,
        status_label=STATUS_LABEL,
        flash=request.session.pop("flash", None),
    )


@router.post("/operacoes")
def create(request: Request, name: str = Form(""), session: Session = Depends(db_session)):
    try:
        op = ops.create_operation(session, name)
    except ops.OperationError as exc:
        flash(request, "error", str(exc))
        return RedirectResponse("/operacoes", status_code=303)
    return RedirectResponse(f"/operacoes/{op.id}/fluxo", status_code=303)


@router.get("/operacoes/{operation_id}", response_class=HTMLResponse)
def detail_page(
    request: Request,
    operation_id: int,
    aba: str = "geral",
    v: int | None = None,
    session: Session = Depends(db_session),
) -> Response:
    op = get_operation(session, operation_id)
    config = ops.current_config(session, op)
    history = ops.versions(session, op)
    shown = next((h for h in history if h.version == v), config)
    issues = ops.validate_graph(config.config)
    return render(
        request,
        "operation_detail.html",
        active="/operacoes",
        op=op,
        config=config,
        shown=shown,
        shown_json=json.dumps(shown.config, ensure_ascii=False, indent=2),
        history=history,
        issues=issues,
        errors=[i for i in issues if i.level == "error"],
        tab=aba if aba in dict(TABS) else "geral",
        tabs=TABS,
        actions=ACTIONS[op.status],
        status_label=STATUS_LABEL,
        node_label=ops.NODE_TYPES,
        sources=src.list_sources(session, op.id),
        executions=exe.list_executions(session, op.id) if aba == "execucoes" else [],
        source_types=SOURCE_TYPES,
        flash=request.session.pop("flash", None),
    )


@router.get("/operacoes/{operation_id}/fluxo", response_class=HTMLResponse)
def canvas_page(
    request: Request, operation_id: int, session: Session = Depends(db_session)
) -> Response:
    op = get_operation(session, operation_id)
    config = ops.current_config(session, op)
    read_only = op.status == "archived"
    settings = credentials.effective(session, request.app.state.settings)
    ready = {st.service.id: st.ready for st in credentials.status(session, settings)}
    boot = {
        "config": config.config,
        "issues": [
            {"level": i.level, "message": i.message, "node_id": i.node_id}
            for i in ops.validate_graph(config.config)
        ],
        "saveUrl": f"/operacoes/{op.id}/config",
        "readOnly": read_only,
        "sourceTypes": SOURCE_TYPES,
        "profiles": [
            {
                "id": p.id,
                "name": p.name,
                "platform": p.platform,
                "maxDuration": p.max_duration_s,
                "resolutions": [list(r) for r in p.allowed_resolutions],
                "fps": list(p.allowed_fps),
                "notes": p.notes,
            }
            for p in PROFILES.values()
        ],
        "platformLabel": PLATFORM_LABEL,
        "accounts": [
            {"id": a.id, "name": a.name, "platform": a.platform, "status": a.status}
            for a in session.scalars(select(Account).order_by(Account.platform, Account.name))
        ],
        "masks": editing.mask_list(request, session, op.id),
        "maskUploadUrl": f"/operacoes/{op.id}/mascaras",
        "presetUrl": f"/operacoes/{op.id}/edicao",
        "assetUploadUrl": f"/operacoes/{op.id}/arquivos/upload-url",
        "ready": ready,
        "op": {"id": op.id, "name": op.name, "status": op.status},
        "statusLabel": STATUS_LABEL,
        "version": config.version,
        "lastModified": config.created_at.isoformat() if config.created_at else None,
        "versions": [
            {"version": v.version, "at": v.created_at.isoformat(), "current": v.id == config.id}
            for v in ops.versions(session, op)[:30]
        ],
        "sourceIds": {
            s.node_id: s.id
            for s in session.scalars(select(Source).where(Source.operation_id == op.id))
        },
        "events": [
            {
                "at": e.at.isoformat(),
                "entity": e.entity,
                "entity_id": e.entity_id,
                "action": e.action,
                "detail": e.detail,
            }
            for e in session.scalars(
                select(Event).where(Event.operation_id == op.id).order_by(Event.id.desc()).limit(60)
            )
        ],
    }
    return render(
        request,
        "operation_canvas.html",
        active="/operacoes",
        op=op,
        config=config,
        boot=boot,
        read_only=read_only,
        status_label=STATUS_LABEL,
        flash=request.session.pop("flash", None),
    )


@router.post("/operacoes/{operation_id}/versoes/{version}/restaurar")
def restore_version(operation_id: int, version: int, session: Session = Depends(db_session)):
    """Recupera uma versão antiga: vira a versão nova (as anteriores nunca mudam)."""
    op = get_operation(session, operation_id)
    old = next((v for v in ops.versions(session, op) if v.version == version), None)
    if old is None:
        raise HTTPException(status_code=404, detail="Versão não encontrada")
    try:
        saved = ops.save_config(session, op, old.config)
    except ops.OperationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    return JSONResponse({"version": saved.version, "restored": version})


@router.post("/operacoes/{operation_id}/renomear")
def rename(
    operation_id: int, name: str = Body(..., embed=True), session: Session = Depends(db_session)
):
    op = get_operation(session, operation_id)
    name = name.strip()[:200]
    if not name:
        return JSONResponse({"error": "Dê um nome à operação."}, status_code=400)
    op.name = name
    session.add(Event(entity="operation", entity_id=op.id, operation_id=op.id, action="renamed"))
    return JSONResponse({"name": op.name})


@router.post("/operacoes/{operation_id}/status")
def change_status(
    request: Request,
    operation_id: int,
    acao: str = Form(...),
    voltar: str = Form(""),
    session: Session = Depends(db_session),
):
    op = get_operation(session, operation_id)
    try:
        ops.change_status(session, op, acao)
        flash(request, "ok", f"Operação agora está {STATUS_LABEL[acao].lower()}.")
    except ops.OperationError as exc:
        flash(request, "error", str(exc))
    target = voltar if voltar.startswith(f"/operacoes/{operation_id}") else ""
    return RedirectResponse(target or f"/operacoes/{operation_id}", status_code=303)


@router.post("/operacoes/{operation_id}/fontes/{source_id}/testar")
def test_source(
    request: Request,
    operation_id: int,
    source_id: int,
    session: Session = Depends(db_session),
):
    source = session.get(Source, source_id)
    if source is None or source.operation_id != operation_id:
        raise HTTPException(status_code=404, detail="Fonte não encontrada")
    state = request.app.state
    settings = credentials.effective(session, state.settings)
    result = src.test_connection(session, source, settings, state.storage, **state.connector_kwargs)
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"ok": result.ok, "message": result.message})
    flash(request, "ok" if result.ok else "error", result.message)
    return RedirectResponse(f"/operacoes/{operation_id}?aba=fontes", status_code=303)


CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def upload_source(session: Session, operation_id: int, source_id: int) -> Source:
    source = session.get(Source, source_id)
    if source is None or source.operation_id != operation_id or source.type != "upload":
        raise HTTPException(status_code=404, detail="Fonte de upload não encontrada")
    return source


def upload_key(operation_id: int, source_id: int, filename: str) -> str:
    """Nome seguro e único: data + nome original limpo. A extensão define o tipo."""
    name = Path(filename).name
    ext = Path(name).suffix.lower()
    if ext not in VIDEO_EXT + IMAGE_EXT:
        raise HTTPException(status_code=400, detail=f"Formato não aceito: {ext or 'sem extensão'}")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(name).stem).strip("_")[:80] or "arquivo"
    return f"{upload_prefix(operation_id, source_id)}{int(time.time() * 1000)}_{stem}{ext}"


@router.post("/operacoes/{operation_id}/fontes/{source_id}/upload-url")
def upload_url(
    request: Request,
    operation_id: int,
    source_id: int,
    filename: str = Body(..., embed=True),
    session: Session = Depends(db_session),
) -> JSONResponse:
    """Com R2: URL assinada para o navegador enviar direto. Sem R2: envio pela interface."""
    upload_source(session, operation_id, source_id)
    key = upload_key(operation_id, source_id, filename)
    content_type = CONTENT_TYPES[Path(key).suffix]
    url = request.app.state.storage.upload_url(key, content_type)
    if url:
        return JSONResponse(
            {"mode": "direct", "url": url, "key": key, "content_type": content_type}
        )
    return JSONResponse(
        {
            "mode": "local",
            "url": f"/operacoes/{operation_id}/fontes/{source_id}/upload",
            "content_type": content_type,
        }
    )


@router.post("/operacoes/{operation_id}/fontes/{source_id}/upload")
def upload_local(
    request: Request,
    operation_id: int,
    source_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(db_session),
) -> JSONResponse:
    """Envio pela interface, só quando não há R2 (desenvolvimento)."""
    upload_source(session, operation_id, source_id)
    storage = request.app.state.storage
    if storage.upload_url("x.mp4", "video/mp4"):
        raise HTTPException(status_code=409, detail="Com R2, envie pela URL assinada.")
    key = upload_key(operation_id, source_id, file.filename or "")
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
    try:
        storage.put_file(key, Path(tmp.name), CONTENT_TYPES[Path(key).suffix])
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    return JSONResponse({"key": key})


@router.post("/operacoes/{operation_id}/duplicar")
def duplicate(request: Request, operation_id: int, session: Session = Depends(db_session)):
    copy_op = ops.duplicate_operation(session, get_operation(session, operation_id))
    flash(request, "ok", "Operação duplicada como rascunho.")
    return RedirectResponse(f"/operacoes/{copy_op.id}", status_code=303)


@router.post("/operacoes/{operation_id}/config")
def save_config(
    operation_id: int,
    config: dict[str, Any] = Body(...),
    session: Session = Depends(db_session),
) -> JSONResponse:
    """Usado pelo canvas: salva uma versão nova e devolve os problemas do fluxo."""
    op = get_operation(session, operation_id)
    try:
        version = ops.save_config(session, op, config)
    except ops.OperationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    issues = ops.validate_graph(version.config)
    return JSONResponse(
        {
            "version": version.version,
            "issues": [
                {"level": i.level, "message": i.message, "node_id": i.node_id} for i in issues
            ],
        }
    )
