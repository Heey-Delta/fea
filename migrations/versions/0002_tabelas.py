"""As 14 tabelas da ferramenta (Task 2).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16 15:02:04.470525
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("token_encrypted", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="connected", nullable=False),
        sa.Column("daily_limit", sa.Integer(), server_default="3", nullable=False),
        sa.Column(
            "timezone", sa.String(length=64), server_default="America/Sao_Paulo", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('connected', 'error', 'paused', 'revoked')",
            name=op.f("ck_accounts_status_valid"),
        ),
        sa.CheckConstraint("daily_limit >= 0", name=op.f("ck_accounts_daily_limit_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
        sa.UniqueConstraint("platform", "external_id", name=op.f("uq_accounts_platform")),
    )
    op.create_table(
        "operations",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("current_config_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'archived')",
            name=op.f("ck_operations_status_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operations")),
    )
    op.create_table(
        "batches",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("operation_id", sa.BigInteger(), nullable=False),
        sa.Column("request_key", sa.String(length=100), nullable=False),
        sa.Column("mode", sa.String(length=20), server_default="rotation", nullable=False),
        sa.Column("automatic", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("interval_min", sa.Integer(), nullable=False),
        sa.Column("first_immediate", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("mode IN ('rotation', 'all')", name=op.f("ck_batches_mode_valid")),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'cancelled')", name=op.f("ck_batches_status_valid")
        ),
        sa.CheckConstraint("interval_min >= 0", name=op.f("ck_batches_interval_positive")),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("fk_batches_operation_id_operations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_batches")),
        sa.UniqueConstraint("request_key", name=op.f("uq_batches_request_key")),
    )
    op.create_index(op.f("ix_batches_operation_id"), "batches", ["operation_id"], unique=False)
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("entity", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("operation_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("fk_events_operation_id_operations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
    )
    op.create_index("ix_events_entity", "events", ["entity", "entity_id"], unique=False)
    op.create_index(op.f("ix_events_operation_id"), "events", ["operation_id"], unique=False)
    op.create_table(
        "mask_assets",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("operation_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("fk_mask_assets_operation_id_operations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mask_assets")),
    )
    op.create_index(
        op.f("ix_mask_assets_operation_id"), "mask_assets", ["operation_id"], unique=False
    )
    op.create_table(
        "operation_accounts",
        sa.Column("operation_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_operation_accounts_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("fk_operation_accounts_operation_id_operations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("operation_id", "account_id", name=op.f("pk_operation_accounts")),
    )
    op.create_index(
        op.f("ix_operation_accounts_account_id"), "operation_accounts", ["account_id"], unique=False
    )
    op.create_table(
        "operation_configs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("operation_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("fk_operation_configs_operation_id_operations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operation_configs")),
        sa.UniqueConstraint(
            "operation_id", "version", name=op.f("uq_operation_configs_operation_id")
        ),
    )
    op.create_index(
        op.f("ix_operation_configs_operation_id"),
        "operation_configs",
        ["operation_id"],
        unique=False,
    )
    op.create_table(
        "sources",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("operation_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("reference", sa.String(length=500), nullable=False),
        sa.Column("permission_note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="ok", nullable=False),
        sa.Column("cursor", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ok', 'error', 'paused')", name=op.f("ck_sources_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("fk_sources_operation_id_operations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
    )
    op.create_index(op.f("ix_sources_operation_id"), "sources", ["operation_id"], unique=False)
    op.create_table(
        "executions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("operation_id", sa.BigInteger(), nullable=False),
        sa.Column("config_id", sa.BigInteger(), nullable=False),
        sa.Column("trigger", sa.String(length=20), server_default="manual", nullable=False),
        sa.Column("target_x", sa.Integer(), nullable=False),
        sa.Column("search_budget", sa.Integer(), nullable=False),
        sa.Column("criteria", sa.String(length=20), server_default="recent", nullable=False),
        sa.Column("priority", sa.String(length=10), server_default="normal", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="running", nullable=False),
        sa.Column("shortfall_reason", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "criteria IN ('recent', 'heat')", name=op.f("ck_executions_criteria_valid")
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high')", name=op.f("ck_executions_priority_valid")
        ),
        sa.CheckConstraint(
            "status IN ('running', 'paused', 'completed', 'partial', 'cancelled')",
            name=op.f("ck_executions_status_valid"),
        ),
        sa.CheckConstraint(
            "trigger IN ('manual', 'scheduled', 'stock')", name=op.f("ck_executions_trigger_valid")
        ),
        sa.CheckConstraint("target_x > 0", name=op.f("ck_executions_target_x_positive")),
        sa.ForeignKeyConstraint(
            ["config_id"],
            ["operation_configs.id"],
            name=op.f("fk_executions_config_id_operation_configs"),
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("fk_executions_operation_id_operations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_executions")),
    )
    op.create_index(
        op.f("ix_executions_operation_id"), "executions", ["operation_id"], unique=False
    )
    op.create_table(
        "mask_versions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("mask_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_key", sa.Text(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("has_alpha", sa.Boolean(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["mask_id"],
            ["mask_assets.id"],
            name=op.f("fk_mask_versions_mask_id_mask_assets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mask_versions")),
        sa.UniqueConstraint("mask_id", "version", name=op.f("uq_mask_versions_mask_id")),
    )
    op.create_table(
        "items",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("operation_id", sa.BigInteger(), nullable=False),
        sa.Column("execution_id", sa.BigInteger(), nullable=True),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("author", sa.String(length=200), nullable=True),
        sa.Column("media_type", sa.String(length=20), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("duration_s", sa.Double(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("phash", sa.String(length=64), nullable=True),
        sa.Column("score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("priority", sa.String(length=10), server_default="normal", nullable=False),
        sa.Column("status", sa.String(length=30), server_default="discovered", nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("duplicate_of", sa.BigInteger(), nullable=True),
        sa.Column("original_file", sa.Text(), nullable=True),
        sa.Column("approved_render_id", sa.BigInteger(), nullable=True),
        sa.Column("approved_account_ids", sa.ARRAY(sa.BigInteger()), nullable=True),
        sa.Column("approved_by", sa.String(length=10), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delete_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("files_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "approved_by IS NULL OR approved_by IN ('manual', 'auto')",
            name=op.f("ck_items_approved_by_valid"),
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high')", name=op.f("ck_items_priority_valid")
        ),
        sa.CheckConstraint(
            "status IN ('discovered', 'duplicate', 'rejected', 'pending_permission', 'eligible', 'rendering', 'needs_fix', 'awaiting_approval', 'approved')",
            name=op.f("ck_items_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of"],
            ["items.id"],
            name=op.f("fk_items_duplicate_of_items"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["executions.id"],
            name=op.f("fk_items_execution_id_executions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("fk_items_operation_id_operations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_items_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_items")),
        sa.UniqueConstraint("source_id", "external_id", name=op.f("uq_items_source_id")),
    )
    op.create_index(op.f("ix_items_delete_after"), "items", ["delete_after"], unique=False)
    op.create_index(op.f("ix_items_execution_id"), "items", ["execution_id"], unique=False)
    op.create_index("ix_items_operation_status", "items", ["operation_id", "status"], unique=False)
    op.create_index(op.f("ix_items_phash"), "items", ["phash"], unique=False)
    op.create_index(op.f("ix_items_sha256"), "items", ["sha256"], unique=False)
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("ref_id", sa.BigInteger(), nullable=True),
        sa.Column("operation_id", sa.BigInteger(), nullable=True),
        sa.Column("execution_id", sa.BigInteger(), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column(
            "run_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("locked_by", sa.String(length=100), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed', 'cancelled')",
            name=op.f("ck_jobs_status_valid"),
        ),
        sa.CheckConstraint(
            "type IN ('collect', 'render', 'publish', 'scheduler', 'cleanup')",
            name=op.f("ck_jobs_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["executions.id"],
            name=op.f("fk_jobs_execution_id_executions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("fk_jobs_operation_id_operations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_jobs_idempotency_key")),
    )
    op.create_index(op.f("ix_jobs_execution_id"), "jobs", ["execution_id"], unique=False)
    op.create_index("ix_jobs_pick", "jobs", ["status", "type", "priority", "run_at"], unique=False)
    op.create_table(
        "renders",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config_id", sa.BigInteger(), nullable=False),
        sa.Column("mask_version_id", sa.BigInteger(), nullable=True),
        sa.Column("output_file", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="rendering", nullable=False),
        sa.Column("qa_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("files_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('rendering', 'ok', 'failed')", name=op.f("ck_renders_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["config_id"],
            ["operation_configs.id"],
            name=op.f("fk_renders_config_id_operation_configs"),
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["items.id"], name=op.f("fk_renders_item_id_items"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["mask_version_id"],
            ["mask_versions.id"],
            name=op.f("fk_renders_mask_version_id_mask_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_renders")),
        sa.UniqueConstraint("item_id", "version", name=op.f("uq_renders_item_id")),
    )
    op.create_table(
        "publish_jobs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("render_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", sa.ARRAY(sa.Text()), nullable=True),
        sa.Column("title_method", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="planned", nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'pending_capacity', 'uploading', 'scheduled_platform', 'processing', 'retry_wait', 'uncertain', 'published', 'failed', 'skipped', 'cancelled')",
            name=op.f("ck_publish_jobs_status_valid"),
        ),
        sa.CheckConstraint(
            "title_method IS NULL OR title_method IN ('markov', 'fallback', 'manual')",
            name=op.f("ck_publish_jobs_title_method_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_publish_jobs_account_id_accounts")
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["batches.id"],
            name=op.f("fk_publish_jobs_batch_id_batches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["render_id"], ["renders.id"], name=op.f("fk_publish_jobs_render_id_renders")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publish_jobs")),
        sa.UniqueConstraint("render_id", "account_id", name=op.f("uq_publish_jobs_render_id")),
    )
    op.create_index(
        op.f("ix_publish_jobs_account_id"), "publish_jobs", ["account_id"], unique=False
    )
    op.create_index(op.f("ix_publish_jobs_batch_id"), "publish_jobs", ["batch_id"], unique=False)
    op.create_index(
        "ix_publish_jobs_status_planned_at", "publish_jobs", ["status", "planned_at"], unique=False
    )

    # Ligações circulares: criadas depois das duas tabelas existirem.
    op.create_foreign_key(
        op.f("fk_operations_current_config_id_operation_configs"),
        "operations",
        "operation_configs",
        ["current_config_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_items_approved_render_id_renders"),
        "items",
        "renders",
        ["approved_render_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_items_approved_render_id_renders"), "items", type_="foreignkey")
    op.drop_constraint(
        op.f("fk_operations_current_config_id_operation_configs"), "operations", type_="foreignkey"
    )
    op.drop_index("ix_publish_jobs_status_planned_at", table_name="publish_jobs")
    op.drop_index(op.f("ix_publish_jobs_batch_id"), table_name="publish_jobs")
    op.drop_index(op.f("ix_publish_jobs_account_id"), table_name="publish_jobs")
    op.drop_table("publish_jobs")
    op.drop_table("renders")
    op.drop_index("ix_jobs_pick", table_name="jobs")
    op.drop_index(op.f("ix_jobs_execution_id"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_items_sha256"), table_name="items")
    op.drop_index(op.f("ix_items_phash"), table_name="items")
    op.drop_index("ix_items_operation_status", table_name="items")
    op.drop_index(op.f("ix_items_execution_id"), table_name="items")
    op.drop_index(op.f("ix_items_delete_after"), table_name="items")
    op.drop_table("items")
    op.drop_table("mask_versions")
    op.drop_index(op.f("ix_executions_operation_id"), table_name="executions")
    op.drop_table("executions")
    op.drop_index(op.f("ix_sources_operation_id"), table_name="sources")
    op.drop_table("sources")
    op.drop_index(op.f("ix_operation_configs_operation_id"), table_name="operation_configs")
    op.drop_table("operation_configs")
    op.drop_index(op.f("ix_operation_accounts_account_id"), table_name="operation_accounts")
    op.drop_table("operation_accounts")
    op.drop_index(op.f("ix_mask_assets_operation_id"), table_name="mask_assets")
    op.drop_table("mask_assets")
    op.drop_index(op.f("ix_events_operation_id"), table_name="events")
    op.drop_index("ix_events_entity", table_name="events")
    op.drop_table("events")
    op.drop_index(op.f("ix_batches_operation_id"), table_name="batches")
    op.drop_table("batches")
    op.drop_table("operations")
    op.drop_table("accounts")
