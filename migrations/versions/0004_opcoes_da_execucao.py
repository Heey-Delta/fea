"""Fontes escolhidas e estatísticas da busca na execução (Task 6).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-16 15:35:39.239751
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("executions", sa.Column("source_ids", sa.ARRAY(sa.BigInteger()), nullable=True))
    op.add_column(
        "executions", sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("executions", "stats")
    op.drop_column("executions", "source_ids")
