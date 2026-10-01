"""Add retry scheduling state.

Revision ID: 20261001_0003
Revises: 20261001_0002
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_0003"
down_revision: str | Sequence[str] | None = "20261001_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "deliveries",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint("ck_deliveries_status", "deliveries", type_="check")
    op.create_check_constraint(
        "ck_deliveries_status",
        "deliveries",
        "status IN ('pending', 'retry_scheduled', 'delivered', 'failed')",
    )
    op.create_index(
        "ix_deliveries_retry_due",
        "deliveries",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.execute("UPDATE deliveries SET status = 'failed' WHERE status = 'retry_scheduled'")
    op.drop_index("ix_deliveries_retry_due", table_name="deliveries")
    op.drop_constraint("ck_deliveries_status", "deliveries", type_="check")
    op.create_check_constraint(
        "ck_deliveries_status",
        "deliveries",
        "status IN ('pending', 'delivered', 'failed')",
    )
    op.drop_column("deliveries", "next_attempt_at")
