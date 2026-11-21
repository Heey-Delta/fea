"""Estado ao vivo das operações (rodinha, estágios, erro) e os gráficos do dashboard."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

import core.models as m
from core import dashboard as dash
from core import live
from tests.conftest import fake_github, github_login
from tests.test_publish import batch, make_world
from tests.test_render_job import factory, pytestmark, storage  # noqa: F401


def add_job(s, type_, status, op_id=None, ref_id=None, last_error=None, key=None):
    job = m.Job(
        type=type_,
        status=status,
        operation_id=op_id,
        ref_id=ref_id,
        idempotency_key=key or f"{type_}:{status}:{op_id}:{ref_id}",
        last_error=last_error,
    )
    s.add(job)
    s.flush()
    return job


def test_estagios_fila_erro_e_publicacao_da_operacao_certa(factory, storage, tmp_path):  # noqa: F811
    op_id, items, accounts = make_world(factory, storage, tmp_path, n_items=1, n_accounts=1)
    batch(factory, op_id, accounts, interval_min=0)
    with factory() as s:
        pj = s.scalars(select(m.PublishJob)).one()
        add_job(s, "collect", "running", op_id)
        add_job(s, "render", "queued", op_id, last_error="FFmpeg falhou: memória")
        add_job(s, "publish", "running", ref_id=pj.id)  # publicação não guarda a operação
        add_job(s, "cleanup", "running")  # tarefa sem operação: ignorada
        s.commit()
        state = live.operations_live(s)
    entry = state[op_id]
    assert entry.stages == {"busca": "running", "edicao": "queued", "publicacao": "running"}
    assert entry.running == ["Buscando", "Publicando"] and entry.active
    assert entry.error.startswith("Tentando de novo: FFmpeg falhou")


def test_falha_antiga_some_e_fonte_com_erro_aparece(factory, storage, tmp_path):  # noqa: F811
    op_id, _, _ = make_world(factory, storage, tmp_path, n_items=1, n_accounts=1)
    now = datetime.now(UTC)
    with factory() as s:
        old = add_job(s, "render", "failed", op_id, last_error="antiga", key="old")
        old.updated_at = now - timedelta(hours=7)
        s.commit()
        assert op_id not in live.operations_live(s, now=now)
        s.scalars(select(m.Source)).one().status = "error"
        s.commit()
        entry = live.operations_live(s, now=now)[op_id]
    assert entry.error.startswith("Fonte com erro") and not entry.active


def test_rota_ao_vivo_e_lista_mostram_rodinha_estagios_e_erro(factory, storage, tmp_path, settings):  # noqa: F811
    from fastapi.testclient import TestClient

    from web.main import create_app

    op_id, _, _ = make_world(factory, storage, tmp_path, n_items=1, n_accounts=1)
    with factory() as s:
        add_job(s, "collect", "running", op_id)
        add_job(s, "render", "failed", op_id, last_error="sem espaço")
        s.commit()
    app = create_app(settings)
    app.state.http_client_factory = fake_github()
    client = TestClient(app)
    github_login(client)
    data = client.get(f"/operacoes/ao-vivo?ids={op_id},999").json()
    assert data[str(op_id)]["running"] and data[str(op_id)]["error"]
    html = data[str(op_id)]["html"]
    assert 'class="spin"' in html and "Em execução" in html and "Buscando" in html
    assert "Falhou: sem espaço" in html
    assert data["999"] == {"html": data["999"]["html"], "running": False, "error": False}
    page = client.get("/operacoes").text
    assert f'data-live="{op_id}"' in page and "op-live-row err run" in page and "live.js" in page


def test_dashboard_tem_tres_graficos_e_lista_compacta(factory, storage, tmp_path, settings):  # noqa: F811
    from fastapi.testclient import TestClient

    from web.main import create_app

    op_id, _, accounts = make_world(factory, storage, tmp_path, n_items=2, n_accounts=1)
    now = datetime.now(UTC)
    batch(factory, op_id, accounts, interval_min=0)
    with factory() as s:
        for job in s.scalars(select(m.PublishJob)):
            job.status, job.published_at = "published", now - timedelta(days=1)
        s.commit()
        series = dash.published_by_day(s, now=now)
        funnel = dash.pipeline(s)
    assert len(series) == 14 and series[-2]["count"] == 2 and series[-2]["peak"]
    assert [p["key"] for p in funnel] == ["busca", "edicao", "aprovacao", "estoque", "agenda"]
    app = create_app(settings)
    app.state.http_client_factory = fake_github()
    client = TestClient(app)
    github_login(client)
    page = client.get("/").text
    assert page.count('class="card hero-card"') == 3
    assert "Publicados" in page and "Funil de vídeos" in page and "Saúde" in page
    assert '<svg class="viz-cols"' in page and 'class="viz-stack"' in page
    assert "Mais indicadores" in page and 'class="mini' in page
    assert "Publicados (24 h)" not in page.split("Mais indicadores")[1]  # já está no gráfico
