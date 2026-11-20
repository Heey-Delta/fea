"""Contador de uso do Cloudflare R2 e preferências da ferramenta.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-20 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "r2_usage",
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("metric", sa.String(length=20), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("month", "metric", name=op.f("pk_r2_usage")),
    )
    op.create_table(
        "app_settings",
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_app_settings")),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_table("r2_usage")
