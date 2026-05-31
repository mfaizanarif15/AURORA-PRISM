from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

from loguru import logger

from app.core.config import Settings, get_settings
from app.models import Episode, EpisodeContext, TranscriptSegment
from app.services.ai_clients import chat_model_name, make_chat_client
from app.services.observability import observation, safe_update


TITLE_PROMPT_VERSION = "episode-title-json-v1"
SECTION_PROMPT_VERSION = "section-specialist-json-v1"


@dataclass(frozen=True)
class LLMCallResult:
    content: str
    raw_response: Any
    finish_reason: str | None
    usage_details: dict[str, int] | None
    model: str
    provider: str


async def call_chat_completion(
    *,
    operation: str,
    messages: list[dict[str, str]],
    payload: dict[str, Any],
    provider: str | None = None,
    settings: Settings | None = None,
    name: str | None = None,
    metadata: dict[str, Any] | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1200,
    response_format: dict[str, Any] | None = None,
    prompt_version: str | None = None,
) -> LLMCallResult:
    settings = settings or get_settings()
    selected_provider = provider or settings.ai_provider
    client = make_chat_client(settings, selected_provider)
    model = chat_model_name(settings, selected_provider)
    model_parameters = llm_model_parameters(
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
        prompt_version=prompt_version,
    )
    trace_metadata = llm_trace_metadata(
        settings,
        operation=operation,
        provider=selected_provider,
        prompt_version=prompt_version,
        extra=metadata,
    )

    with observation(
        name or f"llm_{operation}",
        as_type="generation",
        input=langfuse_llm_input(settings, messages, payload),
        metadata=trace_metadata,
        model=model,
        model_parameters=model_parameters,
        version=prompt_version,
    ) as span:
        logger.info(
            "Calling LLM operation={} provider={} model={}",
            operation,
            selected_provider,
            model,
        )
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format

        completion = await client.chat.completions.create(**kwargs)
        content = openai_completion_content(completion)
        finish_reason = openai_finish_reason(completion)
        usage_details = llm_usage_details(completion)
        safe_update(
            span,
            output=langfuse_llm_raw_output(settings, content, finish_reason),
            metadata={
                **trace_metadata,
                **completion_metadata(completion),
                "raw_response_length": len(content),
                "raw_response_sha256": sha256_text(content),
            },
            usage_details=usage_details,
        )
        return LLMCallResult(
            content=content,
            raw_response=completion,
            finish_reason=finish_reason,
            usage_details=usage_details,
            model=model,
            provider=selected_provider,
        )


async def call_langchain_chat(
    *,
    operation: str,
    messages: list[dict[str, str]],
    payload: dict[str, Any],
    provider: str | None = None,
    settings: Settings | None = None,
    name: str | None = None,
    metadata: dict[str, Any] | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1200,
    prompt_version: str | None = None,
) -> LLMCallResult:
    settings = settings or get_settings()
    selected_provider = provider or settings.ai_provider
    model_name = chat_model_name(settings, selected_provider)
    model = make_langchain_chat_model(
        settings,
        selected_provider,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    model_parameters = llm_model_parameters(
        temperature=temperature,
        max_tokens=max_tokens,
        prompt_version=prompt_version,
    )
    trace_metadata = llm_trace_metadata(
        settings,
        operation=operation,
        provider=selected_provider,
        prompt_version=prompt_version,
        extra=metadata,
    )

    with observation(
        name or f"llm_{operation}",
        as_type="generation",
        input=langfuse_llm_input(settings, messages, payload),
        metadata=trace_metadata,
        model=model_name,
        model_parameters=model_parameters,
        version=prompt_version,
    ) as span:
        logger.info(
            "Calling LangChain LLM operation={} provider={} model={}",
            operation,
            selected_provider,
            model_name,
        )
        response = await model.ainvoke(langchain_messages(messages))
        content = message_content(getattr(response, "content", ""))
        finish_reason = response_finish_reason(response)
        usage_details = langchain_usage_details(response)
        safe_update(
            span,
            output=langfuse_llm_raw_output(settings, content, finish_reason),
            metadata={
                **trace_metadata,
                "raw_response_length": len(content),
                "raw_response_sha256": sha256_text(content),
            },
            usage_details=usage_details,
        )
        return LLMCallResult(
            content=content,
            raw_response=response,
            finish_reason=finish_reason,
            usage_details=usage_details,
            model=model_name,
            provider=selected_provider,
        )


def make_langchain_chat_model(
    settings: Settings,
    provider: str | None = None,
    *,
    temperature: float = 0.2,
    max_tokens: int = 1200,
) -> Any:
    selected_provider = provider or settings.ai_provider

    if selected_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for the OpenAI provider")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    if not settings.resolved_azure_openai_endpoint or not settings.resolved_azure_openai_api_key:
        raise RuntimeError(
            "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY are required for Azure OpenAI"
        )
    if not settings.resolved_azure_openai_chat_deployment:
        raise RuntimeError("AZURE_OPENAI_CHAT_DEPLOYMENT is required for Azure OpenAI")

    from langchain_openai import AzureChatOpenAI

    return AzureChatOpenAI(
        azure_endpoint=settings.resolved_azure_openai_endpoint,
        api_key=settings.resolved_azure_openai_api_key,
        api_version=settings.resolved_azure_openai_api_version,
        azure_deployment=settings.resolved_azure_openai_chat_deployment,
        temperature=temperature,
        max_tokens=max_tokens,
    )


async def suggest_episode_title(
    episode: Episode,
    context: EpisodeContext | None,
    transcript_segments: Iterable[TranscriptSegment],
    provider: str,
) -> str:
    fallback = heuristic_episode_title(episode, context)
    try:
        transcript = " ".join(segment.text for segment in transcript_segments)
        prompt_payload = title_prompt_payload(episode, context, transcript)
        messages = title_messages(prompt_payload)
        result = await call_chat_completion(
            operation="episode_title_generation",
            name="llm_episode_title_generation",
            provider=provider,
            messages=messages,
            payload=prompt_payload,
            temperature=0.2,
            max_tokens=120,
            response_format={"type": "json_object"},
            prompt_version=TITLE_PROMPT_VERSION,
            metadata={
                "episode_id": episode.id,
                "episode_title": episode.title,
                "transcript_excerpt_chars": len(prompt_payload["transcript_excerpt"]),
            },
        )
        parsed = json.loads(result.content or "{}")
        title = clean_title(parsed.get("title"))
        if title:
            return title
    except Exception as exc:
        logger.warning(
            "LLM episode title suggestion failed episode_id={} error={}",
            episode.id,
            exc,
        )
    return fallback


def title_messages(prompt_payload: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Create concise, professional podcast episode titles. "
                "Return valid JSON only with a title field."
            ),
        },
        {
            "role": "user",
            "content": (
                "Suggest one specific title under 90 characters from this context. "
                "Avoid clickbait and avoid generic words like Untitled.\n"
                f"{json.dumps(prompt_payload, ensure_ascii=True)}"
            ),
        },
    ]


def title_prompt_payload(
    episode: Episode,
    context: EpisodeContext | None,
    transcript: str,
) -> dict[str, Any]:
    return {
        "episode": {
            "current_title": episode.title,
            "guest_name": episode.guest_name,
            "guest_role": episode.guest_role,
            "guest_company": episode.guest_company,
        },
        "context": context_summary(context),
        "transcript_excerpt": transcript[:1800],
    }


def section_system_prompt(*, purpose: str, focus: str) -> str:
    return (
        "You are AURORA PRISM, a specialist B2B podcast editor. "
        f"You only select outputs for {purpose}. "
        f"Optimize for {focus}. "
        "Use supporting documents only as background context. "
        "Selected timestamps must stay inside the provided candidate moments and must be grounded "
        "in transcript text. "
        "Return valid JSON only."
    )


def section_user_prompt(payload: dict[str, Any]) -> str:
    target_platform = payload["section"]["target_platform"]
    schema = {
        "clips": [
            {
                "source_candidate_id": "candidate id from candidate_moments",
                "clip_type": payload["section"]["clip_type"],
                "moment_type": (
                    "hot_take|expert_insight|future_prediction|business_value|"
                    "practical_advice|story"
                ),
                "start_seconds": 123.0,
                "end_seconds": 183.0,
                "excerpt": "Transcript-grounded excerpt.",
                "reasoning": "Why this section should use the moment.",
                "platform_metadata": {
                    target_platform: {
                        "title": "Section-native title under 95 characters",
                        "hook": "Opening hook or overlay angle",
                        "caption": "Platform-ready caption",
                        "soft_cta": "Low-pressure viewer CTA",
                        "business_cta": "Business CTA for TKXEL when appropriate",
                        "hashtags": ["#BetterTech", "#AI"],
                        "pinned_comment": "Question that invites replies",
                        "thumbnail_concepts": [
                            {
                                "headline": "Short thumbnail headline",
                                "supporting_text": "Optional supporting text",
                                "layout": "Visual layout direction",
                                "tone": "Tone words",
                                "risk": "Claims/safety note",
                            }
                        ],
                        "risk_flags": [],
                    }
                },
            }
        ],
        "summary": "Brief selection rationale for this section.",
    }
    return (
        "Choose the best outputs for this exact section.\n"
        "Rules:\n"
        "- Return JSON matching output_schema.\n"
        "- Select only from candidate_moments by source_candidate_id.\n"
        "- Return no more than section.target_count clips.\n"
        "- Keep timestamps inside the selected candidate's start/end seconds.\n"
        "- Keep duration inside section.duration_min_seconds and section.duration_max_seconds.\n"
        "- Include platform_metadata only for section.target_platform.\n"
        "- Avoid unsupported claims and do not invent transcript facts.\n"
        f"output_schema:\n{json.dumps(schema, ensure_ascii=True)}\n\n"
        f"input_json:\n{json.dumps(payload, ensure_ascii=True)}"
    )


def context_summary(context: EpisodeContext | None) -> dict[str, Any]:
    if context is None:
        return {}
    return {
        "target_audience": context.target_audience,
        "hot_topic": context.hot_topic,
        "business_objectives": context.business_objectives,
        "episode_plan": context.episode_plan,
        "editor_notes": context.editor_notes,
    }


def heuristic_episode_title(episode: Episode, context: EpisodeContext | None) -> str:
    topic = clean_title(context.hot_topic if context else None)
    guest = clean_title(episode.guest_name)
    if guest and topic:
        return clean_title(f"{guest} on {topic}") or "Untitled episode"
    if topic:
        return topic
    if guest:
        return clean_title(f"Conversation with {guest}") or "Untitled episode"
    return "Untitled episode"


def clean_title(value: object) -> str | None:
    if value is None:
        return None
    title = " ".join(str(value).strip().split())
    if not title:
        return None
    return title[:90].rsplit(" ", 1)[0] if len(title) > 90 else title


def langchain_messages(messages: list[dict[str, str]]) -> list[Any]:
    from langchain_core.messages import HumanMessage, SystemMessage

    converted = []
    for message in messages:
        role = message.get("role")
        content = message.get("content", "")
        if role == "system":
            converted.append(SystemMessage(content=content))
        else:
            converted.append(HumanMessage(content=content))
    return converted


def openai_completion_content(completion: Any) -> str:
    choices = getattr(completion, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    return str(getattr(message, "content", "") or "")


def openai_finish_reason(completion: Any) -> str | None:
    choices = getattr(completion, "choices", None) or []
    if not choices:
        return None
    reason = getattr(choices[0], "finish_reason", None)
    return str(reason) if reason is not None else None


def message_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            elif item is not None:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content or "")


def response_finish_reason(response: Any) -> str | None:
    metadata = getattr(response, "response_metadata", None)
    if isinstance(metadata, dict):
        reason = metadata.get("finish_reason") or metadata.get("stop_reason")
        return str(reason) if reason is not None else None
    return None


def langfuse_llm_input(
    settings: Any,
    messages: list[dict[str, str]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not settings.langfuse_capture_llm_io:
        return {
            "capture_disabled": True,
            "messages": [message_digest(message) for message in messages],
            "payload_summary": llm_payload_summary(payload),
        }
    return truncate_for_langfuse(
        {
            "messages": messages,
            "prompt_payload": payload,
        },
        settings.langfuse_max_llm_io_chars,
    )


def langfuse_llm_raw_output(
    settings: Any,
    content: str,
    finish_reason: str | None,
) -> dict[str, Any]:
    if not settings.langfuse_capture_llm_io:
        return {
            "capture_disabled": True,
            "assistant_message": {
                "role": "assistant",
                "content_length": len(content),
                "content_sha256": sha256_text(content),
            },
            "finish_reason": finish_reason,
        }
    return truncate_for_langfuse(
        {
            "assistant_message": {"role": "assistant", "content": content},
            "finish_reason": finish_reason,
        },
        settings.langfuse_max_llm_io_chars,
    )


def llm_trace_metadata(
    settings: Any,
    *,
    operation: str,
    provider: str,
    prompt_version: str | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return without_none(
        {
            **(extra or {}),
            "operation": operation,
            "provider": provider,
            "prompt_version": prompt_version,
            "capture_llm_io": settings.langfuse_capture_llm_io,
        }
    )


def llm_model_parameters(
    *,
    temperature: float,
    max_tokens: int,
    response_format: dict[str, Any] | None = None,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    return without_none(
        {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
            "prompt_version": prompt_version,
        }
    )


def llm_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = payload.get("candidate_moments")
    candidate_items = candidates if isinstance(candidates, list) else []
    return {
        "episode": payload.get("episode"),
        "section": payload.get("section"),
        "request": payload.get("request"),
        "transcript": payload.get("transcript"),
        "transcript_excerpt_chars": len(str(payload.get("transcript_excerpt") or "")),
        "supporting_document_count": len(payload.get("supporting_documents") or []),
        "candidate_count": len(candidate_items),
        "candidate_ids": [
            candidate.get("id") for candidate in candidate_items if isinstance(candidate, dict)
        ],
    }


def llm_response_summary(payload: dict[str, Any]) -> dict[str, Any]:
    raw_clips = payload.get("clips") if isinstance(payload, dict) else None
    clips = raw_clips if isinstance(raw_clips, list) else []
    return {
        "clip_count": len(clips),
        "summary": payload.get("summary") if isinstance(payload, dict) else None,
        "source_candidate_ids": [
            clip.get("source_candidate_id") for clip in clips if isinstance(clip, dict)
        ],
    }


def completion_metadata(completion: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("id", "created", "model", "system_fingerprint"):
        value = getattr(completion, key, None)
        if value is not None:
            metadata[f"completion_{key}"] = value
    return metadata


def llm_usage_details(completion: Any) -> dict[str, int] | None:
    usage = getattr(completion, "usage", None)
    if usage is None:
        return None

    details = {
        "input": usage_int(usage, "prompt_tokens", "input_tokens"),
        "output": usage_int(usage, "completion_tokens", "output_tokens"),
        "total": usage_int(usage, "total_tokens"),
    }
    cleaned = {key: value for key, value in details.items() if value is not None}
    return cleaned or None


def langchain_usage_details(response: Any) -> dict[str, int] | None:
    metadata = getattr(response, "usage_metadata", None)
    if isinstance(metadata, dict):
        details = {
            "input": metadata.get("input_tokens"),
            "output": metadata.get("output_tokens"),
            "total": metadata.get("total_tokens"),
        }
        cleaned = {key: value for key, value in details.items() if isinstance(value, int)}
        return cleaned or None

    response_metadata = getattr(response, "response_metadata", None)
    token_usage = (
        response_metadata.get("token_usage") if isinstance(response_metadata, dict) else None
    )
    if isinstance(token_usage, dict):
        details = {
            "input": token_usage.get("prompt_tokens"),
            "output": token_usage.get("completion_tokens"),
            "total": token_usage.get("total_tokens"),
        }
        cleaned = {key: value for key, value in details.items() if isinstance(value, int)}
        return cleaned or None
    return None


def usage_int(usage: Any, *names: str) -> int | None:
    for name in names:
        value = getattr(usage, name, None)
        if isinstance(value, int):
            return value
    return None


def message_digest(message: dict[str, str]) -> dict[str, Any]:
    content = message.get("content", "")
    return {
        "role": message.get("role"),
        "content_length": len(content),
        "content_sha256": sha256_text(content),
    }


def without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def truncate_for_langfuse(value: Any, max_chars: int) -> Any:
    if isinstance(value, str):
        return truncate_trace_text(value, max_chars)
    if isinstance(value, list):
        return [truncate_for_langfuse(item, max_chars) for item in value]
    if isinstance(value, dict):
        return {key: truncate_for_langfuse(item, max_chars) for key, item in value.items()}
    return value


def truncate_trace_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n...[truncated {omitted} chars]"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
