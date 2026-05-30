from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from loguru import logger
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.base import Base
from app.models import *  # noqa: F401,F403

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
configure_logging(settings)
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata
logger.info("Alembic environment configured")


def run_migrations_offline() -> None:
    logger.info("Running Alembic migrations offline")
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
    logger.info("Alembic offline migrations complete")


def do_run_migrations(connection: Connection) -> None:
    logger.debug("Running Alembic migration transaction")
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    logger.info("Running Alembic migrations online")
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()
    logger.info("Alembic online migrations complete")


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
