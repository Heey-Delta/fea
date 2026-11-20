"""Play diário e reposição de estoque (Tasks 6.8 e 6.9)."""

import os
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

import core.models as m
from core import automation
from core import operations as ops
from tests.test_operations import complete_config

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL não definida")
SP = ZoneInfo("America/Sao_Paulo")


def at_sp(hour, minute=0, day=16):
    return datetime(2026, 11, day, hour, minute, tzinfo=SP).astimezone(UTC)


def test_parse_hhmm():
    assert automation.parse_hhmm("06:30").hour == 6
    assert automation.parse_hhmm("") is None and automation.parse_hhmm("25:99") is None


def test_next_daily_play_rolls_to_tomorrow():
    auto = {"daily_play_at": "06:00"}
    assert automation.next_daily_play(auto, SP, at_sp(5)).hour == 6
    assert automation.next_daily_play(auto, SP, at_sp(7)).day == 17
    assert automation.next_daily_play({}, SP, at_sp(7)) is None


@pytest.fixture
def factory():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from core.db import sqlalchemy_url

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", sqlalchemy_url(DATABASE_URL))
    command.upgrade(cfg, "head")
    engine = create_engine(sqlalchemy_url(DATABASE_URL))
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE operations, jobs, events RESTART IDENTITY CASCADE"))
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def make_op(factory, **auto):
    config = complete_config()
    config["automation"].update(auto)
    with factory() as s:
        op = ops.create_operation(s, "Auto", config)
        ops.change_status(s, op, "active")
        s.commit()
        return op.id


def triggers(factory):
    with factory() as s:
        return [e.trigger for e in s.scalars(select(m.Execution).order_by(m.Execution.id))]


def finish_all(factory):
    with factory() as s:
        for ex in s.scalars(select(m.Execution)):
            ex.status = "completed"
        s.commit()


@needs_db
def test_daily_play_runs_once_after_its_time(factory):
    make_op(factory, daily_play_at="06:00")
    with factory() as s:
        assert automation.automation_tick(s, at_sp(5, 59)) == []
        assert len(automation.automation_tick(s, at_sp(6, 0))) == 1
        s.commit()
    finish_all(factory)
    with factory() as s:
        assert automation.automation_tick(s, at_sp(9)) == []  # já rodou hoje
        assert len(automation.automation_tick(s, at_sp(6, day=17))) == 1  # amanhã de novo
        s.commit()
    assert triggers(factory) == ["scheduled", "scheduled"]


@needs_db
def test_nothing_runs_while_an_execution_is_open(factory):
    make_op(factory, daily_play_at="06:00")
    with factory() as s:
        automation.automation_tick(s, at_sp(6))
        s.commit()
    with factory() as s:
        assert automation.automation_tick(s, at_sp(6, day=17)) == []


@needs_db
def test_stock_refill_asks_for_the_missing_amount(factory):
    op_id = make_op(factory, stock_enabled=True, daily_target=10, stock_min_days=3)
    with factory() as s:
        source = s.scalars(select(m.Source)).one()
        for i in range(12):
            s.add(
                m.Item(
                    operation_id=op_id,
                    source_id=source.id,
                    external_id=f"p{i}",
                    status="awaiting_approval",
                )
            )
        s.add(
            m.Item(
                operation_id=op_id,
                source_id=source.id,
                external_id="reserva",
                status="eligible",
                status_reason="reserva",
            )
        )
        s.commit()
        assert automation.ready_stock(s, op_id) == 12
        started = automation.automation_tick(s, at_sp(10))
        s.commit()
        ex = s.get(m.Execution, started[0])
        assert (ex.trigger, ex.target_x) == ("stock", 18)


@needs_db
def test_full_stock_does_nothing(factory):
    op_id = make_op(factory, stock_enabled=True, daily_target=1, stock_min_days=1)
    with factory() as s:
        source = s.scalars(select(m.Source)).one()
        s.add(m.Item(operation_id=op_id, source_id=source.id, external_id="p", status="approved"))
        s.commit()
        assert automation.automation_tick(s, at_sp(10)) == []


@needs_db
def test_inactive_operations_are_ignored(factory):
    op_id = make_op(factory, daily_play_at="06:00")
    with factory() as s:
        ops.change_status(s, s.get(m.Operation, op_id), "paused")
        s.commit()
        assert automation.automation_tick(s, at_sp(7)) == []


def test_buscador_runs_automation_every_minute():
    from worker.handlers import ROLE_PERIODIC

    interval, _ = ROLE_PERIODIC["buscador"]["automation"]
    assert interval == 60.0
