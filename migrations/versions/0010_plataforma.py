"""Plataforma: ambiente isolado por operação e servidores com o agente (Tasks 32 e 33).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-21 02:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ts = sa.DateTime(timezone=True)
    op.create_table(
        "operation_runtimes",
        sa.Column("operation_id", sa.BigInteger(), nullable=False),
        sa.Column("desired_state", sa.String(20), server_default="stopped", nullable=False),
        sa.Column("cpu_limit", sa.Float(), server_default="1", nullable=False),
        sa.Column("memory_mb", sa.Integer(), server_default="1024", nullable=False),
        sa.Column("version", sa.String(40), server_default="", nullable=False),
        sa.Column("actual_state", sa.String(20), server_default="absent", nullable=False),
        sa.Column("actual_version", sa.String(40)),
        sa.Column("containers", postgresql.JSONB()),
        sa.Column("usage", postgresql.JSONB()),
        sa.Column("logs", postgresql.JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column("restart_requested_at", ts),
        sa.Column("restart_done_at", ts),
        sa.Column("backup_requested_at", ts),
        sa.Column("backup_done_at", ts),
        sa.Column("backups", postgresql.JSONB()),
        sa.Column("restore_request", postgresql.JSONB()),
        sa.Column("restore_done_at", ts),
        sa.Column("reported_at", ts),
        sa.Column("created_at", ts, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", ts, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            ondelete="CASCADE",
            name=op.f("fk_operation_runtimes_operation_id_operations"),
        ),
        sa.PrimaryKeyConstraint("operation_id", name=op.f("pk_operation_runtimes")),
        sa.CheckConstraint(
            "desired_state IN ('running', 'stopped')",
            name=op.f("ck_operation_runtimes_desired_state"),
        ),
        sa.CheckConstraint(
            "cpu_limit > 0 AND memory_mb >= 256", name=op.f("ck_operation_runtimes_limits")
        ),
    )
    op.create_table(
        "infra_servers",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("agent_version", sa.String(40)),
        sa.Column("cpu_count", sa.Integer()),
        sa.Column("mem_total_mb", sa.Integer()),
        sa.Column("mem_used_mb", sa.Integer()),
        sa.Column("disk_total_gb", sa.Float()),
        sa.Column("disk_free_gb", sa.Float()),
        sa.Column("load1", sa.Float()),
        sa.Column("versions", postgresql.JSONB()),
        sa.Column("info", postgresql.JSONB()),
        sa.Column("last_seen", ts),
        sa.Column("created_at", ts, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_infra_servers")),
        sa.UniqueConstraint("name", name=op.f("uq_infra_servers_name")),
    )


def downgrade() -> None:
    op.drop_table("infra_servers")
    op.drop_table("operation_runtimes")
