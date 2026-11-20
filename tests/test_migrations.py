import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from core.db import sqlalchemy_url

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL não definida")


def alembic_config() -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", sqlalchemy_url(DATABASE_URL))
    return config


def test_upgrade_and_downgrade():
    config = alembic_config()
    command.upgrade(config, "head")
    engine = create_engine(sqlalchemy_url(DATABASE_URL))
    try:
        assert "alembic_version" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_url_normalization():
    assert sqlalchemy_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert sqlalchemy_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert sqlalchemy_url("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
