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


MIXED = [
    {"id": "foto", "name": "meme.jpg", "mimeType": "image/jpeg"},
    {"id": "gen", "name": "meme2.JPG", "mimeType": "application/octet-stream"},
    {"id": "atalho", "name": "meme3", "mimeType": "application/vnd.google-apps.shortcut",
     "shortcutDetails": {"targetId": "alvo3", "targetMimeType": "image/png"}},
    {"id": "doc", "name": "notas", "mimeType": "application/vnd.google-apps.document"},
    {"id": "pdf", "name": "a.pdf", "mimeType": "application/pdf"},
    {"id": "pdf2", "name": "b.pdf", "mimeType": "application/pdf"},
]  # fmt: skip


def mixed_drive():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/drive/v3/files":
            assert "mimeType" not in request.url.params["q"]  # sem filtro de tipo no Google
            return httpx.Response(200, json={"files": MIXED})
        return httpx.Response(200, json={"id": "x"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_atalhos_e_tipo_generico_entram_e_o_resto_e_contado():
    from core.connectors.drive import skipped_summary

    conn = DriveConnector(key_settings(), client=mixed_drive())
    page = conn.fetch(SourceRef(1, "drive", FOLDER), None)
    assert [(i.external_id, i.media_type, i.media_url) for i in page.items] == [
        ("foto", "image", "foto"),
        ("gen", "image", "gen"),
        ("alvo3", "image", "alvo3"),  # atalho baixa o arquivo de destino
    ]
    assert skipped_summary(conn) == (
        "2 × application/pdf, 1 × application/vnd.google-apps.document"
    )


def test_testar_conexao_mostra_os_ignorados(factory):  # noqa: F811
    from core import sources
    from core.storage import LocalStorage

    op_id, _ = meme_operation(factory)
    with factory() as s:
        source = s.scalars(select(m.Source).where(m.Source.operation_id == op_id)).one()
        result = sources.test_connection(
            s, source, key_settings(), LocalStorage("/tmp/x"), client=mixed_drive()
        )
    assert "3 vídeos/imagens" in result.message and "2 × application/pdf" in result.message


# --- imagens salvas como .txt (caso real do usuário) -------------------------------------


def test_assinatura_reconhece_imagem_e_video_pelo_conteudo(tmp_path):
    from core.connectors.drive import sniff

    jpg = make_meme(tmp_path / "a.jpg", 1).read_bytes()
    assert sniff(jpg[:32]) == "image"
    assert sniff(b"\x89PNG\r\n\x1a\n" + b"\0" * 24) == "image"
    assert sniff(b"RIFF\0\0\0\0WEBPVP8 " + b"\0" * 16) == "image"
    assert sniff(b"\0\0\0\x18ftypheic" + b"\0" * 20) == "image"
    assert sniff(b"\0\0\0\x18ftypisom" + b"\0" * 20) == "video"
    assert sniff(b"so um texto comum\n" + b" " * 14) is None


def txt_drive(images_dir, n):
    """Pasta com memes JPEG salvos como .txt (o Drive diz text/plain) e um .txt de verdade."""
    files = [
        {"id": f"meme{i}", "name": f"meme{i}.txt", "mimeType": "text/plain"} for i in range(n)
    ] + [{"id": "nota", "name": "nota.txt", "mimeType": "text/plain"}]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/drive/v3/files":
            return httpx.Response(200, json={"files": files})
        fid = request.url.path.rsplit("/", 1)[-1]
        if fid == "nota":
            return httpx.Response(200, content=b"isto e um texto de verdade, nao imagem")
        data = (images_dir / f"{fid}.jpg").read_bytes()
        if request.headers.get("range"):
            return httpx.Response(206, content=data[:32])
        return httpx.Response(200, content=data)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_memes_salvos_como_txt_viram_shorts(factory, tmp_path):  # noqa: F811
    from core.storage import LocalStorage
    from worker.collect import run_collect
    from worker.render import run_render

    for i in range(10):
        make_meme(tmp_path / f"meme{i}.jpg", i)
    storage = LocalStorage(tmp_path / "s")
    op_id, ex_id = meme_operation(factory, target_x=2)
    progress = run_collect(
        factory, ex_id, key_settings(), storage,
        {"client": txt_drive(tmp_path, 10), "sleep": lambda _: 0},
    )  # fmt: skip
    assert len(progress.eligible) == 10, progress
    assert "1 × text/plain" in progress.stop_reason  # o .txt de verdade é contado à parte
    with factory() as s:
        refs = [j.ref_id for j in s.scalars(select(m.Job).where(m.Job.type == "render"))]
    for ref in refs:
        run_render(factory, ref, storage)
    with factory() as s:
        statuses = sorted(i.status for i in s.scalars(select(m.Item)))
    assert statuses.count("approved") == 2 and statuses.count("grouped") == 8
