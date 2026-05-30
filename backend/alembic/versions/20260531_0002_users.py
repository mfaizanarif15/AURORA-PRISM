"""add users table

Revision ID: 20260531_0002
Revises: 20260522_0001
Create Date: 2026-05-31
"""

from collections.abc import Sequence

from loguru import logger
import sqlalchemy as sa
from alembic import op

revision: str = "20260531_0002"
down_revision: str | None = "20260522_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    logger.info("Applying users migration revision={}", revision)
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_username", "users", ["username"])
    logger.info("Users migration applied revision={}", revision)


def downgrade() -> None:
    logger.info("Reverting users migration revision={}", revision)
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
    logger.info("Users migration reverted revision={}", revision)
