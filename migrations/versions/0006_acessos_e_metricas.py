"""Chaves das redes pela interface e métricas dos envios (Task 28).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-20 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_credentials",
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("value_encrypted", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_app_credentials")),
    )
    op.add_column(
        "publish_jobs",
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "publish_jobs", sa.Column("metrics_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("publish_jobs", "metrics_at")
    op.drop_column("publish_jobs", "metrics")
    op.drop_table("app_credentials")
