"""Agrupar imagens num só Short: novo estado "grouped" do item (Task 39).

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-21 16:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = (
    "'discovered', 'duplicate', 'rejected', 'pending_permission', 'eligible', 'rendering', "
    "'needs_fix', 'awaiting_approval', 'approved'"
)
NEW = OLD + ", 'grouped'"


def _replace(values: str) -> None:
    op.drop_constraint(op.f("ck_items_status_valid"), "items", type_="check")
    op.create_check_constraint(op.f("ck_items_status_valid"), "items", f"status IN ({values})")


def upgrade() -> None:
    _replace(NEW)


def downgrade() -> None:
    op.execute("UPDATE items SET status = 'eligible' WHERE status = 'grouped'")
    _replace(OLD)
