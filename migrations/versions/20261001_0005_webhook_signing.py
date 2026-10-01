"""Add webhook signing secrets.

Revision ID: 20261001_0005
Revises: 20261001_0004
Create Date: 2026-10-01
"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_0005"
down_revision: str | Sequence[str] | None = "20261001_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "webhook_endpoints",
        sa.Column("signing_secret", sa.String(length=255), nullable=True),
    )
    endpoints = sa.table(
        "webhook_endpoints",
        sa.column("id"),
        sa.column("signing_secret"),
    )
    connection = op.get_bind()
    endpoint_ids = connection.execute(sa.select(endpoints.c.id)).scalars()
    for endpoint_id in endpoint_ids:
        connection.execute(
            endpoints.update()
            .where(endpoints.c.id == endpoint_id)
            .values(signing_secret=secrets.token_urlsafe(32))
        )
    op.alter_column("webhook_endpoints", "signing_secret", nullable=False)


def downgrade() -> None:
    op.drop_column("webhook_endpoints", "signing_secret")
