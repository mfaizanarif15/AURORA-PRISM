"""add section output fields

Revision ID: 20260531_0005
Revises: 20260531_0004
Create Date: 2026-05-31
"""

from collections.abc import Sequence

from loguru import logger
import sqlalchemy as sa
from alembic import op

revision: str = "20260531_0005"
down_revision: str | None = "20260531_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    logger.info("Adding section output fields revision={}", revision)
    op.add_column(
        "clip_candidates",
        sa.Column("target_platform", sa.String(length=64), nullable=False, server_default="generic"),
    )
    op.add_column(
        "clip_candidates",
        sa.Column("purpose", sa.String(length=128), nullable=False, server_default="Generic"),
    )
    op.alter_column("clip_candidates", "target_platform", server_default=None)
    op.alter_column("clip_candidates", "purpose", server_default=None)
    logger.info("Added section output fields revision={}", revision)


def downgrade() -> None:
    logger.info("Removing section output fields revision={}", revision)
    op.drop_column("clip_candidates", "purpose")
    op.drop_column("clip_candidates", "target_platform")
    logger.info("Removed section output fields revision={}", revision)
