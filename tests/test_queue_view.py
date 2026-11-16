"""Fila (Task 8): filtros, liberação de permissão em lote com resumo e Dashboard (Task 25)."""

import httpx
from sqlalchemy import select

import core.models as m
from core import items as it
from core import operations as ops
from tests.test_fishing import (  # noqa: F401
    SETTINGS,
    factory,
    items_by_external,
    media,
    post,
    reddit_with,
    run,
    setup_operation,
)
from tests.test_render_job import pytestmark  # noqa: F401


def give_permission(factory, op_id):
    with factory() as s:
        op = s.get(m.Operation, op_id)
        config = ops.current_config(s, op).config
        for node in config["nodes"]:
            if node["type"] == "source":
                node["config"]["permission_note"] = "autorizado pelo criador"
        ops.save_config(s, op, config)
        s.commit()


def test_release_pending_permission_downloads_and_renders(factory, media, tmp_path):  # noqa: F811
    from worker.collect import run_release

    op_id = setup_operation(factory, permission="")
    fake = reddit_with(media, [("p1", "academia supino", media["a"])])
    ex_id, _, storage = run(factory, op_id, fake, tmp_path, target_x=1)
    item = items_by_external(factory, ex_id)["p1"]
    assert item.status == "pending_permission"
    with factory() as s:
        summary = it.summary(s, [item.id], "release")
        assert summary["skipped"] and "permissão registrada" in summary["skipped"][0][1]
    give_permission(factory, op_id)
    with factory() as s:
        assert it.apply(s, [item.id], "release") == (1, 0)
        s.commit()
        job = s.scalars(select(m.Job).where(m.Job.idempotency_key == f"release:{item.id}")).one()
        assert job.type == "collect" and job.payload == {"release_item": item.id}
    kwargs = {"client": httpx.Client(transport=httpx.MockTransport(fake)), "sleep": lambda s: None}
    assert run_release(factory, item.id, SETTINGS, storage, kwargs) == "eligible"
    with factory() as s:
        item = s.get(m.Item, item.id)
        assert item.status == "eligible" and storage.exists(item.original_file)
        assert s.scalars(select(m.Job).where(m.Job.type == "render")).one().ref_id == item.id


def test_queue_page_filters_and_confirms(factory, logged_client, tmp_path):  # noqa: F811
    op_id = setup_operation(factory, permission="")
    fake = reddit_with({}, [("p1", "academia", None), ("p2", "academia nsfw", None)])
    ex_id, _, _ = run(factory, op_id, fake, tmp_path, target_x=2)
    items = items_by_external(factory, ex_id)
    page = logged_client.get(f"/fila?op={op_id}&etapa=pesca")
    assert "sem permissão" in page.text and f'value="{items["p1"].id}"' in page.text
    assert f'value="{items["p2"].id}"' not in page.text  # rejeitado não está na pesca
    confirm = logged_client.post(
        "/fila/lote", data={"acao": "priority_high", "item_ids": [items["p1"].id, items["p2"].id]}
    )
    assert "1</strong> itens entram" in confirm.text and "descartado" in confirm.text
    done = logged_client.post(
        "/fila/lote",
        data={"acao": "priority_high", "item_ids": [items["p1"].id], "confirmar": "true"},
    )
    assert "Prioridade alta: 1 itens." in done.text
    with factory() as s:
        assert s.get(m.Item, items["p1"].id).priority == "high"


def test_dashboard_counts_link_to_filtered_queues(factory, logged_client, tmp_path):  # noqa: F811
    op_id = setup_operation(factory, permission="")
    run(factory, op_id, reddit_with({}, [("p1", "academia", None)]), tmp_path, target_x=1)
    page = logged_client.get("/").text
    block = page.split('href="/fila?estado=pending_permission"')[1][:200]
    assert '<span class="num">1</span>' in block
    assert "Operações ativas" in page and "Erros recentes" in page
