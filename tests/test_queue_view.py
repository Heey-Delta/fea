"""Fila (Task 8): filtros, liberação de permissão em lote com resumo e Dashboard (Task 25)."""

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


def test_itens_antigos_sem_permissao_podem_ser_liberados(factory, media, tmp_path):  # noqa: F811
    """Itens parados antes da remoção da trava saem com "Liberar", sem exigir nota."""
    op_id = setup_operation(factory, permission="")
    fake = reddit_with(media, [("p1", "academia supino", media["a"])])
    ex_id, _, _ = run(factory, op_id, fake, tmp_path, target_x=1)
    item = items_by_external(factory, ex_id)["p1"]
    with factory() as s:
        s.get(m.Item, item.id).status = "pending_permission"
        s.commit()
    with factory() as s:
        assert it.summary(s, [item.id], "release")["skipped"] == []
        assert it.apply(s, [item.id], "release") == (1, 0)
        s.commit()
        job = s.scalars(select(m.Job).where(m.Job.idempotency_key == f"release:{item.id}")).one()
        assert job.type == "collect" and job.payload == {"release_item": item.id}


def test_queue_page_filters_and_confirms(factory, logged_client, tmp_path):  # noqa: F811
    op_id = setup_operation(factory, permission="")
    fake = reddit_with({}, [("p1", "academia", None), ("p2", "academia nsfw", None)])
    ex_id, _, _ = run(factory, op_id, fake, tmp_path, target_x=2)
    items = items_by_external(factory, ex_id)
    with factory() as s:  # p1 na pesca (antes ficava parado sem permissão; sem mídia é descartado)
        s.get(m.Item, items["p1"].id).status = "eligible"
        s.commit()
    page = logged_client.get(f"/fila?op={op_id}&etapa=pesca")
    assert f'value="{items["p1"].id}"' in page.text
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
    assert 'href="/fila?estado=pending_permission"' not in page  # trava de permissão removida
    assert "Operações ativas" in page and "Falhas e alertas recentes" in page
