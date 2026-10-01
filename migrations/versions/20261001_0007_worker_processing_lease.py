"""Add worker processing lease.

Revision ID: 20261001_0007
Revises: 20261001_0006
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_0007"
down_revision: str | Sequence[str] | None = "20261001_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "deliveries",
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint("ck_deliveries_status", "deliveries", type_="check")
    op.create_check_constraint(
        "ck_deliveries_status",
        "deliveries",
        "status IN ('pending', 'processing', 'retry_scheduled', 'delivered', 'failed', "
        "'dead_lettered')",
    )


def downgrade() -> None:
    op.execute("UPDATE deliveries SET status = 'pending' WHERE status = 'processing'")
    op.drop_constraint("ck_deliveries_status", "deliveries", type_="check")
    op.create_check_constraint(
        "ck_deliveries_status",
        "deliveries",
        "status IN ('pending', 'retry_scheduled', 'delivered', 'failed', 'dead_lettered')",
    )
    op.drop_column("deliveries", "processing_started_at")
