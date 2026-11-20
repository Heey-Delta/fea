"""Operações: validação do fluxo, versões, estados e telas (Task 4)."""

import copy
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

import core.models as m
from core import operations as ops
from core.db import sqlalchemy_url

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL não definida")


def complete_config() -> dict:
    """Fluxo padrão com uma fonte e uma conta ligadas: sem erros."""
    config = ops.default_config()
    config["nodes"] += [
        {
            "id": "reddit",
            "type": "source",
            "config": {"type": "reddit", "reference": "r/teste", "permission_note": "ok"},
        },
        {"id": "contaA", "type": "account", "config": {"account_id": 1}},
    ]
    config["edges"] += [
        {"from": "reddit", "to": "pesca"},
        {"from": "contaA", "to": "postagem"},
    ]
    return config


def messages(config) -> list[str]:
    return [i.message for i in ops.validate_graph(config)]


# --- validação do fluxo (sem banco) ----------------------------------------------------


def test_complete_flow_has_no_issues():
    assert ops.validate_graph(complete_config()) == []


def test_default_flow_needs_source_and_account():
    errors = messages(ops.default_config())
    assert "Adicione ao menos uma fonte de busca na Pesca." in errors
    assert "Escolha ao menos uma conta no Publicador." in errors
    assert len(errors) == 2


def test_forbidden_edge_is_refused():
    config = complete_config()
    config["edges"].append({"from": "reddit", "to": "postagem"})
    assert "Fonte não pode ligar em Publicador." in messages(config)


def test_skipping_a_stage_is_an_error():
    config = complete_config()
    config["edges"] = [e for e in config["edges"] if e != {"from": "edicao", "to": "aprovacao"}]
    assert "Ligue o Motor Editor à Aprovação." in messages(config)


def test_single_blocks_must_be_unique():
    config = complete_config()
    config["nodes"].append({"id": "rede2", "type": "network", "config": {}})
    assert "A operação precisa de exatamente um bloco Rede." in messages(config)


def test_unknown_block_and_dangling_edge():
    config = complete_config()
    config["nodes"].append({"id": "x", "type": "foguete"})
    config["edges"].append({"from": "pesca", "to": "fantasma"})
    found = messages(config)
    assert any(msg.startswith("Bloco inválido") for msg in found)
    assert any(msg.startswith("Ligação com bloco inexistente") for msg in found)


def test_source_without_permission_is_only_a_warning():
    config = complete_config()
    config["nodes"][-2]["config"] = {"type": "reddit", "reference": "r/teste"}
    issues = ops.validate_graph(config)
    assert [i.level for i in issues] == ["warning"]
    assert issues[0].node_id == "reddit"


def test_cycle_detection():
    assert ops._has_cycle({"a": {}, "b": {}}, {"a": {"b"}, "b": {"a"}})
    assert not ops._has_cycle({"a": {}, "b": {}}, {"a": {"b"}, "b": set()})


# --- persistência ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def factory():
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", sqlalchemy_url(DATABASE_URL))
    command.upgrade(config, "head")
    engine = create_engine(sqlalchemy_url(DATABASE_URL))
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def session(factory):
    with factory() as s:
        s.execute(text("TRUNCATE operations, operation_configs, events RESTART IDENTITY CASCADE"))
        s.commit()
        yield s
        s.rollback()


@needs_db
def test_create_starts_as_draft_with_version_1(session):
    op = ops.create_operation(session, "  Operação A  ")
    assert op.name == "Operação A" and op.status == "draft"
    assert ops.current_config(session, op).version == 1


@needs_db
def test_empty_name_is_refused(session):
    with pytest.raises(ops.OperationError):
        ops.create_operation(session, "   ")


@needs_db
def test_saving_creates_new_immutable_version(session):
    op = ops.create_operation(session, "A")
    first = ops.current_config(session, op)
    ops.save_config(session, op, complete_config())
    assert ops.current_config(session, op).version == 2
    assert session.get(m.OperationConfig, first.id).config == ops.default_config()
    assert [v.version for v in ops.versions(session, op)] == [2, 1]


@needs_db
def test_saving_identical_config_does_not_create_version(session):
    op = ops.create_operation(session, "A")
    ops.save_config(session, op, ops.default_config())
    assert ops.current_config(session, op).version == 1


@needs_db
def test_cannot_activate_with_errors(session):
    op = ops.create_operation(session, "A")
    with pytest.raises(ops.OperationError):
        ops.change_status(session, op, "active")
    ops.save_config(session, op, complete_config())
    ops.change_status(session, op, "active")
    assert op.status == "active"


@needs_db
def test_status_transitions(session):
    op = ops.create_operation(session, "A", complete_config())
    with pytest.raises(ops.OperationError):
        ops.change_status(session, op, "paused")  # rascunho não pausa
    for status in ("active", "paused", "active", "archived"):
        ops.change_status(session, op, status)
    with pytest.raises(ops.OperationError):
        ops.change_status(session, op, "active")  # arquivada não volta


@needs_db
def test_archived_is_read_only(session):
    op = ops.create_operation(session, "A")
    ops.change_status(session, op, "archived")
    with pytest.raises(ops.OperationError):
        ops.save_config(session, op, complete_config())


@needs_db
def test_active_operation_refuses_broken_flow(session):
    op = ops.create_operation(session, "A", complete_config())
    ops.change_status(session, op, "active")
    with pytest.raises(ops.OperationError):
        ops.save_config(session, op, ops.default_config())


@needs_db
def test_duplicate_copies_config_as_draft(session):
    op = ops.create_operation(session, "A", complete_config())
    ops.change_status(session, op, "active")
    dup = ops.duplicate_operation(session, op)
    assert dup.status == "draft" and dup.name == "A (cópia)"
    assert ops.current_config(session, dup).config == complete_config()


@needs_db
def test_actions_are_logged(session):
    op = ops.create_operation(session, "A", complete_config())
    ops.change_status(session, op, "active")
    actions = session.scalars(select(m.Event.action).where(m.Event.operation_id == op.id)).all()
    assert actions == ["created", "status_changed"]


# --- telas -----------------------------------------------------------------------------


@needs_db
def test_web_flow(logged_client, session):
    response = logged_client.post("/operacoes", data={"name": "Memes"}, follow_redirects=False)
    assert response.status_code == 303
    detail_url = response.headers["location"]
    page = logged_client.get(detail_url)
    assert "Memes" in page.text and "Rascunho" in page.text
    assert "Adicione ao menos uma fonte de busca na Pesca." in page.text

    # Ativar com erro: recusado com mensagem.
    op_id = int(detail_url.rsplit("/", 1)[1])
    refused = logged_client.post(f"/operacoes/{op_id}/status", data={"acao": "active"})
    assert "O fluxo tem erros" in refused.text
    assert "Rascunho" in refused.text

    # Salvar o fluxo pela API do canvas e ativar.
    saved = logged_client.post(f"/operacoes/{op_id}/config", json=complete_config())
    assert saved.status_code == 200
    assert saved.json() == {"version": 2, "issues": []}
    logged_client.post(f"/operacoes/{op_id}/status", data={"acao": "active"})
    listing = logged_client.get("/operacoes?status=active")
    assert "Memes" in listing.text and "Play" in listing.text

    # Histórico mostra as duas versões.
    history = logged_client.get(f"{detail_url}?aba=historico&v=1")
    assert "v2 (vigente)" in history.text and "Configuração v1" in history.text


@needs_db
def test_web_rejects_broken_flow_on_active_operation(logged_client, session):
    op = ops.create_operation(session, "A", complete_config())
    ops.change_status(session, op, "active")
    session.commit()
    broken = copy.deepcopy(complete_config())
    broken["edges"] = []
    response = logged_client.post(f"/operacoes/{op.id}/config", json=broken)
    assert response.status_code == 409


@needs_db
def test_unknown_operation_is_404(logged_client, session):
    assert logged_client.get("/operacoes/999999").status_code == 404


def test_operations_require_login(client):
    response = client.get("/operacoes", follow_redirects=False)
    assert response.headers["location"] == "/login"
    response = client.post("/operacoes/1/config", json={}, follow_redirects=False)
    assert response.status_code == 303


def test_database_down_page(settings):
    from fastapi.testclient import TestClient

    from tests.conftest import github_login
    from web.main import create_app

    app = create_app(settings.model_copy(update={"database_url": "postgresql://x:y@127.0.0.1:1/z"}))
    client = TestClient(app)
    from tests.conftest import fake_github

    app.state.http_client_factory = fake_github()
    github_login(client)
    response = client.get("/operacoes")
    assert response.status_code == 503
    assert "Banco indisponível" in response.text
