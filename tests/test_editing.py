"""Tela da Edição (Tasks 12 e 15): preset por formulário, máscaras, arquivos e Testar preset."""

import io

from PIL import Image
from sqlalchemy import select

import core.models as m
from core import operations as ops
from core.editor import preset as pr
from tests.test_approval import app_client
from tests.test_render_job import factory, make_video, pytestmark, setup, storage  # noqa: F401
from web.editing import preset_from_form
from worker.render import run_test


def png(size=(720, 1280), alpha=True) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA" if alpha else "RGB", size, (0, 0, 0, 0) if alpha else (0, 0, 0)).save(
        buf, "PNG"
    )
    return buf.getvalue()


def test_form_converts_percentages():
    preset = preset_from_form(
        {
            "resolution": "720x1280",
            "fps": "30",
            "fit": "cover",
            "mask_opacity_pct": "50",
            "t0_content": "@canal",
            "t0_size": "48",
            "e0_file_key": "operations/1/assets/a.png",
            "e0_scale_pct": "15",
            "audio_mode": "remove",
            "audio_normalize": "on",
        }
    )
    assert preset["video"]["width"] == 720 and preset["mask"]["opacity"] == 0.5
    assert preset["texts"][0]["content"] == "@canal" and len(preset["texts"]) == 1
    assert preset["elements"][0]["scale"] == 0.15
    assert preset["audio"]["mode"] == "remove" and preset["audio"]["normalize"] is True
    assert pr.validate(preset) == []


def test_page_save_and_reject(settings, factory, storage, tmp_path):  # noqa: F811
    op_id, _, _ = setup(factory, storage, tmp_path)
    client = app_client(settings, storage)
    page = client.get(f"/operacoes/{op_id}/edicao")
    assert page.status_code == 200 and "Salvar preset" in page.text
    saved = client.post(
        f"/operacoes/{op_id}/edicao",
        data={"resolution": "720x1280", "fps": "30", "fit": "contain", "t0_content": "Oi"},
    )
    assert "Preset salvo na versão v2" in saved.text
    with factory() as s:
        config = ops.current_config(s, s.get(m.Operation, op_id)).config
    assert pr.from_config(config)["video"]["fit"] == "contain"
    bad = client.post(f"/operacoes/{op_id}/edicao", data={"resolution": "720x1280", "fps": "12"})
    assert "Preset não salvo" in bad.text and "FPS" in bad.text


def test_mask_upload_and_versions(settings, factory, storage, tmp_path):  # noqa: F811
    op_id, _, _ = setup(factory, storage, tmp_path)
    client = app_client(settings, storage)
    ok = client.post(
        f"/operacoes/{op_id}/mascaras",
        files={"file": ("moldura.png", png(), "image/png")},
        data={"name": "Moldura"},
    )
    assert "Máscara importada (versão 1)" in ok.text and "Moldura" in ok.text
    with factory() as s:
        mask_id = s.scalar(select(m.MaskAsset.id))
    again = client.post(
        f"/operacoes/{op_id}/mascaras",
        files={"file": ("m.png", png(alpha=False), "image/png")},
        data={"mask_id": str(mask_id)},
    )
    assert "versão 2" in again.text and "transparência" in again.text
    refused = client.post(
        f"/operacoes/{op_id}/mascaras", files={"file": ("x.png", b"nada", "image/png")}
    )
    assert "Máscara recusada" in refused.text


def test_asset_upload_local(settings, factory, storage, tmp_path):  # noqa: F811
    op_id, _, _ = setup(factory, storage, tmp_path)
    client = app_client(settings, storage)
    plan = client.post(f"/operacoes/{op_id}/arquivos/upload-url", json={"filename": "logo.png"})
    assert plan.json()["mode"] == "local"
    sent = client.post(plan.json()["url"], files={"file": ("logo.png", png((100, 100)))})
    key = sent.json()["key"]
    assert key.startswith(f"operations/{op_id}/assets/") and storage.exists(key)
    assert (
        client.post(
            f"/operacoes/{op_id}/arquivos/upload-url", json={"filename": "x.exe"}
        ).status_code
        == 400
    )


def test_preset_test_enqueues_and_renders(settings, factory, storage, tmp_path):  # noqa: F811
    op_id, _, _ = setup(factory, storage, tmp_path)
    sample = f"operations/{op_id}/assets/amostra.mp4"
    storage.put_file(sample, make_video(tmp_path / "a.mp4"), "video/mp4")
    client = app_client(settings, storage)
    assert (
        client.post(
            f"/operacoes/{op_id}/edicao/testar", data={"sample_key": "operations/999/x.mp4"}
        ).status_code
        == 400
    )
    response = client.post(f"/operacoes/{op_id}/edicao/testar", data={"sample_key": sample})
    assert "Teste na fila do Editor" in response.text
    with factory() as s:
        job = s.scalars(select(m.Job).where(m.Job.idempotency_key.like("render-test:%"))).one()
        assert job.payload["test"] and job.ref_id is None
        job_id, payload = job.id, job.payload
    detail = run_test(factory, job_id, payload, storage)
    assert detail["ok"], detail
    assert storage.exists(detail["output_file"]) and detail["size_bytes"] > 0
    page = client.get(f"/operacoes/{op_id}/edicao")
    assert "OK" in page.text and detail["output_file"] in page.text
