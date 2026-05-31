"""remove redundant episode context fields

Revision ID: 20260531_0006
Revises: 20260531_0005
Create Date: 2026-05-31
"""

from collections.abc import Sequence

from loguru import logger
import sqlalchemy as sa
from alembic import op

revision: str = "20260531_0006"
down_revision: str | None = "20260531_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    logger.info("Removing redundant episode context fields revision={}", revision)
    op.drop_column("episode_contexts", "tkxel_services")
    op.drop_column("episodes", "theme")
    logger.info("Removed redundant episode context fields revision={}", revision)


def downgrade() -> None:
    logger.info("Restoring redundant episode context fields revision={}", revision)
    op.add_column("episodes", sa.Column("theme", sa.String(length=255), nullable=True))
    op.add_column("episode_contexts", sa.Column("tkxel_services", sa.Text(), nullable=True))
    logger.info("Restored redundant episode context fields revision={}", revision)
