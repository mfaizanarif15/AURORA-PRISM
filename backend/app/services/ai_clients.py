from __future__ import annotations

from typing import Any

from loguru import logger

from app.core.config import Settings


def provider_status(settings: Settings) -> dict[str, Any]:
    status = {
        "default_provider": settings.ai_provider,
        "providers": settings.ai_provider_options,
        "azure_openai_configured": bool(
            settings.resolved_azure_openai_endpoint
            and settings.resolved_azure_openai_api_key
            and settings.resolved_azure_openai_chat_deployment
        ),
        "azure_openai_transcription_configured": bool(
            settings.resolved_azure_openai_endpoint
            and settings.resolved_azure_openai_api_key
            and settings.resolved_azure_openai_transcription_deployment
        ),
        "openai_configured": bool(settings.openai_api_key),
    }
    logger.debug(
        "Provider status default_provider={} azure_configured={} openai_configured={}",
        status["default_provider"],
        status["azure_openai_configured"],
        status["openai_configured"],
    )
    return status


def make_chat_client(settings: Settings, provider: str | None = None):
    selected = provider or settings.ai_provider
    logger.info("Creating chat client provider={}", selected)
    try:
        from openai import AsyncAzureOpenAI, AsyncOpenAI
    except ImportError as exc:
        logger.exception("OpenAI SDK import failed")
        raise RuntimeError("Install backend dependencies with uv sync before using live AI providers") from exc

    if selected == "openai":
        if not settings.openai_api_key:
            logger.warning("OpenAI client requested but OPENAI_API_KEY is missing")
            raise RuntimeError("OPENAI_API_KEY is required for the OpenAI provider")
        return AsyncOpenAI(api_key=settings.openai_api_key)

    if not settings.resolved_azure_openai_endpoint or not settings.resolved_azure_openai_api_key:
        logger.warning("Azure OpenAI client requested but endpoint or API key is missing")
        raise RuntimeError("AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY are required for Azure OpenAI")
    logger.debug(
        "Azure OpenAI client configured endpoint={} api_version={}",
        settings.resolved_azure_openai_endpoint,
        settings.resolved_azure_openai_api_version,
    )
    return AsyncAzureOpenAI(
        api_key=settings.resolved_azure_openai_api_key,
        azure_endpoint=settings.resolved_azure_openai_endpoint,
        api_version=settings.resolved_azure_openai_api_version,
    )


def chat_model_name(settings: Settings, provider: str | None = None) -> str:
    selected = provider or settings.ai_provider
    if selected == "openai":
        logger.debug("Resolved OpenAI model name model={}", settings.openai_model)
        return settings.openai_model
    if not settings.resolved_azure_openai_chat_deployment:
        logger.warning("Azure OpenAI chat deployment missing")
        raise RuntimeError("AZURE_OPENAI_CHAT_DEPLOYMENT is required for Azure OpenAI chat calls")
    logger.debug("Resolved Azure OpenAI deployment deployment={}", settings.resolved_azure_openai_chat_deployment)
    return settings.resolved_azure_openai_chat_deployment
