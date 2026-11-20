"""Canvas de blocos num navegador de verdade (Chromium + Playwright)."""

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
            text("TRUNCATE operations, operation_configs, events RESTART IDENTITY CASCADE")
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


def test_canvas_loads_saved_flow(page, server, factory):
    op_id = make_operation(factory)
    page.goto(f"{server}/operacoes/{op_id}/fluxo")
    page.wait_for_selector(".drawflow-node")
    assert page.locator(".drawflow-node").count() == 5
    assert page.locator(".connection").count() == 5
    assert "Adicione ao menos uma fonte de busca na Pesca." in page.inner_text("#canvas-issues")


def test_forbidden_connection_is_removed(page, server, factory):
    op_id = make_operation(factory)
    page.goto(f"{server}/operacoes/{op_id}/fluxo")
    page.wait_for_selector(".drawflow-node")
    before = page.locator(".connection").count()
    # Rede → Aprovação não está na tabela de ligações permitidas.
    page.evaluate(
        """() => {
          const data = window.feaEditor.export().drawflow.Home.data;
          const find = (t) => Object.keys(data).find((k) => data[k].data.type === t);
          window.feaEditor.addConnection(find('network'), find('approval'), 'output_1', 'input_1');
        }"""
    )
    assert page.locator(".connection").count() == before
    assert "Ligação recusada" in page.inner_text("#canvas-status")


def test_add_blocks_connect_and_save(page, server, factory):
    op_id = make_operation(factory)
    page.goto(f"{server}/operacoes/{op_id}/fluxo")
    page.wait_for_selector(".drawflow-node")
    page.click("[data-add=source]")
    page.click("[data-add=account]")
    assert page.locator(".drawflow-node").count() == 7
    page.evaluate(
        """() => {
          const ed = window.feaEditor;
          const data = ed.export().drawflow.Home.data;
          const find = (t) => Object.keys(data).find((k) => data[k].data.type === t);
          ed.updateNodeDataFromId(find('source'), {...data[find('source')].data,
            config: {type: 'reddit', reference: 'r/teste', permission_note: 'ok'}});
          ed.addConnection(find('source'), find('fishing'), 'output_1', 'input_1');
          ed.addConnection(find('account'), find('publish'), 'output_1', 'input_1');
        }"""
    )
    page.click("#save")
    page.wait_for_function("document.querySelector('#canvas-status').textContent.includes('salva')")
    assert page.inner_text("#version") == "v2"
    assert "Fluxo completo" in page.inner_text("#canvas-issues")
    with factory() as s:
        op = s.get(ops.Operation, op_id)
        saved = ops.current_config(s, op).config
    assert ops.validate_graph(saved) == []
    assert all("pos" in node for node in saved["nodes"])
    assert saved["retention"] == {"delete_after_minutes": 30}


def test_panel_edits_block_config(page, server, factory):
    op_id = make_operation(factory)
    page.goto(f"{server}/operacoes/{op_id}/fluxo")
    page.wait_for_selector(".drawflow-node")
    page.click(".drawflow-node.t-fishing")
    page.fill("#node-config", '{"tags": ["academia"], "target_x": 25}')
    page.click("#apply-node")
    config = page.evaluate("() => window.feaExportConfig()")
    fishing = next(n for n in config["nodes"] if n["type"] == "fishing")
    assert fishing["config"] == {"tags": ["academia"], "target_x": 25}


def test_archived_operation_is_read_only(page, server, factory):
    op_id = make_operation(factory, complete_config(), status="archived")
    page.goto(f"{server}/operacoes/{op_id}/fluxo")
    page.wait_for_selector(".drawflow-node")
    assert page.locator("#save").count() == 0
    assert page.locator("[data-add]").count() == 0
    assert "Somente leitura" in page.inner_text("h1 + .chip + .chip")


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
