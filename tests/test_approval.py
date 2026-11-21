"""Aprovação (Task 18): regras, lote, nova versão e telas."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import core.models as m
from core import approval as ap
from core.operations import OperationError
from tests.conftest import fake_github, github_login
from tests.test_render_job import factory, pytestmark, run, setup, state, storage  # noqa: F401


@pytest.fixture
def rendered(factory, storage, tmp_path):  # noqa: F811
    op_id, item_id, account_id = setup(factory, storage, tmp_path)
    run(factory, storage, item_id)
    return op_id, item_id, account_id


def test_approve_binds_render_and_accounts(factory, rendered):  # noqa: F811
    _, item_id, account_id = rendered
    with factory() as s:
        item = s.get(m.Item, item_id)
        render = ap.approve(s, item, [account_id, account_id])
        s.commit()
    item, renders = state(factory, item_id)
    assert (item.status, item.approved_by) == ("approved", "manual")
    assert item.approved_render_id == render.id == renders[-1].id
    assert item.approved_account_ids == [account_id]


def test_approve_needs_accounts_and_waiting_status(factory, rendered):  # noqa: F811
    _, item_id, account_id = rendered
    with factory() as s:
        item = s.get(m.Item, item_id)
        with pytest.raises(OperationError, match="conta"):
            ap.approve(s, item, [])
        ap.approve(s, item, [account_id])
        with pytest.raises(OperationError, match="aguardando"):
            ap.approve(s, item, [account_id])


def test_fonte_sem_nota_de_permissao_aprova_normalmente(factory, storage, tmp_path):  # noqa: F811
    _, item_id, account_id = setup(factory, storage, tmp_path, permission="")
    run(factory, storage, item_id)
    with factory() as s:
        item = s.get(m.Item, item_id)
        assert ap.can_approve(s, item) is None
        ap.approve(s, item, [account_id])
        assert item.status == "approved"


def test_reject_and_new_version(factory, rendered):  # noqa: F811
    _, item_id, _ = rendered
    with factory() as s:
        item = s.get(m.Item, item_id)
        job_id = ap.request_new_version(s, item)
        s.commit()
        job = s.get(m.Job, job_id)
        assert job.type == "render" and job.payload["config_id"] and job.priority == 2
        ap.reject(s, item, "fora do padrão")
        s.commit()
    item, _ = state(factory, item_id)
    assert (item.status, item.status_reason) == ("rejected", "fora do padrão")


def test_bulk_reports_who_was_left_out(factory, storage, tmp_path, rendered):  # noqa: F811
    _, item_id, account_id = rendered
    with factory() as s:
        done, skipped = ap.bulk(s, [item_id, 999999], "approve", [account_id])
        s.commit()
    assert done == 1 and skipped == []
    with factory() as s:
        done, skipped = ap.bulk(s, [item_id], "approve", [account_id])
    assert done == 0 and "aguardando" in skipped[0]


def app_client(settings, storage):  # noqa: F811
    from web.main import create_app

    app = create_app(settings)
    app.state.storage = storage
    app.state.http_client_factory = fake_github()
    client = TestClient(app)
    github_login(client)
    return client


def test_queue_and_item_pages(settings, factory, storage, rendered):  # noqa: F811
    op_id, item_id, account_id = rendered
    client = app_client(settings, storage)
    page = client.get(f"/aprovacao?op={op_id}")
    assert f'value="{item_id}"' in page.text and "Canal A" in page.text
    assert "<video" in page.text and "/arquivos/operations/" in page.text
    video = client.get(page.text.split('<video src="')[1].split('"')[0])
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4"
    detail = client.get(f"/aprovacao/{item_id}")
    assert "resolução e proporção" in detail.text and "Permissão" not in detail.text
    approved = client.post(f"/aprovacao/{item_id}/aprovar", data={"account_ids": [account_id]})
    assert "Vídeo aprovado." in approved.text
    assert "Nada aguardando aprovação" in client.get("/aprovacao").text


def test_bulk_from_the_queue(settings, factory, storage, rendered):  # noqa: F811
    _, item_id, _ = rendered
    client = app_client(settings, storage)
    response = client.post(
        "/aprovacao/lote", data={"acao": "reject", "item_ids": [item_id], "motivo": "não"}
    )
    assert "1 vídeos rejeitados." in response.text
    with factory() as s:
        assert s.scalar(select(m.Item.status).where(m.Item.id == item_id)) == "rejected"


def test_new_version_button(settings, factory, storage, rendered):  # noqa: F811
    _, item_id, _ = rendered
    client = app_client(settings, storage)
    response = client.post(f"/aprovacao/{item_id}/nova-versao")
    assert "Nova versão na fila do Editor" in response.text
