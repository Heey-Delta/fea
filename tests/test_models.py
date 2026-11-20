"""Banco: as 14 tabelas do MVP mais app_credentials, modelos x migração e constraints (Task 2)."""

import os

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import core.models as m
from core.db import Base, sqlalchemy_url

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL não definida")

TABLES = {
    "operations",
    "operation_configs",
    "sources",
    "accounts",
    "operation_accounts",
    "executions",
    "items",
    "renders",
    "mask_assets",
    "mask_versions",
    "batches",
    "publish_jobs",
    "jobs",
    "events",
    "app_credentials",
    "worker_heartbeats",
    "r2_usage",
    "app_settings",
}


@pytest.fixture(scope="module")
def engine():
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", sqlalchemy_url(DATABASE_URL))
    command.upgrade(config, "head")
    eng = create_engine(sqlalchemy_url(DATABASE_URL))
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with engine.connect() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(sorted(TABLES)) + " RESTART IDENTITY CASCADE"))
        conn.commit()
    with Session(engine) as s:
        yield s
        s.rollback()


def test_fourteen_tables(engine):
    tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert tables == TABLES


def test_migration_matches_models(engine):
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def make_operation(session: Session) -> m.Operation:
    op = m.Operation(name="Operação A")
    session.add(op)
    session.flush()
    config = m.OperationConfig(operation_id=op.id, version=1, config={"nodes": [], "edges": []})
    session.add(config)
    session.flush()
    op.current_config_id = config.id
    session.flush()
    return op


def make_item(session: Session, op: m.Operation, external_id: str = "abc") -> m.Item:
    source = session.query(m.Source).filter_by(operation_id=op.id).first()
    if source is None:
        source = m.Source(operation_id=op.id, type="reddit", reference="r/teste")
        session.add(source)
        session.flush()
    item = m.Item(operation_id=op.id, source_id=source.id, external_id=external_id)
    session.add(item)
    session.flush()
    return item


def test_defaults_and_circular_links(session):
    op = make_operation(session)
    item = make_item(session, op)
    render = m.Render(item_id=item.id, version=1, config_id=op.current_config_id)
    session.add(render)
    session.flush()
    item.approved_render_id = render.id
    item.approved_account_ids = [1, 2]
    item.approved_by = "auto"
    session.flush()
    session.refresh(op)
    session.refresh(item)
    assert op.status == "draft"
    assert item.status == "discovered" and item.priority == "normal" and item.score == 0
    assert item.approved_account_ids == [1, 2]


def test_invalid_status_is_rejected(session):
    session.add(m.Operation(name="X", status="ligada"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_invalid_publish_status_is_rejected(session):
    op = make_operation(session)
    item = make_item(session, op)
    render = m.Render(item_id=item.id, version=1, config_id=op.current_config_id)
    account = m.Account(platform="youtube", name="Conta A", external_id="UC1")
    batch = m.Batch(operation_id=op.id, request_key="k1", interval_min=10)
    session.add_all([render, account, batch])
    session.flush()
    session.add(
        m.PublishJob(batch_id=batch.id, render_id=render.id, account_id=account.id, status="ok")
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_same_external_item_twice_is_rejected(session):
    op = make_operation(session)
    make_item(session, op, "post1")
    with pytest.raises(IntegrityError):
        make_item(session, op, "post1")


def test_same_render_to_same_account_twice_is_rejected(session):
    op = make_operation(session)
    item = make_item(session, op)
    render = m.Render(item_id=item.id, version=1, config_id=op.current_config_id)
    account = m.Account(platform="youtube", name="Conta A", external_id="UC1")
    batch = m.Batch(operation_id=op.id, request_key="k1", interval_min=10)
    session.add_all([render, account, batch])
    session.flush()
    for _ in range(2):
        session.add(m.PublishJob(batch_id=batch.id, render_id=render.id, account_id=account.id))
    with pytest.raises(IntegrityError):
        session.flush()


def test_batch_request_key_is_unique(session):
    op = make_operation(session)
    session.add_all(
        [
            m.Batch(operation_id=op.id, request_key="dup", interval_min=0),
            m.Batch(operation_id=op.id, request_key="dup", interval_min=0),
        ]
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_job_idempotency_key_is_unique(session):
    session.add_all(
        [
            m.Job(type="collect", idempotency_key="collect:1"),
            m.Job(type="collect", idempotency_key="collect:1"),
        ]
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_config_versions_are_unique_per_operation(session):
    op = make_operation(session)
    session.add(m.OperationConfig(operation_id=op.id, version=1, config={}))
    with pytest.raises(IntegrityError):
        session.flush()


def test_mask_versions_are_unique(session):
    op = make_operation(session)
    mask = m.MaskAsset(operation_id=op.id, name="Moldura")
    session.add(mask)
    session.flush()
    for _ in range(2):
        session.add(
            m.MaskVersion(
                mask_id=mask.id,
                version=1,
                file_key="k",
                width=1080,
                height=1920,
                has_alpha=True,
                checksum="0" * 64,
            )
        )
    with pytest.raises(IntegrityError):
        session.flush()


def test_negative_daily_limit_is_rejected(session):
    session.add(m.Account(platform="youtube", name="A", external_id="UC2", daily_limit=-1))
    with pytest.raises(IntegrityError):
        session.flush()


def test_states_match_constraints():
    """Toda lista de estados de core.states aparece numa constraint do modelo."""
    from core import states

    checks = " ".join(
        str(c.sqltext)
        for table in Base.metadata.tables.values()
        for c in table.constraints
        if hasattr(c, "sqltext")
    )
    for values in (states.ITEM_STATUS, states.PUBLISH_STATUS, states.JOB_TYPE):
        for value in values:
            assert f"'{value}'" in checks
