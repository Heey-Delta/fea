"""Editor de ponta a ponta (Tasks 10, 12, 15.5, 17, 18.5): fila de pesca → fila de editados."""

import os
import shutil
import subprocess

import pytest
from PIL import Image
from sqlalchemy import select, text

import core.models as m
from core import masks
from core import operations as ops
from core.queue import RetryableError
from core.storage import LocalStorage

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL não definida"),
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg não instalado"),
]
FAST = {"video": {"width": 720, "height": 1280}, "export": {"x264_preset": "ultrafast"}}


@pytest.fixture
def factory():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from core.db import sqlalchemy_url

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", sqlalchemy_url(DATABASE_URL))
    command.upgrade(cfg, "head")
    engine = create_engine(sqlalchemy_url(DATABASE_URL))
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE operations, accounts, jobs, events, app_credentials, worker_heartbeats,"
                " infra_servers, r2_usage, app_settings"
                " RESTART IDENTITY CASCADE"
            )
        )
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "storage")


def make_video(path, audio=True):
    cmd = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=640x360:rate=25:duration=2",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=duration=2", "-c:a", "aac", "-shortest"]
    subprocess.run([*cmd, "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path)], check=True)
    return path


def setup(factory, storage, tmp_path, preset=None, auto_approve=False, audio=True, permission="ok"):
    """Operação ativa com um item elegível já baixado."""
    with factory() as s:
        account = m.Account(platform="youtube", name="Canal A", external_id="UC1")
        s.add(account)
        s.flush()
        config = ops.default_config()
        config["nodes"][1]["config"]["preset"] = {**FAST, **(preset or {})}
        config["nodes"][2]["config"]["auto_approve"] = auto_approve
        config["nodes"] += [
            {
                "id": "f1",
                "type": "source",
                "config": {"type": "reddit", "reference": "r/x1", "permission_note": permission},
            },
            {"id": "c1", "type": "account", "config": {"account_id": account.id}},
        ]
        config["edges"] += [{"from": "f1", "to": "pesca"}, {"from": "c1", "to": "postagem"}]
        op = ops.create_operation(s, "Edição", config)
        ops.change_status(s, op, "active")
        from core.executions import start_execution

        ex = start_execution(s, op, target_x=1)
        source = s.scalars(select(m.Source)).one()
        key = f"operations/{op.id}/items/1/original.mp4"
        storage.put_file(key, make_video(tmp_path / "orig.mp4", audio=audio))
        item = m.Item(
            operation_id=op.id,
            execution_id=ex.id,
            source_id=source.id,
            external_id="p1",
            media_type="video",
            status="eligible",
            original_file=key,
        )
        s.add(item)
        s.commit()
        return op.id, item.id, account.id


def run(factory, storage, item_id, **kw):
    from worker.render import run_render

    return run_render(factory, item_id, storage, **kw)


def state(factory, item_id):
    with factory() as s:
        item = s.get(m.Item, item_id)
        renders = s.scalars(
            select(m.Render).where(m.Render.item_id == item_id).order_by(m.Render.version)
        ).all()
        return item, renders


def test_render_goes_to_edited_queue(factory, storage, tmp_path):
    _, item_id, _ = setup(factory, storage, tmp_path)
    run(factory, storage, item_id)
    item, renders = state(factory, item_id)
    assert item.status == "awaiting_approval"
    assert [r.status for r in renders] == ["ok"]
    assert renders[0].qa_result["passed"] is True
    assert storage.exists(renders[0].output_file)
    assert renders[0].output_file.endswith("/renders/1.mp4")


def test_auto_approve_publishes_straight_to_accounts(factory, storage, tmp_path):
    _, item_id, account_id = setup(factory, storage, tmp_path, auto_approve=True)
    run(factory, storage, item_id)
    item, renders = state(factory, item_id)
    assert (item.status, item.approved_by) == ("approved", "auto")
    assert item.approved_render_id == renders[0].id
    assert item.approved_account_ids == [account_id]


def test_auto_approve_needs_permission(factory, storage, tmp_path):
    _, item_id, _ = setup(factory, storage, tmp_path, auto_approve=True, permission="")
    run(factory, storage, item_id)
    assert state(factory, item_id)[0].status == "awaiting_approval"


def test_blocking_qc_goes_to_needs_fix(factory, storage, tmp_path):
    _, item_id, _ = setup(
        factory, storage, tmp_path, preset={"audio": {"required": True}}, audio=False
    )
    run(factory, storage, item_id)
    item, renders = state(factory, item_id)
    assert item.status == "needs_fix" and "áudio" in item.status_reason
    assert renders[0].status == "failed" and renders[0].qa_result["passed"] is False


def test_preset_outside_network_rules_is_refused(factory, storage, tmp_path):
    _, item_id, _ = setup(factory, storage, tmp_path, preset={"video": {"fps": 29}})
    run(factory, storage, item_id)
    item, _ = state(factory, item_id)
    assert item.status == "needs_fix" and "29 FPS" in item.status_reason


def test_mask_version_is_recorded(factory, storage, tmp_path):
    op_id, item_id, _ = setup(factory, storage, tmp_path)
    png = tmp_path / "moldura.png"
    Image.new("RGBA", (720, 1280), (0, 0, 0, 0)).save(png)
    with factory() as s:
        version, check = masks.import_mask(s, storage, op_id, png, output=(720, 1280))
        op = s.get(m.Operation, op_id)
        config = ops.current_config(s, op).config
        config["nodes"][1]["config"]["preset"]["mask"] = {"mask_id": version.mask_id}
        new = ops.save_config(s, op, config)
        s.commit()
    run(factory, storage, item_id, payload={"config_id": new.id})
    _, renders = state(factory, item_id)
    assert renders[0].mask_version_id == version.id
    checks = {c["name"]: c["ok"] for c in renders[0].qa_result["checks"]}
    assert checks["máscara aplicada"] is True


def test_new_version_never_overwrites_and_clears_approval(factory, storage, tmp_path):
    _, item_id, _ = setup(factory, storage, tmp_path, auto_approve=True)
    run(factory, storage, item_id)
    run(factory, storage, item_id)
    item, renders = state(factory, item_id)
    assert [r.version for r in renders] == [1, 2]
    assert all(storage.exists(r.output_file) for r in renders)
    assert item.approved_render_id == renders[1].id  # aprovação nova, do render novo


def test_process_error_retries_then_needs_fix(factory, storage, tmp_path, monkeypatch):
    from core.editor import render as rd

    _, item_id, _ = setup(factory, storage, tmp_path)

    def broken(plan, timeout_s=900, **_):
        raise RuntimeError("FFmpeg falhou: memória")

    monkeypatch.setattr(rd, "run", broken)
    with pytest.raises(RetryableError):
        run(factory, storage, item_id, attempt=1)
    assert state(factory, item_id)[0].status == "eligible"
    run(factory, storage, item_id, attempt=3)  # passou de max_retries (2)
    item, renders = state(factory, item_id)
    assert item.status == "needs_fix" and [r.status for r in renders] == ["failed", "failed"]


def test_render_job_through_the_queue(factory, storage, tmp_path, monkeypatch):
    from core import queue
    from worker import render as worker_render
    from worker.runner import Worker

    _, item_id, _ = setup(factory, storage, tmp_path)
    monkeypatch.setattr(worker_render, "get_storage", lambda: storage)
    with factory() as s:
        queue.enqueue(s, "render", f"render:{item_id}:1", ref_id=item_id)
        s.commit()
    Worker("editor", {"render": worker_render.render_job}, factory).run_once()
    assert state(factory, item_id)[0].status == "awaiting_approval"


# --- máscaras ---------------------------------------------------------------------------


def test_mask_import_validation(factory, storage, tmp_path):
    op_id, _, _ = setup(factory, storage, tmp_path)
    jpg = tmp_path / "foto.jpg"
    Image.new("RGB", (1080, 1920)).save(jpg)
    broken = tmp_path / "quebrado.png"
    broken.write_bytes(b"\x89PNG lixo")
    opaque = tmp_path / "opaca.png"
    Image.new("RGB", (500, 500)).save(opaque)
    good = tmp_path / "boa.png"
    Image.new("RGBA", (1080, 1920)).save(good)
    with factory() as s:
        with pytest.raises(masks.MaskError, match="PNG"):
            masks.import_mask(s, storage, op_id, jpg)
        with pytest.raises(masks.MaskError, match="corrompido"):
            masks.import_mask(s, storage, op_id, broken)
        v1, check = masks.import_mask(s, storage, op_id, opaque, name="Moldura")
        assert any("transparência" in w for w in check.warnings)
        assert any("Dimensões" in w for w in check.warnings)
        v2, check2 = masks.import_mask(s, storage, op_id, good, mask_id=v1.mask_id)
        assert check2.warnings == [] and (v1.version, v2.version) == (1, 2)
        assert masks.latest_version(s, v1.mask_id).id == v2.id
        assert storage.exists(v1.file_key) and storage.exists(v2.file_key)
        [(mask, versions)] = masks.list_masks(s, op_id)
        assert mask.name == "Moldura" and [v.version for v in versions] == [2, 1]
