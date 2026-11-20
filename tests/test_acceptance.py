"""Critérios de aceitação da v2.1 (Task 26.1) e reprodutibilidade do render (26.4).

Os critérios já cobertos em outros arquivos estão mapeados em docs/aceitacao.md; aqui ficam os
que precisavam de um teste próprio, com o número do critério no nome.
"""

import subprocess
from datetime import timedelta

from sqlalchemy import select

import core.models as m
from core import distribution as dist
from core import items as it
from networks.base import PublishFailed
from tests.test_publish import (  # noqa: F401
    NOW,
    FakeAdapter,
    batch,
    jobs,
    make_world,
    run_publish,
    settings,
)
from tests.test_render_job import factory, pytestmark, run, setup, state, storage  # noqa: F401


def test_c03_same_records_in_operation_and_general_queue(factory, storage, tmp_path):
    op_a, items_a, _ = make_world(factory, storage, tmp_path, n_items=2)
    with factory() as s:
        general = {i.id for i in it.list_items(s)}
        of_op = {i.id for i in it.list_items(s, operation_id=op_a)}
    assert of_op == set(items_a) and of_op <= general


def test_c05_only_selected_videos_are_distributed(factory, storage, tmp_path):
    op_id, items, accounts = make_world(factory, storage, tmp_path, n_items=3)
    with factory() as s:
        b, _ = dist.create_batch(
            s,
            s.get(m.Operation, op_id),
            item_ids=[items[1]],
            account_ids=accounts,
            request_key="sel",
            now=NOW,
        )
        s.commit()
        renders = {j.render_id for j in jobs(factory, b.id)}
        assert renders == {s.get(m.Item, items[1]).approved_render_id}


def test_c06_interval_zero_releases_all_within_limits(factory, storage, tmp_path):
    op_id, _, accounts = make_world(
        factory, storage, tmp_path, n_items=5, n_accounts=1, daily_limit=3
    )
    b = batch(factory, op_id, accounts, mode="all", interval_min=0, first_immediate=True)
    js = jobs(factory, b)
    today = [j for j in js if j.planned_at and j.planned_at == NOW]
    assert len(today) == 3  # todos de uma vez, até o limite diário
    assert all(j.planned_at > NOW for j in js if j not in today and j.planned_at)


def test_c08_first_immediate_changes_first_slot_per_account(factory, storage, tmp_path):
    op_id, _, accounts = make_world(factory, storage, tmp_path, n_items=1)
    first = jobs(
        factory,
        batch(
            factory,
            op_id,
            accounts,
            mode="all",
            interval_min=30,
            first_immediate=True,
            request_key="a",
        ),
    )
    with factory() as s:
        for j in s.scalars(select(m.PublishJob)):
            s.delete(j)
        s.commit()
    later = jobs(
        factory,
        batch(
            factory,
            op_id,
            accounts,
            mode="all",
            interval_min=30,
            first_immediate=False,
            request_key="b",
        ),
    )
    assert {j.planned_at for j in first} == {NOW}
    assert {j.planned_at for j in later} == {NOW + timedelta(minutes=30)}


def test_c09_one_job_per_video_and_account(factory, storage, tmp_path):
    op_id, items, accounts = make_world(factory, storage, tmp_path, n_items=2, n_accounts=3)
    js = jobs(
        factory, batch(factory, op_id, accounts, mode="all", interval_min=0, first_immediate=True)
    )
    assert len(js) == 6 and len({(j.render_id, j.account_id) for j in js}) == 6


def test_c10_failure_does_not_repeat_successes(factory, storage, settings, tmp_path):  # noqa: F811
    op_id, _, accounts = make_world(factory, storage, tmp_path, n_items=1)
    batch(factory, op_id, accounts, mode="all", interval_min=0, first_immediate=True)
    ok, bad = jobs(factory)
    adapter = FakeAdapter([None, PublishFailed("recusado")])
    assert run_publish(factory, storage, settings, adapter, ok.id) == "published"
    assert run_publish(factory, storage, settings, adapter, bad.id) == "failed"
    with factory() as s:
        dist.resolve_uncertain(s, s.get(m.PublishJob, bad.id), "retry")
        s.commit()
    assert run_publish(factory, storage, settings, adapter, bad.id) == "published"
    assert run_publish(factory, storage, settings, adapter, ok.id) is None
    assert len(adapter.calls) == 3  # o sucesso nunca foi reenviado


def video_md5(path) -> str:
    out = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(path), "-map", "0:v", "-f", "md5", "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def test_render_is_reproducible(factory, storage, tmp_path):  # noqa: F811
    """26.4: mesmo original + mesma versão de preset e máscara = mesmos quadros."""
    from core import approval

    _, item_id, _ = setup(factory, storage, tmp_path)
    run(factory, storage, item_id)
    with factory() as s:
        approval.request_new_version(s, s.get(m.Item, item_id))
        s.commit()
    _, renders = state(factory, item_id)
    run(factory, storage, item_id, payload={"config_id": renders[0].config_id})
    _, renders = state(factory, item_id)
    assert [r.version for r in renders] == [1, 2] and renders[0].config_id == renders[1].config_id
    paths = []
    for r in renders:
        path = tmp_path / f"r{r.version}.mp4"
        storage.get_file(r.output_file, path)
        paths.append(path)
    assert video_md5(paths[0]) == video_md5(paths[1])
