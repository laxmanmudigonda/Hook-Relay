"""Add tenant API keys.

Revision ID: 20261001_0008
Revises: 20261001_0007
Create Date: 2026-10-01
"""

import hashlib
import os
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_0008"
down_revision: str | Sequence[str] | None = "20261001_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEVELOPMENT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
    development_key = os.getenv("HOOKRELAY_DEVELOPMENT_API_KEY", "hr_dev_local_change_me")
    keys = sa.table(
        "api_keys",
        sa.column("id", sa.Uuid()),
        sa.column("tenant_id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("key_prefix", sa.String()),
        sa.column("key_hash", sa.String()),
    )
    op.bulk_insert(
        keys,
        [
            {
                "id": str(uuid.uuid4()),
                "tenant_id": DEVELOPMENT_TENANT_ID,
                "name": "Local development key",
                "key_prefix": development_key[:16],
                "key_hash": hashlib.sha256(development_key.encode()).hexdigest(),
            }
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_api_keys_tenant_id", table_name="api_keys")
    op.drop_table("api_keys")
