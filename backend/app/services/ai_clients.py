from __future__ import annotations

from typing import Any

from app.core.config import Settings


def provider_status(settings: Settings) -> dict[str, Any]:
    return {
        "default_provider": settings.ai_provider,
        "providers": settings.ai_provider_options,
        "azure_openai_configured": bool(
            settings.resolved_azure_openai_endpoint
            and settings.resolved_azure_openai_api_key
            and settings.resolved_azure_openai_chat_deployment
        ),
        "openai_configured": bool(settings.openai_api_key),
    }


def make_chat_client(settings: Settings, provider: str | None = None):
    selected = provider or settings.ai_provider
    try:
        from openai import AsyncAzureOpenAI, AsyncOpenAI
    except ImportError as exc:
        raise RuntimeError("Install backend requirements before using live AI providers") from exc

    if selected == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for the OpenAI provider")
        return AsyncOpenAI(api_key=settings.openai_api_key)

    if not settings.resolved_azure_openai_endpoint or not settings.resolved_azure_openai_api_key:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY are required for Azure OpenAI")
    return AsyncAzureOpenAI(
        api_key=settings.resolved_azure_openai_api_key,
        azure_endpoint=settings.resolved_azure_openai_endpoint,
        api_version=settings.resolved_azure_openai_api_version,
    )


def chat_model_name(settings: Settings, provider: str | None = None) -> str:
    selected = provider or settings.ai_provider
    if selected == "openai":
        return settings.openai_model
    if not settings.resolved_azure_openai_chat_deployment:
        raise RuntimeError("AZURE_OPENAI_CHAT_DEPLOYMENT is required for Azure OpenAI chat calls")
    return settings.resolved_azure_openai_chat_deployment
