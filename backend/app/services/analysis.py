from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import (
    AnalysisRun,
    Asset,
    ClipCandidate,
    ClipMetadata,
    Episode,
    EpisodeContext,
    TranscriptSegment,
)
from app.schemas.api import ANALYSIS_SECTION_DURATION_DEFAULTS, AnalysisRequest
from app.services.analysis_events import publish_analysis_event
from app.services.audio import audio_confidence_for_range
from app.services.llm import (
    langfuse_llm_input as _langfuse_llm_input,
    langfuse_llm_raw_output as _langfuse_llm_raw_output,
    llm_response_summary as _llm_response_summary,
    sha256_text as _sha256_text,
    suggest_episode_title,
    truncate_for_langfuse as _truncate_for_langfuse,
)
from app.services.observability import observation, safe_update
from app.services.transcripts import seconds_to_timestamp


PLATFORM_LABELS = {
    "youtube_shorts": "YouTube Shorts",
    "linkedin": "LinkedIn",
    "instagram_reels": "Instagram/Reels",
    "tiktok": "TikTok",
    "generic": "Highlight",
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
SUPPORTING_DOCUMENT_ASSET_TYPES = {"guest_document", "brand_reference", "document", "supporting_document"}
SUPPORTING_DOCUMENT_LIMIT = 5
SUPPORTING_DOCUMENT_CHAR_LIMIT = 2400


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
    target_platform: str = "generic"
    purpose: str = "Generic"
    metadata_by_platform: dict[str, PlatformMetadataDraft] = field(default_factory=dict)

    @property
    def total_score(self) -> int:
        return round(mean(self.score_parts.values()))

    @property
    def duration_seconds(self) -> float:
        return round(self.end_seconds - self.start_seconds, 3)


async def analyze_episode(
    session: AsyncSession, episode_id: str, request: AnalysisRequest
) -> AnalysisRun:
    logger.info(
        "Starting section analysis episode_id={} mode={} provider={} sections={}",
        episode_id,
        request.mode,
        request.ai_provider,
        {key: config.target_count for key, config in request.enabled_sections()},
    )
    with observation(
        "analyze_episode",
        as_type="span",
        input={
            "episode_id": episode_id,
            "sections": {key: config.target_count for key, config in request.enabled_sections()},
            "ai_provider": request.ai_provider,
            "mode": request.mode,
        },
        metadata={"operation": "analysis"},
    ) as span:
        episode = await session.get(Episode, episode_id)
        if episode is None:
            logger.warning("Analysis failed, episode not found episode_id={}", episode_id)
            raise ValueError("Episode not found")
        await publish_analysis_event(
            episode_id,
            "analysis.started",
            "Preparing transcript and context",
            progress=10,
            data={"mode": request.mode, "provider": request.ai_provider},
        )

        context = await _get_context(session, episode_id)
        segments = await _get_segments(session, episode_id)
        if not segments:
            logger.warning("Analysis failed, transcript missing episode_id={}", episode_id)
            raise ValueError("Transcript is required before analysis")
        supporting_documents = await _get_supporting_documents(session, episode_id)
        logger.debug(
            "Analysis input loaded episode_id={} has_context={} transcript_segments={} supporting_documents={}",
            episode_id,
            context is not None,
            len(segments),
            len(supporting_documents),
        )
        await publish_analysis_event(
            episode_id,
            "analysis.inputs_loaded",
            "Transcript and context loaded",
            progress=20,
            data={
                "segment_count": len(segments),
                "has_context": context is not None,
                "supporting_document_count": len(supporting_documents),
            },
        )

        run = AnalysisRun(
            episode_id=episode_id,
            mode=request.mode,
            status="running",
            request=request.model_dump(),
            summary="Finding section-specific outputs with Azure OpenAI specialists.",
        )
        session.add(run)
        await session.flush()
        logger.info("Analysis run created episode_id={} analysis_run_id={}", episode_id, run.id)

        media_path = await _primary_audio_path(session, episode_id)
        logger.debug("Primary media path resolved episode_id={} media_path={}", episode_id, media_path)
        heuristic_drafts = _generate_drafts(
            episode, context, segments, request, media_path, supporting_documents
        )
        await publish_analysis_event(
            episode_id,
            "analysis.candidates",
            f"Shortlisted {len(heuristic_drafts)} candidate moments",
            progress=35,
            data={"candidate_count": len(heuristic_drafts)},
        )
        try:
            from app.services.analysis_graph import run_section_analysis

            await publish_analysis_event(
                episode_id,
                "analysis.section_specialists",
                "Running section specialists",
                progress=55,
                data={"sections": [key for key, _ in request.enabled_sections()]},
            )
            drafts, analysis_source = await run_section_analysis(
                episode,
                context,
                segments,
                request,
                media_path,
                heuristic_drafts,
                supporting_documents,
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
            raise ValueError(f"Analysis failed: {exc}") from exc

        logger.info(
            "Draft clips generated episode_id={} analysis_run_id={} draft_count={} source={}",
            episode_id,
            run.id,
            len(drafts),
            analysis_source,
        )
        generated_title = None
        if _should_auto_title_episode(episode):
            await publish_analysis_event(
                episode_id,
                "analysis.title_generation",
                "Generating episode title",
                progress=75,
                data={"provider": request.ai_provider},
            )
            original_title = episode.title
            episode.title = await suggest_episode_title(
                episode,
                context,
                segments[:8],
                request.ai_provider,
            )
            if episode.title != original_title:
                generated_title = episode.title
                logger.info(
                    "Analysis generated episode title episode_id={} title={}",
                    episode_id,
                    generated_title,
                )

        await publish_analysis_event(
            episode_id,
            "analysis.saving",
            "Saving recommended outputs",
            progress=85,
            data={"draft_count": len(drafts), "analysis_source": analysis_source},
        )

        rank_offsets = await _section_rank_offsets(session, episode_id)
        for rank, draft in enumerate(drafts, start=1):
            purpose_rank = 1 + sum(
                1 for item in drafts[: rank - 1] if item.target_platform == draft.target_platform
            )
            purpose_rank += rank_offsets.get(draft.target_platform, 0)
            clip = ClipCandidate(
                episode_id=episode_id,
                analysis_run_id=run.id,
                clip_type=draft.clip_type,
                target_platform=draft.target_platform,
                purpose=draft.purpose,
                moment_type=draft.moment_type,
                status="recommended",
                start_seconds=draft.start_seconds,
                end_seconds=draft.end_seconds,
                duration_seconds=draft.duration_seconds,
                excerpt=draft.excerpt,
                reasoning=draft.reasoning,
                rank=purpose_rank,
            )
            session.add(clip)
            await session.flush()
            metadata_platforms = list(draft.metadata_by_platform) or [draft.target_platform]
            for platform in metadata_platforms:
                session.add(_metadata_for_clip(clip.id, platform, episode, context, draft))

        episode.status = "analyzed"
        run.status = "completed"
        run.summary = (
            f"Generated {len(drafts)} section outputs across "
            f"{', '.join(key for key, _ in request.enabled_sections())} using {analysis_source}."
        )
        await session.commit()
        await session.refresh(run)
        logger.info(
            "Analysis run completed episode_id={} analysis_run_id={} generated_clip_count={}",
            episode_id,
            run.id,
            len(drafts),
        )
        safe_update(
            span,
            output={
                "analysis_run_id": run.id,
                "generated_clip_count": len(drafts),
                "analysis_source": analysis_source,
                "generated_title": generated_title,
            },
        )
        return run


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


def _draft_clip_trace_payload(draft: DraftClip, *, capture_content: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "clip_type": draft.clip_type,
        "moment_type": draft.moment_type,
        "start_seconds": draft.start_seconds,
        "end_seconds": draft.end_seconds,
        "duration_seconds": draft.duration_seconds,
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


def _should_auto_title_episode(episode: Episode) -> bool:
    return episode.title.strip().lower() == "untitled episode"


async def _section_rank_offsets(session: AsyncSession, episode_id: str) -> dict[str, int]:
    result = await session.execute(
        select(ClipCandidate.target_platform, func.max(ClipCandidate.rank))
        .where(ClipCandidate.episode_id == episode_id)
        .group_by(ClipCandidate.target_platform)
    )
    return {
        str(target_platform): int(max_rank or 0)
        for target_platform, max_rank in result.all()
    }


def _generate_drafts(
    episode: Episode,
    context: EpisodeContext | None,
    segments: list[TranscriptSegment],
    request: AnalysisRequest,
    media_path: Path | None,
    supporting_documents: list[Asset],
) -> list[DraftClip]:
    terms = _context_terms(episode, context, request, supporting_documents)
    logger.debug(
        "Generating drafts episode_id={} context_term_count={} segment_count={}",
        episode.id,
        len(terms),
        len(segments),
    )
    seed_scores = [(_segment_signal(segment, terms), index) for index, segment in enumerate(segments)]
    seed_scores = sorted(seed_scores, reverse=True)[: max(12, _max_section_count(request) * 6)]
    drafts: list[DraftClip] = []

    for clip_type, min_duration, max_duration in _request_clip_windows(request):
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


def _request_clip_types(request: AnalysisRequest) -> list[str]:
    if request.sections:
        clip_types: list[str] = []
        if any(key != "highlights" and config.enabled for key, config in request.sections.items()):
            clip_types.append("short")
        if request.sections.get("highlights") and request.sections["highlights"].enabled:
            clip_types.append("highlight")
        return clip_types or ["short"]
    return list(request.clip_types)


def _request_clip_windows(request: AnalysisRequest) -> list[tuple[str, int, int]]:
    if not request.sections:
        return [(clip_type, *_duration_range(clip_type, request)) for clip_type in request.clip_types]

    windows: list[tuple[str, int, int]] = []
    for key, config in request.enabled_sections():
        clip_type = "highlight" if key == "highlights" else "short"
        min_duration, max_duration = ANALYSIS_SECTION_DURATION_DEFAULTS[key]
        if request.duration_min_seconds and request.duration_max_seconds:
            min_duration = request.duration_min_seconds
            max_duration = request.duration_max_seconds
        if config.duration_min_seconds is not None:
            min_duration = config.duration_min_seconds
        if config.duration_max_seconds is not None:
            max_duration = config.duration_max_seconds
        windows.append((clip_type, min_duration, max_duration))

    # Build broader source windows first. Shorter sections can trim longer candidates, but a
    # too-short source cannot satisfy longer custom durations.
    ordered = sorted(dict.fromkeys(windows), key=lambda item: (item[0] != "highlight", item[1]), reverse=True)
    return ordered or [("short", 30, 90)]


def _max_section_count(request: AnalysisRequest) -> int:
    counts = [config.target_count for _, config in request.enabled_sections()]
    return max(counts) if counts else request.target_clip_count


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
    }


def _context_payload(context: EpisodeContext | None) -> dict[str, Any]:
    if context is None:
        return {}
    return {
        "icp": context.icp,
        "target_audience": context.target_audience,
        "audience_pain_points": context.audience_pain_points,
        "hot_topic": context.hot_topic,
        "business_objectives": context.business_objectives,
        "episode_plan": context.episode_plan,
        "preferred_platforms": context.preferred_platforms,
        "editor_notes": context.editor_notes,
    }


def _supporting_document_payloads(documents: list[Asset]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for asset in documents[:SUPPORTING_DOCUMENT_LIMIT]:
        text = (asset.extracted_text or "").strip()
        if not text:
            continue
        payloads.append(
            {
                "filename": asset.filename,
                "asset_type": asset.asset_type,
                "content_type": asset.content_type,
                "text_excerpt": _clip_text(text, SUPPORTING_DOCUMENT_CHAR_LIMIT),
            }
        )
    return payloads


def _llm_system_prompt() -> str:
    return (
        "You are AURORA PRISM, an expert podcast clip strategist for B2B technology content. "
        "Select the moments most likely to perform as YouTube Shorts, TikTok clips, Instagram Reels, "
        "LinkedIn clips, and longer highlights. You optimize for strong hooks, audience relevance, "
        "business value, guest authority, factual safety, and clean standalone context. "
        "Use supporting documents as background context only; selected clips must stay grounded in transcript moments. "
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
        "- Use supporting_documents when present to improve audience, positioning, and factual context.\n"
        "- Include platform_metadata for every requested platform.\n"
        "- Titles should be native to the platform, specific, and not clickbait.\n"
        "- Captions should preserve factual accuracy and avoid unsupported claims.\n"
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
        metadata = _platform_metadata_from_llm(raw.get("platform_metadata"), request.platforms)
        draft = DraftClip(
            clip_type=clip_type,
            moment_type=moment_type,
            start_seconds=round(start, 3),
            end_seconds=round(end, 3),
            excerpt=excerpt,
            reasoning=_clip_text(str(raw.get("reasoning") or source.reasoning), 700),
            score_parts=source.score_parts,
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
    topic_bonus = 12 if context and context.hot_topic and _matches_text(lower, context.hot_topic) else 4
    return {
        "icp_relevance": _bounded(58 + signal * 4 + instruction_bonus),
        "tkxel_alignment": _bounded(55 + signal * 2),
        "hook_strength": _bounded(52 + hook_words * 7 + platform_bonus),
        "virality_potential": _bounded(54 + hook_words * 5 + (8 if clip_type == "short" else 2)),
        "business_value": _bounded(58 + signal * 3),
        "guest_authority": _bounded(68 + (6 if "founder" in lower or "chief" in lower else 0)),
        "topic_fit": _bounded(56 + topic_bonus + signal * 3),
        "audio_confidence": audio_score,
    }


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
    topic = context.hot_topic if context and context.hot_topic else "AI strategy"
    title = _title_for(draft, topic)
    hook = f"What if the strongest moment in this conversation is the part most teams overlook?"
    if draft.clip_type == "highlight":
        hook = f"A deeper cut from {episode.guest_name or 'the guest'} on {topic}."
    caption = (
        f"{title}\n\n{_clip_text(draft.excerpt, 280)}\n\n"
        f"Built for {platform_label} with a focus on {topic}."
    )
    return ClipMetadata(
        clip_id=clip_id,
        platform=platform,
        title=title,
        hook=hook,
        caption=caption,
        soft_cta="Watch the full BetterTech conversation for the broader context.",
        business_cta="Talk to TKXEL about turning AI strategy into practical product outcomes.",
        hashtags=_hashtags(topic, platform),
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


async def _get_supporting_documents(session: AsyncSession, episode_id: str) -> list[Asset]:
    result = await session.execute(
        select(Asset)
        .where(
            Asset.episode_id == episode_id,
            Asset.asset_type.in_(SUPPORTING_DOCUMENT_ASSET_TYPES),
            Asset.extracted_text.is_not(None),
            Asset.extracted_text != "",
        )
        .order_by(Asset.created_at.desc())
        .limit(SUPPORTING_DOCUMENT_LIMIT)
    )
    documents = list(result.scalars())
    logger.debug("Loaded supporting documents episode_id={} count={}", episode_id, len(documents))
    return documents


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
    episode: Episode,
    context: EpisodeContext | None,
    request: AnalysisRequest,
    supporting_documents: list[Asset] | None = None,
) -> set[str]:
    context_items = [
        episode.title,
        episode.guest_role,
        episode.guest_company,
        context.icp if context else None,
        context.target_audience if context else None,
        context.audience_pain_points if context else None,
        context.hot_topic if context else None,
        context.business_objectives if context else None,
        context.episode_plan if context else None,
        request.custom_instructions,
    ]
    if supporting_documents:
        context_items.extend(asset.extracted_text for asset in supporting_documents)
    raw = " ".join(item or "" for item in context_items)
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
    topic = context.hot_topic if context and context.hot_topic else "the selected hot topic"
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


def _title_for(draft: DraftClip, topic: str) -> str:
    if draft.clip_type == "highlight":
        return f"The deeper BetterTech take on {topic}"[:95]
    if draft.moment_type == "hot_take":
        return f"The uncomfortable truth about {topic}"[:95]
    if draft.moment_type == "future_prediction":
        return f"What happens next in {topic}"[:95]
    return f"A sharp BetterTech insight on {topic}"[:95]


def _hashtags(topic: str, platform: str) -> list[str]:
    words = [word.title() for word in re.findall(r"[A-Za-z][A-Za-z0-9]+", topic)[:3]]
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
