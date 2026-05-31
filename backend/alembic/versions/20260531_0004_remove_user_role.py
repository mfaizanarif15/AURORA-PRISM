"""remove user role

Revision ID: 20260531_0004
Revises: 20260531_0003
Create Date: 2026-05-31
"""

from collections.abc import Sequence

from loguru import logger
import sqlalchemy as sa
from alembic import op

revision: str = "20260531_0004"
down_revision: str | None = "20260531_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    logger.info("Removing user role column revision={}", revision)
    op.drop_column("users", "role")
    logger.info("Removed user role column revision={}", revision)


def downgrade() -> None:
    logger.info("Restoring user role column revision={}", revision)
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=64), nullable=False, server_default="Content Operations"),
    )
    op.alter_column("users", "role", server_default=None)
    logger.info("Restored user role column revision={}", revision)
