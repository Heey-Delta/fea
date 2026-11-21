"""Versão do código que cada worker roda, para avisar quando falta atualizar.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-20 21:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("worker_heartbeats", sa.Column("version", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("worker_heartbeats", "version")
