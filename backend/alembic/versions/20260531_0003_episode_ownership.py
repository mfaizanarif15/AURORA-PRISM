"""add episode ownership

Revision ID: 20260531_0003
Revises: 20260531_0002
Create Date: 2026-05-31
"""

from collections.abc import Sequence

from loguru import logger
import sqlalchemy as sa
from alembic import op

revision: str = "20260531_0003"
down_revision: str | None = "20260531_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    logger.info("Applying episode ownership migration revision={}", revision)
    op.add_column("episodes", sa.Column("owner_user_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_episodes_owner_user_id_users",
        "episodes",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_episodes_owner_user_id", "episodes", ["owner_user_id"])
    op.execute(
        sa.text(
            """
            UPDATE episodes
            SET owner_user_id = (
                SELECT id
                FROM users
                ORDER BY created_at ASC, username ASC
                LIMIT 1
            )
            WHERE owner_user_id IS NULL
              AND EXISTS (SELECT 1 FROM users)
            """
        )
    )
    logger.info("Episode ownership migration applied revision={}", revision)


def downgrade() -> None:
    logger.info("Reverting episode ownership migration revision={}", revision)
    op.drop_index("ix_episodes_owner_user_id", table_name="episodes")
    op.drop_constraint("fk_episodes_owner_user_id_users", "episodes", type_="foreignkey")
    op.drop_column("episodes", "owner_user_id")
    logger.info("Episode ownership migration reverted revision={}", revision)
