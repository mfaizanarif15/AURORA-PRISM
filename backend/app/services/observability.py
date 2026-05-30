from __future__ import annotations

import importlib.util
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from loguru import logger

from app.core.config import Settings, get_settings


class NoopObservation:
    def update(self, **_: Any) -> None:
        return None


def langfuse_status(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    logger.debug(
        "Checking Langfuse status enabled={} configured={}",
        settings.langfuse_enabled,
        settings.langfuse_configured,
    )
    return {
        "enabled": settings.langfuse_enabled,
        "configured": settings.langfuse_configured,
        "sdk_available": importlib.util.find_spec("langfuse") is not None,
        "base_url": settings.langfuse_base_url if settings.langfuse_enabled else None,
        "environment": settings.langfuse_environment or settings.environment,
        "release": settings.langfuse_release,
        "capture_llm_io": settings.langfuse_capture_llm_io,
        "max_llm_io_chars": settings.langfuse_max_llm_io_chars,
    }


@contextmanager
def observation(
    name: str,
    *,
    as_type: str = "span",
    input: Any | None = None,
    output: Any | None = None,
    metadata: dict[str, Any] | None = None,
    model: str | None = None,
    model_parameters: dict[str, Any] | None = None,
    usage_details: dict[str, int] | None = None,
    cost_details: dict[str, float] | None = None,
    version: str | None = None,
    level: str | None = None,
    status_message: str | None = None,
) -> Iterator[Any]:
    settings = get_settings()
    if not settings.langfuse_enabled or not settings.langfuse_configured:
        logger.debug("Langfuse observation skipped name={} reason=disabled_or_unconfigured", name)
        yield NoopObservation()
        return

    try:
        _prepare_langfuse_environment(settings)
        from langfuse import get_client

        client = get_client()
        base_metadata = {
            "service": "aurora-prism-backend",
            "environment": settings.langfuse_environment or settings.environment,
            "release": settings.langfuse_release,
            **(metadata or {}),
        }
        manager = client.start_as_current_observation(
            **_clean_observation_values(
                {
                    "as_type": as_type,
                    "name": name,
                    "input": input,
                    "output": output,
                    "metadata": base_metadata,
                    "model": model,
                    "model_parameters": model_parameters,
                    "usage_details": usage_details,
                    "cost_details": cost_details,
                    "version": version,
                    "level": level,
                    "status_message": status_message,
                }
            )
        )
    except Exception as exc:
        logger.warning("Langfuse disabled for observation name={} error={}", name, exc)
        yield NoopObservation()
        return

    with manager as span:
        logger.debug("Langfuse observation started name={} type={}", name, as_type)
        try:
            yield span
        except Exception as exc:
            safe_update(
                span,
                level="ERROR",
                status_message=str(exc),
                metadata={"error": type(exc).__name__, "message": str(exc)},
            )
            logger.warning(
                "Langfuse observation captured exception name={} error_type={} error={}",
                name,
                type(exc).__name__,
                exc,
            )
            raise
        finally:
            logger.debug("Langfuse observation finished name={}", name)


def safe_update(span: Any, **values: Any) -> None:
    cleaned = {key: value for key, value in values.items() if value is not None}
    if not cleaned:
        return
    try:
        span.update(**cleaned)
    except Exception as exc:
        logger.debug("Langfuse span update skipped error={}", exc)


def _clean_observation_values(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def flush_langfuse() -> None:
    settings = get_settings()
    if not settings.langfuse_enabled or not settings.langfuse_configured:
        logger.debug("Langfuse flush skipped reason=disabled_or_unconfigured")
        return
    try:
        _prepare_langfuse_environment(settings)
        from langfuse import get_client

        get_client().flush()
        logger.info("Langfuse client flushed")
    except Exception as exc:
        logger.debug("Langfuse flush skipped error={}", exc)


def _prepare_langfuse_environment(settings: Settings) -> None:
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key or ""
    os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key or ""
    os.environ["LANGFUSE_BASE_URL"] = settings.langfuse_base_url
    os.environ["LANGFUSE_HOST"] = settings.langfuse_base_url
    os.environ["LANGFUSE_TRACING_ENABLED"] = "true" if settings.langfuse_enabled else "false"
    if settings.langfuse_environment:
        os.environ["LANGFUSE_ENVIRONMENT"] = settings.langfuse_environment
        os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = settings.langfuse_environment
    if settings.langfuse_release:
        os.environ["LANGFUSE_RELEASE"] = settings.langfuse_release
    logger.debug(
        "Langfuse environment prepared base_url={} environment={} release={}",
        settings.langfuse_base_url,
        settings.langfuse_environment or settings.environment,
        settings.langfuse_release,
    )
