"""Fluxo da operação (Pesca → Motor Editor → Publicador) num navegador de verdade."""

import os
import socket
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core import operations as ops
from core.db import sqlalchemy_url
from core.models import Account
from tests.conftest import fake_github
from tests.test_operations import complete_config

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
CHROMIUM = next(
    iter(sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux64/chrome"))), None
)
pytestmark = [
    pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL não definida"),
    pytest.mark.skipif(CHROMIUM is None, reason="Chromium não encontrado"),
]
playwright = pytest.importorskip("playwright.sync_api")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(settings):
    import uvicorn

    from web.main import create_app

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", sqlalchemy_url(DATABASE_URL))
    command.upgrade(cfg, "head")
    app = create_app(settings)
    app.state.http_client_factory = fake_github()
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def factory():
    engine = create_engine(sqlalchemy_url(DATABASE_URL))
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE operations, operation_configs, events, accounts RESTART IDENTITY CASCADE"
            )
        )
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def page(server):
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROMIUM), args=["--no-sandbox"])
        pg = browser.new_page(viewport={"width": 1400, "height": 1000})

        # O Playwright não intercepta o destino de um redirecionamento: pede o
        # /auth/github sem segui-lo, lê o state e chama o retorno direto.
        start = pg.context.request.get(f"{server}/auth/github", max_redirects=0)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        pg.goto(f"{server}/auth/github/callback?code=x&state={state}")
        pg.wait_for_url(f"{server}/")
        yield pg
        browser.close()


def make_operation(factory, config=None, status=None) -> int:
    with factory() as s:
        op = ops.create_operation(s, "Canvas", config)
        if status:
            ops.change_status(s, op, status)
        s.commit()
        return op.id


def make_account(factory, platform="youtube", name="Canal A") -> int:
    with factory() as s:
        account = Account(platform=platform, name=name, external_id=f"{platform}-{name}")
        s.add(account)
        s.commit()
        return account.id


def saved_config(factory, op_id):
    with factory() as s:
        return ops.current_config(s, s.get(ops.Operation, op_id)).config


def test_flow_shows_three_blocks_and_issues(page, server, factory):
    op_id = make_operation(factory)
    page.goto(f"{server}/operacoes/{op_id}/fluxo")
    page.wait_for_selector("[data-block]")
    names = page.locator(".block .name").all_inner_texts()
    assert names == ["Pesca", "Motor Editor", "Publicador"]
    assert "Fontes de busca" in page.text_content("#panel")  # Pesca aberta por padrão
    assert "Adicione ao menos uma fonte de busca na Pesca." in page.inner_text("#canvas-issues")
    assert "bad" in page.get_attribute('[data-dot="pesca"]', "class")


def test_configure_all_blocks_and_save(page, server, factory):
    op_id = make_operation(factory)
    youtube = make_account(factory, "youtube", "Canal YT")
    tiktok = make_account(factory, "tiktok", "Perfil TT")
    page.goto(f"{server}/operacoes/{op_id}/fluxo")
    page.wait_for_selector("[data-block]")
    # Pesca: fonte do Reddit e do X, tags.
    page.click("#add-source")
    page.fill('[data-source="0"] [data-src="reference"]', "r/teste")
    page.fill('[data-source="0"] [data-src="permission_note"]', "autorizado")
    page.click("#add-source")
    page.select_option('[data-source="1"] [data-src="type"]', "x")
    page.fill('[data-source="1"] [data-src="reference"]', "@criador")
    page.fill('[data-bind="fishing.tags"]', "academia, treino")
    assert "r/teste" in page.inner_text('[data-summary="pesca"]')
    # Motor Editor: resolução e enquadramento.
    page.click('[data-block="editor"]')
    page.select_option("#resolution", "720x1280")
    page.select_option('[data-bind="edit.preset.video.fit"]', "cover")
    # Publicador: YouTube + TikTok, as duas contas, aprovação automática.
    page.click('[data-block="publicador"]')
    page.check('[data-profile="tiktok"]')
    page.check(f'[data-account="{youtube}"]')
    page.check(f'[data-account="{tiktok}"]')
    page.check('input[name="approval"][value="auto"]')
    page.fill('[data-bind="publish.titles.hashtags"]', "shorts, academia")
    page.click("#save")
    page.wait_for_function("document.querySelector('#canvas-status').textContent.includes('salva')")
    assert page.inner_text("#version") == "v2"
    config = saved_config(factory, op_id)
    assert ops.linked_account_ids(config) == [youtube, tiktok]
    assert [i for i in ops.validate_graph(config) if i.level == "error"] == []
    by_type = {}
    for node in config["nodes"]:
        by_type.setdefault(node["type"], []).append(node)
    assert by_type["network"][0]["config"]["profiles"] == ["youtube_shorts", "tiktok"]
    assert [n["config"]["reference"] for n in by_type["source"]] == ["r/teste", "@criador"]
    assert by_type["source"][1]["config"]["type"] == "x"
    assert by_type["fishing"][0]["config"]["tags"] == ["academia", "treino"]
    preset = by_type["edit"][0]["config"]["preset"]
    assert (preset["video"]["width"], preset["video"]["fit"]) == (720, "cover")
    assert by_type["approval"][0]["config"]["auto_approve"] is True
    assert by_type["publish"][0]["config"]["titles"]["hashtags"] == ["shorts", "academia"]
    # Ao desmarcar a rede, a conta dela sai junto.
    page.uncheck('[data-profile="tiktok"]')
    assert page.locator(f'[data-account="{tiktok}"]').count() == 0


def test_mask_upload_from_editor_block(page, server, factory, tmp_path):
    from PIL import Image

    op_id = make_operation(factory)
    png = tmp_path / "moldura.png"
    Image.new("RGBA", (1080, 1920), (0, 0, 0, 0)).save(png)
    page.goto(f"{server}/operacoes/{op_id}/fluxo")
    page.click('[data-block="editor"]')
    page.set_input_files("#mask-file", str(png))
    page.wait_for_function(
        "document.querySelector('#mask-status').textContent.includes('importada')"
    )
    assert page.is_checked('input[name="mask"]:not([value=""])')
    assert "moldura" in page.inner_text('[data-summary="editor"]')
    page.click("#save")
    page.wait_for_function("document.querySelector('#canvas-status').textContent.includes('salva')")
    preset = next(n for n in saved_config(factory, op_id)["nodes"] if n["type"] == "edit")
    assert preset["config"]["preset"]["mask"]["mask_id"]


def test_archived_operation_is_read_only(page, server, factory):
    op_id = make_operation(factory, complete_config(), status="archived")
    page.goto(f"{server}/operacoes/{op_id}/fluxo")
    page.wait_for_selector("[data-block]")
    assert page.locator("#save").count() == 0
    assert page.locator("#add-source").count() == 0
    assert page.is_disabled('[data-bind="fishing.tags"]')
    assert "Somente leitura" in page.inner_text(".top")


def test_manual_upload_from_sources_tab(page, server, factory, tmp_path):
    from core.sources import list_sources
    from core.storage import LocalStorage

    config = complete_config()
    config["nodes"].append(
        {"id": "up", "type": "source", "config": {"type": "upload", "reference": "Envios"}}
    )
    op_id = make_operation(factory, config)
    video = tmp_path / "meme.mp4"
    video.write_bytes(b"video de teste")
    page.goto(f"{server}/operacoes/{op_id}?aba=fontes")
    page.set_input_files("input[type=file]", str(video))
    page.wait_for_selector("#upload-log li.ok")
    assert "meme.mp4: enviado" in page.inner_text("#upload-log")
    with factory() as s:
        source = next(x for x in list_sources(s, op_id) if x.type == "upload")
    storage = LocalStorage("storage")
    keys = storage.list(f"uploads/{op_id}/{source.id}/")
    assert len(keys) == 1
    storage.delete(keys[0])
