"""Add dead-letter and replay state.

Revision ID: 20261001_0004
Revises: 20261001_0003
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_0004"
down_revision: str | Sequence[str] | None = "20261001_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "deliveries",
        sa.Column("current_attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "deliveries",
        sa.Column("replay_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "deliveries",
        sa.Column("last_replayed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE deliveries SET current_attempt_count = attempt_count")
    op.create_check_constraint(
        "ck_deliveries_current_attempt_count_nonnegative",
        "deliveries",
        "current_attempt_count >= 0",
    )
    op.create_check_constraint(
        "ck_deliveries_replay_count_nonnegative",
        "deliveries",
        "replay_count >= 0",
    )
    op.drop_constraint("ck_deliveries_status", "deliveries", type_="check")
    op.create_check_constraint(
        "ck_deliveries_status",
        "deliveries",
        "status IN ('pending', 'retry_scheduled', 'delivered', 'failed', 'dead_lettered')",
    )


def downgrade() -> None:
    op.execute("UPDATE deliveries SET status = 'failed' WHERE status = 'dead_lettered'")
    op.drop_constraint("ck_deliveries_status", "deliveries", type_="check")
    op.create_check_constraint(
        "ck_deliveries_status",
        "deliveries",
        "status IN ('pending', 'retry_scheduled', 'delivered', 'failed')",
    )
    op.drop_constraint(
        "ck_deliveries_replay_count_nonnegative",
        "deliveries",
        type_="check",
    )
    op.drop_constraint(
        "ck_deliveries_current_attempt_count_nonnegative",
        "deliveries",
        type_="check",
    )
    op.drop_column("deliveries", "last_replayed_at")
    op.drop_column("deliveries", "replay_count")
    op.drop_column("deliveries", "current_attempt_count")
