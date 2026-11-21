"""Diagnóstico de ponta a ponta: fotos de meme no Drive → agrupar → aprovar → agenda (Task 39).

Usa o código real dos workers (busca, editor, distribuição), com a API do Drive simulada.
"""

import httpx
import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select

import core.models as m
from core import executions
from core import operations as ops
from core.storage import LocalStorage
from tests.test_drive import FOLDER, key_settings
from tests.test_render_job import FAST, factory, pytestmark  # noqa: F401

GROUP = 5


def make_meme(path, n):
    """Foto de meme distinta: cena aleatória (formas e cores) com legenda em cima e embaixo."""
    import random

    rng = random.Random(n)
    img = Image.new("RGB", (720, 720), tuple(rng.randrange(256) for _ in range(3)))
    draw = ImageDraw.Draw(img)
    for _ in range(25):
        x, y = rng.randrange(720), rng.randrange(720)
        box = (x, y, x + rng.randrange(40, 300), y + rng.randrange(40, 300))
        color = tuple(rng.randrange(256) for _ in range(3))
        (draw.ellipse if rng.random() < 0.5 else draw.rectangle)(box, fill=color)
    draw.text((40, 30), f"QUANDO O MEME {n} BATE", fill="white")
    draw.text((40, 680), "kkkkkk", fill="yellow")
    img.save(path, "JPEG")
    return path


def drive_with(images):
    files = [
        {
            "id": f"img{i}",
            "name": p.name,
            "mimeType": "image/jpeg",
            "createdTime": f"2026-11-21T00:00:{i:02d}.000Z",
        }
        for i, p in enumerate(images)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/drive/v3/files":
            return httpx.Response(200, json={"files": files})
        for i, p in enumerate(images):
            if request.url.path == f"/drive/v3/files/img{i}":
                return httpx.Response(200, content=p.read_bytes())
        return httpx.Response(404)

    return {"client": httpx.Client(transport=httpx.MockTransport(handler)), "sleep": lambda _: 0}


def meme_operation(factory, tags=None, target_x=10):  # noqa: F811
    with factory() as s:
        account = m.Account(platform="youtube", name="Canal", external_id="UCmeme")
        s.add(account)
        s.flush()
        config = ops.default_config()
        fishing = config["nodes"][0]["config"]
        fishing["accepted_media"] = ["video", "image"]
        fishing["tags"] = tags or []
        fishing["target_x"] = 10
        config["nodes"][1]["config"]["preset"] = {
            **FAST,
            "video": {**FAST["video"], "group_images": GROUP, "image_duration_s": 1},
            "audio": {"mode": "remove"},
        }
        config["nodes"][2]["config"]["auto_approve"] = True  # "Autorizar tudo"
        config["nodes"][3]["config"]["automatic"] = True
        config["nodes"] += [
            {
                "id": "f1",
                "type": "source",
                "config": {
                    "type": "drive",
                    "reference": f"https://drive.google.com/drive/folders/{FOLDER}",
                },
            },
            {"id": "c1", "type": "account", "config": {"account_id": account.id}},
        ]
        config["edges"] += [{"from": "f1", "to": "pesca"}, {"from": "c1", "to": "postagem"}]
        op = ops.create_operation(s, "Memes", config)
        ops.change_status(s, op, "active")
        s.commit()
        ex = executions.start_execution(s, op, target_x=target_x)
        s.commit()
        return op.id, ex.id


def run_pipeline(factory, tmp_path, n_images, tags=None, target_x=10):  # noqa: F811
    from worker.collect import run_collect
    from worker.render import run_render

    storage = LocalStorage(tmp_path / "storage")
    images = [make_meme(tmp_path / f"meme_{i}.jpg", i) for i in range(n_images)]
    op_id, ex_id = meme_operation(factory, tags, target_x)
    progress = run_collect(factory, ex_id, key_settings(), storage, drive_with(images))
    with factory() as s:
        jobs = s.scalars(select(m.Job).where(m.Job.type == "render").order_by(m.Job.id)).all()
        render_refs = [j.ref_id for j in jobs]
    results = [run_render(factory, ref, storage) for ref in render_refs]
    with factory() as s:
        items = s.scalars(select(m.Item).where(m.Item.operation_id == op_id)).all()
        status = {}
        for item in items:
            status[item.status] = status.get(item.status, 0) + 1
        reasons = {i.status_reason for i in items if i.status in ("rejected", "needs_fix")}
    return progress, status, reasons, results, op_id


def test_dez_memes_viram_dois_shorts_aprovados_e_agendados(factory, tmp_path):  # noqa: F811
    from core import distribution

    progress, status, reasons, results, op_id = run_pipeline(factory, tmp_path, 10)
    assert progress.examined == 10, progress.stop_reason
    assert not reasons, reasons
    assert status == {"approved": 2, "grouped": 8}, status
    with factory() as s:
        distribution.auto_distribute(s)
        s.commit()
        planned = s.scalars(select(m.PublishJob)).all()
    assert len(planned) == 2 and {p.status for p in planned} == {"planned"}


def test_tag_no_drive_da_prioridade_sem_descartar(factory, tmp_path):  # noqa: F811
    """Tag que não aparece no nome do arquivo não barra: os memes seguem e viram Shorts."""
    progress, status, reasons, _, _ = run_pipeline(factory, tmp_path, 10, tags=["academia"])
    assert "rejected" not in status and status == {"approved": 2, "grouped": 8}, status


def test_ordem_sem_tags_e_aleatoria_e_com_tags_prioriza():
    from core.connectors.base import RawItem
    from worker.collect import arrange

    raws = [
        RawItem(external_id=str(i), url=None, author=None, published_at=None,
                media_type="image", text=f"meme {i}", media_url=str(i))
        for i in range(30)
    ]  # fmt: skip
    orders = {tuple(r.external_id for r in arrange(raws, {}, searched=False)) for _ in range(5)}
    assert len(orders) > 1  # aleatória
    tagged = [*raws, RawItem(external_id="gato", url=None, author=None, published_at=None,
                             media_type="image", text="meme de gato", media_url="g")]  # fmt: skip
    assert arrange(tagged, {"tags": ["gato"]}, searched=False)[0].external_id == "gato"
    assert [r.external_id for r in arrange(raws, {}, searched=True)] == [str(i) for i in range(30)]


def test_meta_conta_videos_quando_agrupa(factory, tmp_path):  # noqa: F811
    """Meta X = 2 vídeos com grupo de 5: busca 10 imagens e sai com 2 Shorts."""
    progress, status, _, _, _ = run_pipeline(factory, tmp_path, 12, target_x=2)
    assert progress.examined == 10 and status.get("approved") == 2, (progress, status)


@pytest.mark.parametrize("n", [3])
def test_menos_imagens_que_o_grupo_ficam_esperando(factory, tmp_path, n):  # noqa: F811
    _, status, _, results, _ = run_pipeline(factory, tmp_path, n)
    assert status == {"eligible": n} and results == [None] * n
