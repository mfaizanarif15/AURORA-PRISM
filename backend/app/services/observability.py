from __future__ import annotations

import importlib.util
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class NoopObservation:
    def update(self, **_: Any) -> None:
        return None


def langfuse_status(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return {
        "enabled": settings.langfuse_enabled,
        "configured": settings.langfuse_configured,
        "sdk_available": importlib.util.find_spec("langfuse") is not None,
        "base_url": settings.langfuse_base_url if settings.langfuse_enabled else None,
        "environment": settings.langfuse_environment or settings.environment,
        "release": settings.langfuse_release,
    }


@contextmanager
def observation(
    name: str,
    *,
    as_type: str = "span",
    input: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Any]:
    settings = get_settings()
    if not settings.langfuse_enabled or not settings.langfuse_configured:
        yield NoopObservation()
        return

    try:
        _prepare_langfuse_environment(settings)
        from langfuse import get_client

        client = get_client()
        manager = client.start_as_current_observation(as_type=as_type, name=name)
    except Exception as exc:
        logger.warning("Langfuse disabled for this observation: %s", exc)
        yield NoopObservation()
        return

    with manager as span:
        safe_update(
            span,
            input=input,
            metadata={
                "service": "aurora-prism-backend",
                "environment": settings.langfuse_environment or settings.environment,
                "release": settings.langfuse_release,
                **(metadata or {}),
            },
        )
        try:
            yield span
        except Exception as exc:
            safe_update(span, metadata={"error": type(exc).__name__, "message": str(exc)})
            raise


def safe_update(span: Any, **values: Any) -> None:
    cleaned = {key: value for key, value in values.items() if value is not None}
    if not cleaned:
        return
    try:
        span.update(**cleaned)
    except Exception as exc:
        logger.debug("Langfuse span update skipped: %s", exc)


def flush_langfuse() -> None:
    settings = get_settings()
    if not settings.langfuse_enabled or not settings.langfuse_configured:
        return
    try:
        _prepare_langfuse_environment(settings)
        from langfuse import get_client

        get_client().flush()
    except Exception as exc:
        logger.debug("Langfuse flush skipped: %s", exc)


def _prepare_langfuse_environment(settings: Settings) -> None:
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key or ""
    os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key or ""
    os.environ["LANGFUSE_BASE_URL"] = settings.langfuse_base_url
    if settings.langfuse_environment:
        os.environ["LANGFUSE_ENVIRONMENT"] = settings.langfuse_environment
    if settings.langfuse_release:
        os.environ["LANGFUSE_RELEASE"] = settings.langfuse_release
