"""Add transactional outbox.

Revision ID: 20261001_0006
Revises: 20261001_0005
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20261001_0006"
down_revision: str | Sequence[str] | None = "20261001_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=50), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("publish_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "publish_attempts >= 0",
            name="ck_outbox_publish_attempts_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_outbox_events_aggregate_id",
        "outbox_events",
        ["aggregate_id"],
    )
    op.create_index(
        "ix_outbox_unpublished",
        "outbox_events",
        ["published_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_unpublished", table_name="outbox_events")
    op.drop_index("ix_outbox_events_aggregate_id", table_name="outbox_events")
    op.drop_table("outbox_events")
