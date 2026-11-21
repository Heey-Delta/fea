"""Correções do diagnóstico real de 21/11 (Task 43).

O diagnóstico mostrou: busca com 1 examinado e 1 já visto (a pasta só expunha 1 arquivo à
API: os memes estavam em subpastas), música aleatória sem músicas travando o render, agenda
manual com "Autorizar tudo" e reposição de estoque disparando uma busca por minuto.
"""

import re
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

import core.models as m
from core import automation, distribution, executions
from core import operations as ops
from core.connectors.base import SourceRef
from core.connectors.drive import FOLDER_MIME, DriveConnector
from core.editor import preset as pr
from tests.test_drive import FOLDER, key_settings
from tests.test_drive_memes_e2e import make_meme, meme_operation
from tests.test_render_job import factory, pytestmark  # noqa: F401

TREE = {
    FOLDER: [("raiz.jpg", None), ("Memes novembro", "sub1")],
    "sub1": [(f"m{i}.jpg", None) for i in range(4)] + [("Mais", "sub2")],
    "sub2": [("x1.jpg", None), ("x2.jpg", None)],
}


def drive_tree(images_dir=None, page_size=None):
    """Drive com subpastas. Com `page_size`, pagina cada pasta (testa o cursor)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/drive/v3/files":
            parent = re.search(r"'([^']+)' in parents", request.url.params["q"]).group(1)
            entries = TREE.get(parent, [])
            files = [
                {"id": sub or name.split(".")[0], "name": name,
                 "mimeType": FOLDER_MIME if sub else "image/jpeg"}
                for name, sub in entries
            ]  # fmt: skip
            start = int(request.url.params.get("pageToken") or 0)
            if page_size:
                chunk, end = files[start : start + page_size], start + page_size
                token = str(end) if end < len(files) else None
                return httpx.Response(200, json={"files": chunk, "nextPageToken": token})
            return httpx.Response(200, json={"files": files})
        name = request.url.path.rsplit("/", 1)[-1]
        if images_dir and (images_dir / f"{name}.jpg").exists():
            return httpx.Response(200, content=(images_dir / f"{name}.jpg").read_bytes())
        return httpx.Response(200, json={"id": name})

    return httpx.Client(transport=httpx.MockTransport(handler))


def all_items(conn):
    ref, cursor, ids = SourceRef(1, "drive", FOLDER), None, []
    while True:
        page = conn.fetch(ref, cursor)
        ids += [i.external_id for i in page.items]
        if not page.next_cursor:
            return ids
        cursor = page.next_cursor


def test_drive_percorre_subpastas():
    ids = all_items(DriveConnector(key_settings(), client=drive_tree()))
    assert sorted(ids) == sorted(["raiz", "m0", "m1", "m2", "m3", "x1", "x2"])


def test_drive_percorre_subpastas_com_paginacao():
    ids = all_items(DriveConnector(key_settings(), client=drive_tree(page_size=2)))
    assert sorted(ids) == sorted(["raiz", "m0", "m1", "m2", "m3", "x1", "x2"])


def test_cursor_antigo_continua_valendo():
    conn = DriveConnector(key_settings(), client=drive_tree(page_size=1))
    page = conn.fetch(SourceRef(1, "drive", FOLDER), "1")  # pageToken puro de versão antiga
    assert [i.external_id for i in page.items] == []  # 2º da raiz é a subpasta


def test_busca_acha_os_memes_da_subpasta(factory, tmp_path):  # noqa: F811
    from core.storage import LocalStorage
    from worker.collect import run_collect

    for name in ("raiz", "m0", "m1", "m2", "m3", "x1", "x2"):
        make_meme(tmp_path / f"{name}.jpg", hash(name) % 1000)
    _, ex_id = meme_operation(factory, target_x=1)
    progress = run_collect(
        factory, ex_id, key_settings(), LocalStorage(tmp_path / "s"),
        {"client": drive_tree(tmp_path), "sleep": lambda _: 0},
    )  # fmt: skip
    assert progress.examined == 5 and len(progress.eligible) == 5  # meta 1 vídeo × 5 imagens


def test_musica_aleatoria_sem_musicas_nao_trava():
    preset = pr.resolve({"audio": {"mode": "random", "library": []}})
    assert pr.validate(preset) == []
    from worker.render import pick_music

    assert pick_music(preset) is None  # sai sem música


def test_autorizar_tudo_agenda_mesmo_com_agenda_manual(factory, tmp_path):  # noqa: F811
    from tests.test_drive_memes_e2e import run_pipeline

    _, status, _, _, op_id = run_pipeline(factory, tmp_path, 5)
    assert status == {"approved": 1, "grouped": 4}
    with factory() as s:
        op = s.get(m.Operation, op_id)
        config = ops.current_config(s, op).config
        for node in config["nodes"]:
            if node["type"] == "publish":
                node["config"]["automatic"] = False  # como no diagnóstico: agenda=manual
        ops.save_config(s, op, config)
        s.commit()
        assert distribution.auto_distribute(s)
        s.commit()
        assert s.scalars(select(m.PublishJob)).all()


def test_reposicao_de_estoque_espera_quando_nao_acha_nada(factory):  # noqa: F811
    now = datetime.now(UTC)
    op_id, ex_id = meme_operation(factory, target_x=1)
    with factory() as s:
        op = s.get(m.Operation, op_id)
        config = ops.current_config(s, op).config
        config["automation"].update({"stock_enabled": True, "daily_target": 30})
        ops.save_config(s, op, config)
        ex = s.get(m.Execution, ex_id)
        ex.trigger, ex.status = "stock", "partial"  # última reposição não achou nada
        s.commit()
        assert automation.automation_tick(s, now) == []  # espera
        s.get(m.Execution, ex_id).started_at = now - timedelta(minutes=31)
        s.commit()
        started = automation.automation_tick(s, now)
        assert len(started) == 1  # passados 30 min, tenta de novo
        assert s.get(m.Execution, started[0]).trigger == "stock"
        executions  # noqa: B018 - módulo usado pelo automation_tick
