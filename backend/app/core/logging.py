from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from app.core.config import Settings


_CONFIGURED = False


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def configure_logging(settings: Settings) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = settings.log_level.upper()
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        backtrace=False,
        diagnose=False,
    )

    log_path = _resolve_log_path(settings)
    if settings.log_to_file:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_path,
            level=level,
            rotation="10 MB",
            retention="14 days",
            compression="zip",
            encoding="utf-8",
            enqueue=True,
            backtrace=False,
            diagnose=False,
        )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy", "alembic"):
        std_logger = logging.getLogger(logger_name)
        std_logger.handlers = []
        std_logger.propagate = True

    _CONFIGURED = True
    logger.info(
        "Loguru configured level={} file_logging={} log_file={}",
        level,
        settings.log_to_file,
        log_path if settings.log_to_file else None,
    )


def _resolve_log_path(settings: Settings) -> Path:
    if settings.log_file:
        return settings.log_file
    return settings.storage_root / "logs" / "backend.log"
