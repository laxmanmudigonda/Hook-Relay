"""Create the Phase 0 schema baseline.

Revision ID: 20261001_0001
Revises:
Create Date: 2026-10-01
"""

from collections.abc import Sequence

revision: str = "20261001_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Phase 0 intentionally has no business tables."""


def downgrade() -> None:
    """Phase 0 intentionally has no business tables."""
