"""Migrações do banco pela interface ou pela linha de comando (Task 27.2).

O botão "Aplicar migrações" da tela Acessos chama `upgrade`. Um advisory lock do Postgres
garante que só um processo migre por vez (interface na Vercel e serviço `migrar` da VPS).
"""

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parent.parent
LOCK_ID = 841_337_2026


def alembic_config(url: str | None = None):
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    if url:
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def status(engine: Engine) -> dict:
    """Revisão aplicada no banco e a mais nova do código."""
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    return {"current": current, "head": head, "up_to_date": current == head}


def upgrade(engine: Engine) -> dict:
    from alembic import command

    url = engine.url.render_as_string(hide_password=False)
    with engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:id)"), {"id": LOCK_ID})
        try:
            command.upgrade(alembic_config(url), "head")
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
            conn.commit()
    return status(engine)
