from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import (
    AnalysisRun,
    Asset,
    ClipCandidate,
    ClipMetadata,
    ClipScore,
    Episode,
    EpisodeContext,
    TranscriptSegment,
)
from app.schemas.api import AnalysisRequest
from app.services.ai_clients import chat_model_name, make_chat_client
from app.services.audio import audio_confidence_for_range
from app.services.events import publish_episode_event
from app.services.observability import observation, safe_update
from app.services.transcripts import seconds_to_timestamp


PLATFORM_LABELS = {
    "youtube_shorts": "YouTube Shorts",
    "linkedin": "LinkedIn",
    "instagram_reels": "Instagram/Reels",
    "tiktok": "TikTok",
}

MOMENT_TYPES = [
    ("hot_take", {"wrong", "myth", "problem", "risk", "danger", "colonialism", "bias"}),
    ("expert_insight", {"because", "means", "architecture", "model", "data", "strategy"}),
    ("future_prediction", {"future", "next", "will", "trend", "years", "coming"}),
    ("business_value", {"cost", "revenue", "growth", "customer", "business", "market"}),
    ("practical_advice", {"should", "need", "how", "focus", "approach", "build"}),
    ("story", {"when", "started", "company", "career", "customer", "example"}),
]

SCORE_KEYS = (
    "icp_relevance",
    "tkxel_alignment",
    "hook_strength",
    "virality_potential",
    "business_value",
    "guest_authority",
    "topic_fit",
    "audio_confidence",
)

LLM_PROMPT_VERSION = "clip-selection-json-v1"
LLM_TEMPERATURE = 0.2
LLM_MAX_TOKENS = 12000
LLM_RESPONSE_FORMAT = {"type": "json_object"}


@dataclass
class PlatformMetadataDraft:
    title: str
    hook: str
    caption: str
    soft_cta: str
    business_cta: str
    hashtags: list[str]
    pinned_comment: str | None = None
    thumbnail_concepts: list[dict[str, Any]] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)


@dataclass
class DraftClip:
    clip_type: str
    moment_type: str
    start_seconds: float
    end_seconds: float
    excerpt: str
    reasoning: str
    score_parts: dict[str, int]
    metadata_by_platform: dict[str, PlatformMetadataDraft] = field(default_factory=dict)

    @property
    def total_score(self) -> int:
        return round(mean(self.score_parts.values()))

    @property
    def duration_seconds(self) -> float:
        return round(self.end_seconds - self.start_seconds, 3)


@dataclass
class ChatCompletionResult:
    completion: Any
    response_format: str
    retry_count: int = 0
    response_format_error: str | None = None


async def analyze_episode(
    session: AsyncSession, episode_id: str, request: AnalysisRequest
) -> AnalysisRun:
    logger.info(
        "Starting analysis episode_id={} mode={} provider={} clip_types={} target_clip_count={}",
        episode_id,
        request.mode,
        request.ai_provider,
        request.clip_types,
        request.target_clip_count,
    )
    with observation(
        "analyze_episode",
        as_type="span",
        input={
            "episode_id": episode_id,
            "clip_types": request.clip_types,
            "target_clip_count": request.target_clip_count,
            "platforms": request.platforms,
            "ai_provider": request.ai_provider,
            "mode": request.mode,
        },
        metadata={"operation": "analysis"},
    ) as span:
        episode = await session.get(Episode, episode_id)
        if episode is None:
            logger.warning("Analysis failed, episode not found episode_id={}", episode_id)
            raise ValueError("Episode not found")
        await publish_episode_event(
            episode_id,
            "analysis.started",
            "Analysis started",
            progress=10,
            data={"mode": request.mode, "provider": request.ai_provider},
        )

        context = await _get_context(session, episode_id)
        segments = await _get_segments(session, episode_id)
        if not segments:
            logger.warning("Analysis failed, transcript missing episode_id={}", episode_id)
            raise ValueError("Transcript is required before analysis")
        logger.debug(
            "Analysis input loaded episode_id={} has_context={} transcript_segments={}",
            episode_id,
            context is not None,
            len(segments),
        )

        await session.execute(delete(ClipCandidate).where(ClipCandidate.episode_id == episode_id))
        logger.debug("Cleared existing clip candidates episode_id={}", episode_id)
        run = AnalysisRun(
            episode_id=episode_id,
            mode=request.mode,
            status="running",
            request=request.model_dump(),
            summary=f"Finding short-form and highlight candidates with {request.ai_provider}.",
        )
        session.add(run)
        await session.flush()
        logger.info("Analysis run created episode_id={} analysis_run_id={}", episode_id, run.id)

        media_path = await _primary_audio_path(session, episode_id)
        logger.debug("Primary media path resolved episode_id={} media_path={}", episode_id, media_path)
        heuristic_drafts = _generate_drafts(episode, context, segments, request, media_path)
        await publish_episode_event(
            episode_id,
            "analysis.candidates",
            f"Shortlisted {len(heuristic_drafts)} candidate moments",
            progress=25,
            data={"candidate_count": len(heuristic_drafts)},
        )
        try:
            drafts, analysis_source = await _drafts_for_request(
                episode,
                context,
                segments,
                request,
                media_path,
                heuristic_drafts,
            )
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            await session.commit()
            safe_update(
                span,
                metadata={"error": type(exc).__name__, "message": str(exc)},
            )
            logger.exception("Analysis failed episode_id={} analysis_run_id={} error={}", episode_id, run.id, exc)
            await publish_episode_event(
                episode_id,
                "analysis.failed",
                str(exc),
                level="error",
                progress=100,
                data={"analysis_run_id": run.id, "error_type": type(exc).__name__},
            )
            raise ValueError(f"Analysis failed: {exc}") from exc

        logger.info(
            "Draft clips generated episode_id={} analysis_run_id={} draft_count={} source={}",
            episode_id,
            run.id,
            len(drafts),
            analysis_source,
        )

        for rank, draft in enumerate(drafts, start=1):
            clip = ClipCandidate(
                episode_id=episode_id,
                analysis_run_id=run.id,
                clip_type=draft.clip_type,
                moment_type=draft.moment_type,
                status="recommended",
                start_seconds=draft.start_seconds,
                end_seconds=draft.end_seconds,
                duration_seconds=draft.duration_seconds,
                excerpt=draft.excerpt,
                reasoning=draft.reasoning,
                rank=rank,
            )
            session.add(clip)
            await session.flush()
            session.add(_score_from_draft(clip.id, draft))
            for platform in request.platforms:
                session.add(_metadata_for_clip(clip.id, platform, episode, context, draft))

        episode.status = "analyzed"
        run.status = "completed"
        run.summary = (
            f"Generated {len(drafts)} recommended clips across {', '.join(request.clip_types)} "
            f"using {analysis_source}."
        )
        await session.commit()
        await session.refresh(run)
        logger.info(
            "Analysis run completed episode_id={} analysis_run_id={} generated_clip_count={}",
            episode_id,
            run.id,
            len(drafts),
        )
        await publish_episode_event(
            episode_id,
            "analysis.saved",
            f"Saved {len(drafts)} clips",
            level="success",
            progress=95,
            data={"analysis_run_id": run.id, "analysis_source": analysis_source, "clip_count": len(drafts)},
        )
        safe_update(
            span,
            output={
                "analysis_run_id": run.id,
                "generated_clip_count": len(drafts),
                "top_score": drafts[0].total_score if drafts else None,
                "analysis_source": analysis_source,
            },
        )
        return run


async def _drafts_for_request(
    episode: Episode,
    context: EpisodeContext | None,
    segments: list[TranscriptSegment],
    request: AnalysisRequest,
    media_path: Path | None,
    heuristic_drafts: list[DraftClip],
) -> tuple[list[DraftClip], str]:
    sorted_heuristic = sorted(heuristic_drafts, key=lambda item: item.total_score, reverse=True)
    if request.mode == "mock":
        await publish_episode_event(
            episode.id,
            "analysis.heuristic",
            "Using local heuristic scoring",
            progress=75,
            data={"candidate_count": len(sorted_heuristic)},
        )
        return sorted_heuristic[: request.target_clip_count], "heuristic"

    try:
        llm_drafts = await _generate_llm_drafts(
            episode,
            context,
            segments,
            request,
            media_path,
            sorted_heuristic,
        )
    except Exception as exc:
        if request.mode == "openai":
            raise
        logger.warning(
            "LLM analysis failed in hybrid mode, falling back to heuristics episode_id={} error={}",
            episode.id,
            exc,
        )
        await publish_episode_event(
            episode.id,
            "analysis.fallback",
            "LLM failed; using heuristic fallback",
            level="warning",
            progress=80,
            data={"error": str(exc), "error_type": type(exc).__name__},
        )
        return sorted_heuristic[: request.target_clip_count], "heuristic_fallback"

    if not llm_drafts:
        if request.mode == "openai":
            raise RuntimeError("LLM returned no clip candidates")
        await publish_episode_event(
            episode.id,
            "analysis.fallback",
            "LLM returned no clips; using heuristic fallback",
            level="warning",
            progress=80,
        )
        return sorted_heuristic[: request.target_clip_count], "heuristic_fallback"

    combined = _complete_with_heuristics(llm_drafts, sorted_heuristic, request)
    await publish_episode_event(
        episode.id,
        "analysis.llm_completed",
        f"LLM selected {len(llm_drafts)} clips",
        level="success",
        progress=85,
        data={"llm_clip_count": len(llm_drafts), "final_clip_count": len(combined[: request.target_clip_count])},
    )
    return combined[: request.target_clip_count], f"llm:{request.ai_provider}"


async def _generate_llm_drafts(
    episode: Episode,
    context: EpisodeContext | None,
    segments: list[TranscriptSegment],
    request: AnalysisRequest,
    media_path: Path | None,
    heuristic_drafts: list[DraftClip],
) -> list[DraftClip]:
    settings = get_settings()
    client = make_chat_client(settings, request.ai_provider)
    model = chat_model_name(settings, request.ai_provider)
    candidates, candidate_map = _llm_candidate_payloads(heuristic_drafts, request)
    if not candidates:
        raise RuntimeError("No candidate moments are available for LLM analysis")

    payload = {
        "episode": _episode_payload(episode),
        "context": _context_payload(context),
        "request": request.model_dump(),
        "transcript": {
            "segment_count": len(segments),
            "duration_seconds": round(segments[-1].end_seconds, 3) if segments else 0,
        },
        "candidate_moments": candidates,
    }
    messages = [
        {"role": "system", "content": _llm_system_prompt()},
        {"role": "user", "content": _llm_user_prompt(payload)},
    ]
    trace_metadata = {
        "episode_id": episode.id,
        "episode_title": episode.title,
        "operation": "analysis_llm",
        "provider": request.ai_provider,
        "prompt_version": LLM_PROMPT_VERSION,
        "target_clip_count": request.target_clip_count,
        "candidate_count": len(candidates),
        "platforms": request.platforms,
        "capture_llm_io": settings.langfuse_capture_llm_io,
    }

    with observation(
        "llm_clip_analysis",
        as_type="generation",
        input=_langfuse_llm_input(settings, messages, payload),
        metadata=trace_metadata,
        model=model,
        model_parameters=_llm_model_parameters(),
        version=LLM_PROMPT_VERSION,
    ) as span:
        logger.info(
            "Calling LLM for clip analysis episode_id={} provider={} model={} candidate_count={}",
            episode.id,
            request.ai_provider,
            model,
            len(candidates),
        )
        await publish_episode_event(
            episode.id,
            "llm.started",
            f"Calling {request.ai_provider.replace('_', ' ')}",
            progress=45,
            data={"model": model, "candidate_count": len(candidates), "platforms": request.platforms},
        )
        completion_result = await _create_chat_completion(client, model, messages)
        completion = completion_result.completion
        choice = completion.choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        content = choice.message.content or "{}"
        completion_metadata = _without_none(
            {
                **trace_metadata,
                **_completion_metadata(completion),
                "finish_reason": finish_reason,
                "response_format": completion_result.response_format,
                "retry_count": completion_result.retry_count,
                "response_format_error": completion_result.response_format_error,
                "raw_response_length": len(content),
                "raw_response_sha256": _sha256_text(content),
            }
        )
        safe_update(
            span,
            output=_langfuse_llm_raw_output(settings, content, finish_reason),
            usage_details=_llm_usage_details(completion),
            metadata=completion_metadata,
        )
        logger.info(
            "LLM clip analysis response received episode_id={} finish_reason={} content_length={}",
            episode.id,
            finish_reason,
            len(content),
        )
        await publish_episode_event(
            episode.id,
            "llm.response",
            "LLM response received",
            progress=70,
            data={"finish_reason": finish_reason, "content_length": len(content)},
        )
        response_payload = _load_json_response(content)
        drafts = _drafts_from_llm_response(response_payload, candidate_map, request, media_path)
        safe_update(
            span,
            output=_langfuse_llm_output(settings, content, response_payload, drafts, finish_reason),
            metadata={**completion_metadata, "parsed_clip_count": len(drafts)},
        )
        logger.info("LLM clip analysis completed episode_id={} clip_count={}", episode.id, len(drafts))
        await publish_episode_event(
            episode.id,
            "llm.parsed",
            f"Parsed {len(drafts)} LLM clips",
            progress=80,
            data={"clip_count": len(drafts)},
        )
        return drafts


async def _create_chat_completion(client, model: str, messages: list[dict[str, str]]) -> ChatCompletionResult:
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": LLM_TEMPERATURE,
        "max_tokens": LLM_MAX_TOKENS,
    }
    try:
        completion = await client.chat.completions.create(
            **kwargs,
            response_format=LLM_RESPONSE_FORMAT,
        )
        return ChatCompletionResult(completion=completion, response_format="json_object")
    except Exception as exc:
        if "response_format" not in str(exc).lower():
            raise
        logger.warning("Retrying LLM call without JSON response_format error={}", exc)
        completion = await client.chat.completions.create(**kwargs)
        return ChatCompletionResult(
            completion=completion,
            response_format="provider_default",
            retry_count=1,
            response_format_error=_clip_text(str(exc), 1200),
        )


def _llm_model_parameters() -> dict[str, Any]:
    return {
        "temperature": LLM_TEMPERATURE,
        "max_tokens": LLM_MAX_TOKENS,
        "response_format": LLM_RESPONSE_FORMAT["type"],
    }


def _langfuse_llm_input(settings: Any, messages: list[dict[str, str]], payload: dict[str, Any]) -> dict[str, Any]:
    if not settings.langfuse_capture_llm_io:
        return {
            "capture_disabled": True,
            "messages": [_message_digest(message) for message in messages],
            "payload_summary": _llm_payload_summary(payload),
        }
    return _truncate_for_langfuse(
        {
            "messages": messages,
            "prompt_payload": payload,
        },
        settings.langfuse_max_llm_io_chars,
    )


def _langfuse_llm_raw_output(settings: Any, content: str, finish_reason: str | None) -> dict[str, Any]:
    if not settings.langfuse_capture_llm_io:
        return {
            "capture_disabled": True,
            "assistant_message": {
                "role": "assistant",
                "content_length": len(content),
                "content_sha256": _sha256_text(content),
            },
            "finish_reason": finish_reason,
        }
    return _truncate_for_langfuse(
        {
            "assistant_message": {"role": "assistant", "content": content},
            "finish_reason": finish_reason,
        },
        settings.langfuse_max_llm_io_chars,
    )


def _langfuse_llm_output(
    settings: Any,
    content: str,
    response_payload: dict[str, Any],
    drafts: list[DraftClip],
    finish_reason: str | None,
) -> dict[str, Any]:
    capture_content = bool(settings.langfuse_capture_llm_io)
    output = {
        **_langfuse_llm_raw_output(settings, content, finish_reason),
        "parsed_json": response_payload if capture_content else _llm_response_summary(response_payload),
        "normalized_clips": [
            _draft_clip_trace_payload(draft, capture_content=capture_content) for draft in drafts
        ],
        "clip_count": len(drafts),
        "summary": response_payload.get("summary") if isinstance(response_payload, dict) else None,
    }
    return _truncate_for_langfuse(output, settings.langfuse_max_llm_io_chars)


def _message_digest(message: dict[str, str]) -> dict[str, Any]:
    content = message.get("content", "")
    return {
        "role": message.get("role"),
        "content_length": len(content),
        "content_sha256": _sha256_text(content),
    }


def _llm_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = payload.get("candidate_moments")
    candidate_items = candidates if isinstance(candidates, list) else []
    return {
        "episode": payload.get("episode"),
        "request": payload.get("request"),
        "transcript": payload.get("transcript"),
        "candidate_count": len(candidate_items),
        "candidate_ids": [candidate.get("id") for candidate in candidate_items if isinstance(candidate, dict)],
    }


def _llm_response_summary(payload: dict[str, Any]) -> dict[str, Any]:
    raw_clips = payload.get("clips") if isinstance(payload, dict) else None
    clips = raw_clips if isinstance(raw_clips, list) else []
    return {
        "clip_count": len(clips),
        "summary": payload.get("summary") if isinstance(payload, dict) else None,
        "source_candidate_ids": [
            clip.get("source_candidate_id") for clip in clips if isinstance(clip, dict)
        ],
    }


def _draft_clip_trace_payload(draft: DraftClip, *, capture_content: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "clip_type": draft.clip_type,
        "moment_type": draft.moment_type,
        "start_seconds": draft.start_seconds,
        "end_seconds": draft.end_seconds,
        "duration_seconds": draft.duration_seconds,
        "total_score": draft.total_score,
        "score_parts": draft.score_parts,
        "platforms": list(draft.metadata_by_platform.keys()),
    }
    if not capture_content:
        payload.update(
            {
                "excerpt_length": len(draft.excerpt),
                "excerpt_sha256": _sha256_text(draft.excerpt),
                "reasoning_length": len(draft.reasoning),
                "reasoning_sha256": _sha256_text(draft.reasoning),
            }
        )
        return payload

    payload.update(
        {
            "excerpt": draft.excerpt,
            "reasoning": draft.reasoning,
            "platform_metadata": {
                platform: _platform_metadata_trace_payload(metadata)
                for platform, metadata in draft.metadata_by_platform.items()
            },
        }
    )
    return payload


def _platform_metadata_trace_payload(metadata: PlatformMetadataDraft) -> dict[str, Any]:
    return {
        "title": metadata.title,
        "hook": metadata.hook,
        "caption": metadata.caption,
        "soft_cta": metadata.soft_cta,
        "business_cta": metadata.business_cta,
        "hashtags": metadata.hashtags,
        "pinned_comment": metadata.pinned_comment,
        "thumbnail_concepts": metadata.thumbnail_concepts,
        "risk_flags": metadata.risk_flags,
    }


def _completion_metadata(completion: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("id", "created", "model", "system_fingerprint"):
        value = getattr(completion, key, None)
        if value is not None:
            metadata[f"completion_{key}"] = value
    return metadata


def _llm_usage_details(completion: Any) -> dict[str, int] | None:
    usage = getattr(completion, "usage", None)
    if usage is None:
        return None

    details = {
        "input": _usage_int(usage, "prompt_tokens", "input_tokens"),
        "output": _usage_int(usage, "completion_tokens", "output_tokens"),
        "total": _usage_int(usage, "total_tokens"),
    }
    cleaned = {key: value for key, value in details.items() if value is not None}
    return cleaned or None


def _usage_int(usage: Any, *names: str) -> int | None:
    for name in names:
        value = getattr(usage, name, None)
        if isinstance(value, int):
            return value
    return None


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _truncate_for_langfuse(value: Any, max_chars: int) -> Any:
    if isinstance(value, str):
        return _truncate_trace_text(value, max_chars)
    if isinstance(value, list):
        return [_truncate_for_langfuse(item, max_chars) for item in value]
    if isinstance(value, dict):
        return {key: _truncate_for_langfuse(item, max_chars) for key, item in value.items()}
    return value


def _truncate_trace_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n...[truncated {omitted} chars]"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _generate_drafts(
    episode: Episode,
    context: EpisodeContext | None,
    segments: list[TranscriptSegment],
    request: AnalysisRequest,
    media_path: Path | None,
) -> list[DraftClip]:
    terms = _context_terms(episode, context, request)
    logger.debug(
        "Generating drafts episode_id={} context_term_count={} segment_count={}",
        episode.id,
        len(terms),
        len(segments),
    )
    seed_scores = [(_segment_signal(segment, terms), index) for index, segment in enumerate(segments)]
    seed_scores = sorted(seed_scores, reverse=True)[: max(12, request.target_clip_count * 3)]
    drafts: list[DraftClip] = []

    for clip_type in request.clip_types:
        min_duration, max_duration = _duration_range(clip_type, request)
        for signal, index in seed_scores:
            if signal < 1:
                continue
            start, end, excerpt = _window_for_seed(segments, index, min_duration, max_duration)
            if _is_duplicate_window(drafts, clip_type, start, end):
                continue
            moment_type = _moment_type(excerpt)
            audio_score = audio_confidence_for_range(media_path, start, end)
            score_parts = _score_parts(excerpt, signal, audio_score, clip_type, context, request)
            drafts.append(
                DraftClip(
                    clip_type=clip_type,
                    moment_type=moment_type,
                    start_seconds=round(start, 3),
                    end_seconds=round(end, 3),
                    excerpt=excerpt,
                    reasoning=_reasoning(clip_type, moment_type, excerpt, context, request),
                    score_parts=score_parts,
                )
            )
    if not drafts:
        logger.warning("No signal-based drafts generated episode_id={}, using fallback window", episode.id)
        start, end, excerpt = _window_for_seed(segments, 0, 30, 90)
        audio_score = audio_confidence_for_range(media_path, start, end)
        drafts.append(
            DraftClip(
                clip_type="short",
                moment_type="expert_insight",
                start_seconds=start,
                end_seconds=end,
                excerpt=excerpt,
                reasoning="Fallback recommendation from the opening transcript window.",
                score_parts=_score_parts(excerpt, 1, audio_score, "short", context, request),
            )
        )
    logger.debug("Generated draft clip candidates episode_id={} count={}", episode.id, len(drafts))
    return drafts


def _llm_candidate_payloads(
    drafts: list[DraftClip], request: AnalysisRequest
) -> tuple[list[dict[str, Any]], dict[str, DraftClip]]:
    limit = min(max(request.target_clip_count * 4, 12), 40)
    candidates: list[dict[str, Any]] = []
    candidate_map: dict[str, DraftClip] = {}
    for index, draft in enumerate(drafts[:limit], start=1):
        candidate_id = f"candidate_{index}"
        candidate_map[candidate_id] = draft
        candidates.append(
            {
                "id": candidate_id,
                "clip_type": draft.clip_type,
                "moment_type": draft.moment_type,
                "start_seconds": draft.start_seconds,
                "end_seconds": draft.end_seconds,
                "duration_seconds": draft.duration_seconds,
                "excerpt": _clip_text(draft.excerpt, 1200),
                "heuristic_reasoning": draft.reasoning,
                "heuristic_total_score": draft.total_score,
                "heuristic_score_parts": draft.score_parts,
            }
        )
    return candidates, candidate_map


def _episode_payload(episode: Episode) -> dict[str, Any]:
    return {
        "id": episode.id,
        "title": episode.title,
        "guest_name": episode.guest_name,
        "guest_role": episode.guest_role,
        "guest_company": episode.guest_company,
        "recording_date": episode.recording_date,
        "theme": episode.theme,
    }


def _context_payload(context: EpisodeContext | None) -> dict[str, Any]:
    if context is None:
        return {}
    return {
        "icp": context.icp,
        "target_audience": context.target_audience,
        "audience_pain_points": context.audience_pain_points,
        "tkxel_services": context.tkxel_services,
        "hot_topic": context.hot_topic,
        "business_objectives": context.business_objectives,
        "episode_plan": context.episode_plan,
        "preferred_platforms": context.preferred_platforms,
        "editor_notes": context.editor_notes,
    }


def _llm_system_prompt() -> str:
    return (
        "You are AURORA PRISM, an expert podcast clip strategist for B2B technology content. "
        "Select the moments most likely to perform as YouTube Shorts, TikTok clips, Instagram Reels, "
        "LinkedIn clips, and longer highlights. You optimize for strong hooks, audience relevance, "
        "business value, guest authority, factual safety, and clean standalone context. "
        "Return valid JSON only. Do not invent transcript claims or timestamps."
    )


def _llm_user_prompt(payload: dict[str, Any]) -> str:
    schema = {
        "clips": [
            {
                "source_candidate_id": "candidate_1",
                "clip_type": "short",
                "moment_type": "hot_take|expert_insight|future_prediction|business_value|practical_advice|story",
                "start_seconds": 123.0,
                "end_seconds": 183.0,
                "excerpt": "Use or lightly trim the candidate transcript excerpt.",
                "reasoning": "Why this moment should be clipped and who it serves.",
                "score_parts": {key: 80 for key in SCORE_KEYS},
                "platform_metadata": {
                    "youtube_shorts": {
                        "title": "Searchable, specific title under 95 characters",
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
        "summary": "Brief summary of selection strategy.",
    }
    return (
        "Choose the best clip recommendations from candidate_moments.\n"
        "Rules:\n"
        "- Return JSON matching output_schema.\n"
        "- Select only from candidate_moments by source_candidate_id.\n"
        "- Return at most target_clip_count clips.\n"
        "- Prefer shorts that work in 30-90 seconds and highlights that work in 3-6 minutes unless custom durations are provided.\n"
        "- You may tighten timestamps by up to 5 seconds, but keep the selected moment inside the source candidate.\n"
        "- Include platform_metadata for every requested platform.\n"
        "- Titles should be native to the platform, specific, and not clickbait.\n"
        "- Captions should preserve factual accuracy and avoid unsupported claims.\n"
        "- All score_parts values must be integers from 0 to 100.\n\n"
        f"output_schema:\n{json.dumps(schema, ensure_ascii=True)}\n\n"
        f"input_json:\n{json.dumps(payload, ensure_ascii=True)}"
    )


def _load_json_response(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning(
            "LLM response JSON parse failed, trying tolerant recovery error={} content_length={}",
            exc,
            len(content),
        )
        recovered = _recover_llm_json_response(content)
        if recovered is not None:
            return recovered
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise ValueError("LLM response did not contain JSON")
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as nested_exc:
            raise ValueError(f"LLM response JSON was malformed: {nested_exc}") from nested_exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM JSON response must be an object")
    return parsed


def _recover_llm_json_response(content: str) -> dict[str, Any] | None:
    clips_section = _extract_array_section(content, "clips")
    if not clips_section:
        return None

    clips = _recover_json_objects(clips_section)
    if not clips:
        logger.warning("Tolerant LLM JSON recovery found no complete clip objects")
        return None

    summary = _recover_json_string(content, "summary")
    logger.warning("Recovered malformed LLM response clip_count={}", len(clips))
    return {"clips": clips, "summary": summary or "Recovered from malformed LLM JSON response."}


def _extract_array_section(content: str, key: str) -> str | None:
    key_match = re.search(rf'"{re.escape(key)}"\s*:', content)
    if not key_match:
        return None
    start = content.find("[", key_match.end())
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(content)):
        char = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return content[start + 1 : index]

    return content[start + 1 :]


def _recover_json_objects(content: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False

    for index, char in enumerate(content):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start is not None:
                raw_object = content[start : index + 1]
                try:
                    parsed = json.loads(raw_object)
                except json.JSONDecodeError as exc:
                    logger.warning("Skipping malformed recovered LLM clip object error={}", exc)
                else:
                    if isinstance(parsed, dict):
                        objects.append(parsed)
                start = None

    return objects


def _recover_json_string(content: str, key: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"', content, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(f'"{match.group(1)}"')
    except json.JSONDecodeError:
        return match.group(1)


def _drafts_from_llm_response(
    payload: dict[str, Any],
    candidate_map: dict[str, DraftClip],
    request: AnalysisRequest,
    media_path: Path | None,
) -> list[DraftClip]:
    raw_clips = payload.get("clips")
    if not isinstance(raw_clips, list):
        raise ValueError("LLM response missing clips list")

    drafts: list[DraftClip] = []
    for raw in raw_clips:
        if not isinstance(raw, dict):
            continue
        source_id = str(raw.get("source_candidate_id") or raw.get("candidate_id") or "")
        source = candidate_map.get(source_id)
        if source is None:
            logger.warning("Skipping LLM clip with unknown source_candidate_id={}", source_id)
            continue

        clip_type = _choice(raw.get("clip_type"), request.clip_types, source.clip_type)
        start, end = _coerce_llm_window(raw, source, clip_type, request)
        excerpt = _clip_text(str(raw.get("excerpt") or source.excerpt), 1200)
        if len(excerpt.split()) < 5:
            excerpt = source.excerpt
        moment_type = _safe_moment_type(str(raw.get("moment_type") or source.moment_type))
        audio_score = audio_confidence_for_range(media_path, start, end)
        score_parts = _normalize_score_parts(raw.get("score_parts"), source.score_parts, audio_score)
        metadata = _platform_metadata_from_llm(raw.get("platform_metadata"), request.platforms)
        draft = DraftClip(
            clip_type=clip_type,
            moment_type=moment_type,
            start_seconds=round(start, 3),
            end_seconds=round(end, 3),
            excerpt=excerpt,
            reasoning=_clip_text(str(raw.get("reasoning") or source.reasoning), 700),
            score_parts=score_parts,
            metadata_by_platform=metadata,
        )
        if not _is_duplicate_window(drafts, draft.clip_type, draft.start_seconds, draft.end_seconds):
            drafts.append(draft)

    return sorted(drafts, key=lambda item: item.total_score, reverse=True)


def _complete_with_heuristics(
    llm_drafts: list[DraftClip], heuristic_drafts: list[DraftClip], request: AnalysisRequest
) -> list[DraftClip]:
    completed = list(llm_drafts)
    for draft in heuristic_drafts:
        if len(completed) >= request.target_clip_count:
            break
        if not _is_duplicate_window(completed, draft.clip_type, draft.start_seconds, draft.end_seconds):
            completed.append(draft)
    return sorted(completed, key=lambda item: item.total_score, reverse=True)


def _choice(value: object, allowed: list[str], fallback: str) -> str:
    candidate = str(value or "").strip()
    return candidate if candidate in allowed else fallback


def _coerce_llm_window(
    raw: dict[str, Any], source: DraftClip, clip_type: str, request: AnalysisRequest
) -> tuple[float, float]:
    start = _coerce_float(raw.get("start_seconds"), source.start_seconds)
    end = _coerce_float(raw.get("end_seconds"), source.end_seconds)
    source_start = max(0.0, source.start_seconds - 5)
    source_end = source.end_seconds + 5
    start = max(source_start, min(start, source_end - 1))
    end = max(start + 1, min(end, source_end))

    min_duration, max_duration = _duration_range(clip_type, request)
    duration = end - start
    if duration < max(5, min_duration - 15) or duration > max_duration + 15:
        return source.start_seconds, source.end_seconds
    return start, end


def _safe_moment_type(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    allowed = {moment_type for moment_type, _ in MOMENT_TYPES}
    return normalized if normalized in allowed else "expert_insight"


def _normalize_score_parts(
    value: object, fallback: dict[str, int], audio_score: int
) -> dict[str, int]:
    raw = value if isinstance(value, dict) else {}
    normalized: dict[str, int] = {}
    for key in SCORE_KEYS:
        default = audio_score if key == "audio_confidence" else fallback.get(key, 65)
        normalized[key] = _bounded(_coerce_int(raw.get(key), default))
    normalized["audio_confidence"] = audio_score
    return normalized


def _platform_metadata_from_llm(
    value: object, platforms: list[str]
) -> dict[str, PlatformMetadataDraft]:
    raw_metadata = value if isinstance(value, dict) else {}
    metadata: dict[str, PlatformMetadataDraft] = {}
    for platform in platforms:
        raw = raw_metadata.get(platform)
        if not isinstance(raw, dict):
            continue
        title = _clip_text(str(raw.get("title") or ""), 95)
        hook = _clip_text(str(raw.get("hook") or ""), 220)
        caption = _clip_text(str(raw.get("caption") or ""), 1200)
        if not title or not hook or not caption:
            continue
        metadata[platform] = PlatformMetadataDraft(
            title=title,
            hook=hook,
            caption=caption,
            soft_cta=_clip_text(str(raw.get("soft_cta") or ""), 260)
            or "Watch the full BetterTech conversation for the broader context.",
            business_cta=_clip_text(str(raw.get("business_cta") or ""), 260)
            or "Talk to TKXEL about turning AI strategy into practical product outcomes.",
            hashtags=_normalize_hashtags(raw.get("hashtags")),
            pinned_comment=_clip_text(str(raw.get("pinned_comment") or ""), 260) or None,
            thumbnail_concepts=_normalize_thumbnail_concepts(raw.get("thumbnail_concepts")),
            risk_flags=_list_of_strings(raw.get("risk_flags"), limit=8),
        )
    return metadata


def _normalize_hashtags(value: object) -> list[str]:
    hashtags = []
    for item in _list_of_strings(value, limit=12):
        tag = item.strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = f"#{tag.lstrip('#')}"
        hashtags.append(tag.replace(" ", ""))
    return list(dict.fromkeys(hashtags))[:12] or ["#BetterTech", "#AI"]


def _normalize_thumbnail_concepts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    concepts: list[dict[str, Any]] = []
    for item in value[:3]:
        if isinstance(item, dict):
            concepts.append(
                {
                    str(key): _clip_text(str(val), 220)
                    for key, val in item.items()
                    if val is not None
                }
            )
    return concepts


def _list_of_strings(value: object, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clip_text(str(item), 160) for item in value[:limit] if str(item).strip()]


def _coerce_float(value: object, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_int(value: object, fallback: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


def _duration_range(clip_type: str, request: AnalysisRequest) -> tuple[int, int]:
    if request.duration_min_seconds and request.duration_max_seconds:
        return request.duration_min_seconds, request.duration_max_seconds
    if clip_type == "highlight":
        return 180, 360
    return 30, 90


def _window_for_seed(
    segments: list[TranscriptSegment], seed_index: int, min_duration: int, max_duration: int
) -> tuple[float, float, str]:
    seed = segments[seed_index]
    start = max(0.0, seed.start_seconds - 3)
    end = seed.end_seconds
    texts = [f"{seed.speaker + ': ' if seed.speaker else ''}{seed.text}"]

    cursor = seed_index + 1
    while end - start < min_duration and cursor < len(segments):
        next_segment = segments[cursor]
        if next_segment.start_seconds - end > 12 and end - start > 20:
            break
        end = next_segment.end_seconds
        texts.append(f"{next_segment.speaker + ': ' if next_segment.speaker else ''}{next_segment.text}")
        cursor += 1

    if end - start > max_duration:
        end = start + max_duration
    excerpt = _clip_text(" ".join(texts))
    return start, end, excerpt


def _score_parts(
    excerpt: str,
    signal: int,
    audio_score: int,
    clip_type: str,
    context: EpisodeContext | None,
    request: AnalysisRequest,
) -> dict[str, int]:
    lower = excerpt.lower()
    hook_words = sum(1 for word in ["why", "how", "problem", "risk", "future", "mistake", "cost"] if word in lower)
    platform_bonus = 6 if clip_type == "short" and {"tiktok", "youtube_shorts"} & set(request.platforms) else 3
    instruction_bonus = 8 if request.custom_instructions and _matches_text(lower, request.custom_instructions) else 0
    service_bonus = 10 if context and context.tkxel_services and _matches_text(lower, context.tkxel_services) else 0
    topic_bonus = 12 if context and context.hot_topic and _matches_text(lower, context.hot_topic) else 4
    return {
        "icp_relevance": _bounded(58 + signal * 4 + instruction_bonus),
        "tkxel_alignment": _bounded(55 + service_bonus + signal * 2),
        "hook_strength": _bounded(52 + hook_words * 7 + platform_bonus),
        "virality_potential": _bounded(54 + hook_words * 5 + (8 if clip_type == "short" else 2)),
        "business_value": _bounded(58 + signal * 3 + service_bonus),
        "guest_authority": _bounded(68 + (6 if "founder" in lower or "chief" in lower else 0)),
        "topic_fit": _bounded(56 + topic_bonus + signal * 3),
        "audio_confidence": audio_score,
    }


def _score_from_draft(clip_id: str, draft: DraftClip) -> ClipScore:
    parts = draft.score_parts
    return ClipScore(
        clip_id=clip_id,
        total_score=draft.total_score,
        icp_relevance=parts["icp_relevance"],
        tkxel_alignment=parts["tkxel_alignment"],
        hook_strength=parts["hook_strength"],
        virality_potential=parts["virality_potential"],
        business_value=parts["business_value"],
        guest_authority=parts["guest_authority"],
        topic_fit=parts["topic_fit"],
        audio_confidence=parts["audio_confidence"],
        explanation=(
            "Score blends business/context relevance, hook potential, platform fit, guest authority, "
            "and audio confidence around the selected timestamp."
        ),
    )


def _metadata_for_clip(
    clip_id: str,
    platform: str,
    episode: Episode,
    context: EpisodeContext | None,
    draft: DraftClip,
) -> ClipMetadata:
    llm_metadata = draft.metadata_by_platform.get(platform)
    if llm_metadata is not None:
        return ClipMetadata(
            clip_id=clip_id,
            platform=platform,
            title=llm_metadata.title,
            hook=llm_metadata.hook,
            caption=llm_metadata.caption,
            soft_cta=llm_metadata.soft_cta,
            business_cta=llm_metadata.business_cta,
            hashtags=llm_metadata.hashtags,
            pinned_comment=llm_metadata.pinned_comment,
            thumbnail_concepts=llm_metadata.thumbnail_concepts,
            risk_flags=llm_metadata.risk_flags,
        )

    platform_label = PLATFORM_LABELS.get(platform, platform.replace("_", " ").title())
    theme = context.hot_topic if context and context.hot_topic else episode.theme or "AI strategy"
    title = _title_for(draft, theme)
    hook = f"What if the strongest moment in this conversation is the part most teams overlook?"
    if draft.clip_type == "highlight":
        hook = f"A deeper cut from {episode.guest_name or 'the guest'} on {theme}."
    caption = (
        f"{title}\n\n{_clip_text(draft.excerpt, 280)}\n\n"
        f"Built for {platform_label} with a focus on {theme}."
    )
    return ClipMetadata(
        clip_id=clip_id,
        platform=platform,
        title=title,
        hook=hook,
        caption=caption,
        soft_cta="Watch the full BetterTech conversation for the broader context.",
        business_cta="Talk to TKXEL about turning AI strategy into practical product outcomes.",
        hashtags=_hashtags(theme, platform),
        pinned_comment="Which part of this take should technology leaders debate next?",
        thumbnail_concepts=[
            {
                "headline": title[:58],
                "supporting_text": "Expert take from BetterTech",
                "layout": "Guest headshot left, bold quote/right, BetterTech mark in corner.",
                "tone": "sharp, credible, executive-friendly",
                "risk": "Low if the title stays specific and avoids exaggerated claims.",
            }
        ],
        risk_flags=[] if "guarantee" not in draft.excerpt.lower() else ["claims_review"],
    )


async def _get_context(session: AsyncSession, episode_id: str) -> EpisodeContext | None:
    result = await session.execute(select(EpisodeContext).where(EpisodeContext.episode_id == episode_id))
    context = result.scalar_one_or_none()
    logger.debug("Loaded episode context episode_id={} found={}", episode_id, context is not None)
    return context


async def _get_segments(session: AsyncSession, episode_id: str) -> list[TranscriptSegment]:
    result = await session.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.episode_id == episode_id)
        .order_by(TranscriptSegment.start_seconds)
    )
    segments = list(result.scalars())
    logger.debug("Loaded transcript segments episode_id={} count={}", episode_id, len(segments))
    return segments


async def _primary_audio_path(session: AsyncSession, episode_id: str) -> Path | None:
    result = await session.execute(
        select(Asset)
        .where(Asset.episode_id == episode_id, Asset.asset_type.in_(["audio", "video"]))
        .order_by(Asset.is_primary.desc(), Asset.created_at.desc())
    )
    asset = result.scalars().first()
    path = Path(asset.path) if asset else None
    logger.debug("Loaded primary media asset episode_id={} found={} path={}", episode_id, asset is not None, path)
    return path


def _context_terms(
    episode: Episode, context: EpisodeContext | None, request: AnalysisRequest
) -> set[str]:
    raw = " ".join(
        item or ""
        for item in [
            episode.title,
            episode.theme,
            episode.guest_role,
            episode.guest_company,
            context.icp if context else None,
            context.target_audience if context else None,
            context.audience_pain_points if context else None,
            context.tkxel_services if context else None,
            context.hot_topic if context else None,
            context.business_objectives if context else None,
            context.episode_plan if context else None,
            request.custom_instructions,
        ]
    )
    return {word for word in re.findall(r"[a-zA-Z][a-zA-Z0-9-]{3,}", raw.lower()) if word not in _STOPWORDS}


def _segment_signal(segment: TranscriptSegment, terms: set[str]) -> int:
    lower = segment.text.lower()
    term_hits = sum(1 for term in terms if term in lower)
    universal_hits = sum(
        1
        for term in [
            "ai",
            "data",
            "model",
            "business",
            "customer",
            "future",
            "risk",
            "problem",
            "cost",
            "revenue",
            "strategy",
            "regulation",
            "bias",
        ]
        if term in lower
    )
    return term_hits * 2 + universal_hits


def _moment_type(excerpt: str) -> str:
    words = set(re.findall(r"[a-zA-Z][a-zA-Z0-9-]+", excerpt.lower()))
    ranked = sorted(
        ((len(words & markers), moment_type) for moment_type, markers in MOMENT_TYPES),
        reverse=True,
    )
    return ranked[0][1] if ranked and ranked[0][0] else "expert_insight"


def _reasoning(
    clip_type: str, moment_type: str, excerpt: str, context: EpisodeContext | None, request: AnalysisRequest
) -> str:
    duration_label = "short-form social clip" if clip_type == "short" else "3-6 minute highlight"
    topic = context.hot_topic if context and context.hot_topic else "the selected episode theme"
    instruction = f" It also reflects the custom instruction: {request.custom_instructions}" if request.custom_instructions else ""
    return (
        f"Recommended as a {duration_label} because it reads as {moment_type.replace('_', ' ')} "
        f"and connects to {topic}. The excerpt has enough context for viewers to understand the idea "
        f"without needing the full episode.{instruction}"
    )


def _is_duplicate_window(drafts: list[DraftClip], clip_type: str, start: float, end: float) -> bool:
    for draft in drafts:
        if draft.clip_type != clip_type:
            continue
        overlap = max(0, min(end, draft.end_seconds) - max(start, draft.start_seconds))
        if overlap / max(1, min(end - start, draft.duration_seconds)) > 0.55:
            return True
    return False


def _matches_text(excerpt: str, source: str) -> bool:
    terms = [word for word in re.findall(r"[a-zA-Z][a-zA-Z0-9-]{4,}", source.lower()) if word not in _STOPWORDS]
    return any(term in excerpt for term in terms[:20])


def _title_for(draft: DraftClip, theme: str) -> str:
    if draft.clip_type == "highlight":
        return f"The deeper BetterTech take on {theme}"[:95]
    if draft.moment_type == "hot_take":
        return f"The uncomfortable truth about {theme}"[:95]
    if draft.moment_type == "future_prediction":
        return f"What happens next in {theme}"[:95]
    return f"A sharp BetterTech insight on {theme}"[:95]


def _hashtags(theme: str, platform: str) -> list[str]:
    words = [word.title() for word in re.findall(r"[A-Za-z][A-Za-z0-9]+", theme)[:3]]
    base = ["BetterTech", "AI", "TechLeadership"]
    if platform == "linkedin":
        base.append("DigitalTransformation")
    if platform in {"tiktok", "instagram_reels", "youtube_shorts"}:
        base.append("PodcastClips")
    return [f"#{word}" for word in dict.fromkeys(base + words)]


def _clip_text(text: str, limit: int = 900) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rsplit(" ", 1)[0] + "..."


def _bounded(value: int) -> int:
    return max(0, min(100, int(value)))


_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "because",
    "been",
    "being",
    "from",
    "have",
    "into",
    "more",
    "that",
    "their",
    "this",
    "with",
    "your",
    "will",
    "what",
    "when",
    "where",
    "which",
}
