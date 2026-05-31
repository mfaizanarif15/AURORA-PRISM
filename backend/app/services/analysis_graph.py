from __future__ import annotations

import operator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from loguru import logger

from app.core.config import get_settings
from app.models import Asset, Episode, EpisodeContext, TranscriptSegment
from app.schemas.api import ANALYSIS_SECTION_DURATION_DEFAULTS, AnalysisRequest
from app.services.analysis import (
    LLM_MAX_TOKENS,
    LLM_PROMPT_VERSION,
    LLM_TEMPERATURE,
    DraftClip,
    PlatformMetadataDraft,
    _clip_text,
    _coerce_float,
    _is_duplicate_window,
    _load_json_response,
    _safe_moment_type,
    _supporting_document_payloads,
)
from app.services.llm import (
    SECTION_PROMPT_VERSION,
    call_langchain_chat,
    section_system_prompt,
    section_user_prompt,
)


SECTION_ORDER = ("tiktok", "instagram_reels", "youtube_shorts", "linkedin", "highlights")


@dataclass(frozen=True)
class SectionSpec:
    key: str
    purpose: str
    target_platform: str
    clip_type: str
    min_seconds: int
    max_seconds: int
    focus: str


@dataclass(frozen=True)
class SectionJob:
    spec: SectionSpec
    target_count: int


@dataclass
class SectionResult:
    key: str
    drafts: list[DraftClip]
    source: str
    error: str | None = None


class SectionGraphState(TypedDict, total=False):
    episode: Episode
    context: EpisodeContext | None
    segments: list[TranscriptSegment]
    request: AnalysisRequest
    media_path: Path | None
    supporting_documents: list[Asset]
    candidate_drafts: list[DraftClip]
    section_jobs: list[SectionJob]
    section_job: SectionJob
    section_results: Annotated[list[SectionResult], operator.add]
    final_drafts: list[DraftClip]
    analysis_source: str


SECTION_SPECS: dict[str, SectionSpec] = {
    "tiktok": SectionSpec(
        key="tiktok",
        purpose="TikTok",
        target_platform="tiktok",
        clip_type="short",
        min_seconds=30,
        max_seconds=60,
        focus="fast hook, trend-native pacing, high retention, and a strong first line",
    ),
    "instagram_reels": SectionSpec(
        key="instagram_reels",
        purpose="Reels",
        target_platform="instagram_reels",
        clip_type="short",
        min_seconds=30,
        max_seconds=75,
        focus="visual/social shareability, concise insight, and a clean standalone takeaway",
    ),
    "youtube_shorts": SectionSpec(
        key="youtube_shorts",
        purpose="YouTube Shorts",
        target_platform="youtube_shorts",
        clip_type="short",
        min_seconds=30,
        max_seconds=90,
        focus="searchable standalone idea, clear retention arc, and strong replay value",
    ),
    "linkedin": SectionSpec(
        key="linkedin",
        purpose="LinkedIn",
        target_platform="linkedin",
        clip_type="short",
        min_seconds=45,
        max_seconds=120,
        focus="executive relevance, business clarity, and practical B2B insight",
    ),
    "highlights": SectionSpec(
        key="highlights",
        purpose="Highlight",
        target_platform="generic",
        clip_type="highlight",
        min_seconds=180,
        max_seconds=360,
        focus="deeper narrative, strategic value, and a complete 3-6 minute segment",
    ),
}


async def run_section_analysis(
    episode: Episode,
    context: EpisodeContext | None,
    segments: list[TranscriptSegment],
    request: AnalysisRequest,
    media_path: Path | None,
    heuristic_drafts: list[DraftClip],
    supporting_documents: list[Asset],
) -> tuple[list[DraftClip], str]:
    graph = _build_section_graph()
    settings = get_settings()
    state = await graph.ainvoke(
        {
            "episode": episode,
            "context": context,
            "segments": segments,
            "request": request,
            "media_path": media_path,
            "supporting_documents": supporting_documents,
            "candidate_drafts": heuristic_drafts,
            "section_results": [],
        },
        {
            "max_concurrency": settings.llm_analysis_parallelism,
            "configurable": {"max_concurrency": settings.llm_analysis_parallelism},
        },
    )
    return state.get("final_drafts", []), state.get("analysis_source", "section_graph")


def plan_section_jobs(request: AnalysisRequest) -> list[SectionJob]:
    jobs: list[SectionJob] = []
    for key in SECTION_ORDER:
        config = request.sections.get(key)
        if not config or not config.enabled:
            continue
        spec = SECTION_SPECS[key]
        min_seconds, max_seconds = ANALYSIS_SECTION_DURATION_DEFAULTS[key]
        if request.duration_min_seconds and request.duration_max_seconds:
            min_seconds = request.duration_min_seconds
            max_seconds = request.duration_max_seconds
        if config.duration_min_seconds is not None:
            min_seconds = config.duration_min_seconds
        if config.duration_max_seconds is not None:
            max_seconds = config.duration_max_seconds
        spec = replace(
            spec,
            min_seconds=min_seconds,
            max_seconds=max_seconds,
        )
        jobs.append(SectionJob(spec=spec, target_count=config.target_count))
    return jobs


def _build_section_graph():
    builder = StateGraph(SectionGraphState)
    builder.add_node("load_inputs", _load_inputs)
    builder.add_node("build_candidates", _build_candidates)
    builder.add_node("plan_sections", _plan_sections)
    builder.add_node("section_specialist", _section_specialist)
    builder.add_node("merge_results", _merge_results)
    builder.add_edge(START, "load_inputs")
    builder.add_edge("load_inputs", "build_candidates")
    builder.add_edge("build_candidates", "plan_sections")
    builder.add_conditional_edges("plan_sections", _fan_out_sections, ["section_specialist"])
    builder.add_edge("section_specialist", "merge_results")
    builder.add_edge("merge_results", END)
    return builder.compile()


def _load_inputs(state: SectionGraphState) -> dict[str, Any]:
    return {}


def _build_candidates(state: SectionGraphState) -> dict[str, Any]:
    return {"candidate_drafts": sorted(state["candidate_drafts"], key=lambda item: item.total_score, reverse=True)}


def _plan_sections(state: SectionGraphState) -> dict[str, Any]:
    jobs = plan_section_jobs(state["request"])
    logger.info("Planned section analysis jobs count={} sections={}", len(jobs), [job.spec.key for job in jobs])
    return {"section_jobs": jobs}


def _fan_out_sections(state: SectionGraphState) -> list[Send]:
    return [Send("section_specialist", {**state, "section_job": job}) for job in state["section_jobs"]]


async def _section_specialist(state: SectionGraphState) -> dict[str, Any]:
    job = state["section_job"]
    candidates, candidate_map = _section_candidate_payloads(state["candidate_drafts"], job)
    if not candidates:
        result = SectionResult(
            key=job.spec.key,
            drafts=_fallback_for_section(job, state["candidate_drafts"]),
            source="heuristic_fallback",
            error="No candidates matched section constraints",
        )
        return {"section_results": [result]}

    if state["request"].mode == "mock":
        return {
            "section_results": [
                SectionResult(
                    key=job.spec.key,
                    drafts=_fallback_for_section(job, state["candidate_drafts"]),
                    source="heuristic",
                )
            ]
        }

    try:
        drafts = await _call_section_llm(state, job, candidates, candidate_map)
    except Exception as exc:
        if state["request"].mode == "openai":
            raise
        logger.warning("Section LLM failed section={} error={}", job.spec.key, exc)
        drafts = []
        error = str(exc)
    else:
        error = None

    source = "llm"
    if not drafts:
        drafts = _fallback_for_section(job, state["candidate_drafts"])
        source = "heuristic_fallback"
    return {"section_results": [SectionResult(key=job.spec.key, drafts=drafts, source=source, error=error)]}


async def _call_section_llm(
    state: SectionGraphState,
    job: SectionJob,
    candidates: list[dict[str, Any]],
    candidate_map: dict[str, DraftClip],
) -> list[DraftClip]:
    settings = get_settings()
    payload = _section_payload(state, job, candidates)
    system_text = section_system_prompt(purpose=job.spec.purpose, focus=job.spec.focus)
    user_text = section_user_prompt(payload)
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_text},
    ]
    trace_metadata = {
        "episode_id": state["episode"].id,
        "episode_title": state["episode"].title,
        "operation": "section_analysis_llm",
        "section": job.spec.key,
        "purpose": job.spec.purpose,
        "provider": state["request"].ai_provider,
        "prompt_version": SECTION_PROMPT_VERSION,
        "target_count": job.target_count,
        "candidate_count": len(candidates),
        "capture_llm_io": settings.langfuse_capture_llm_io,
    }

    logger.info(
        "Calling section LLM episode_id={} section={} candidate_count={}",
        state["episode"].id,
        job.spec.key,
        len(candidates),
    )
    result = await call_langchain_chat(
        operation="section_analysis_llm",
        name="llm_section_analysis",
        provider=state["request"].ai_provider,
        settings=settings,
        messages=messages,
        payload=payload,
        metadata=trace_metadata,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        prompt_version=f"{LLM_PROMPT_VERSION}:{SECTION_PROMPT_VERSION}",
    )
    parsed = _load_json_response(result.content)
    drafts = _section_drafts_from_response(parsed, candidate_map, job, state["media_path"])
    logger.info(
        "Section LLM response parsed episode_id={} section={} valid_output_count={}",
        state["episode"].id,
        job.spec.key,
        len(drafts),
    )
    return drafts[: job.target_count]


def _merge_results(state: SectionGraphState) -> dict[str, Any]:
    results = sorted(
        state.get("section_results", []),
        key=lambda item: SECTION_ORDER.index(item.key) if item.key in SECTION_ORDER else len(SECTION_ORDER),
    )
    final_drafts = [draft for result in results for draft in result.drafts]
    source_parts = [f"{result.key}:{result.source}" for result in results]
    return {
        "final_drafts": final_drafts,
        "analysis_source": f"langgraph_azure({', '.join(source_parts)})",
    }


def _section_candidate_payloads(
    drafts: list[DraftClip], job: SectionJob
) -> tuple[list[dict[str, Any]], dict[str, DraftClip]]:
    matching = [
        draft
        for draft in drafts
        if draft.clip_type == job.spec.clip_type
        and job.spec.min_seconds <= draft.duration_seconds <= job.spec.max_seconds
    ]
    if not matching:
        matching = [draft for draft in drafts if draft.clip_type == job.spec.clip_type]
    limit = min(max(job.target_count * 5, 12), 40)
    candidates: list[dict[str, Any]] = []
    candidate_map: dict[str, DraftClip] = {}
    for index, draft in enumerate(matching[:limit], start=1):
        candidate_id = f"{job.spec.key}_candidate_{index}"
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


def _section_payload(state: SectionGraphState, job: SectionJob, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "section": {
            "key": job.spec.key,
            "purpose": job.spec.purpose,
            "target_platform": job.spec.target_platform,
            "clip_type": job.spec.clip_type,
            "target_count": job.target_count,
            "duration_min_seconds": job.spec.min_seconds,
            "duration_max_seconds": job.spec.max_seconds,
            "focus": job.spec.focus,
        },
        "episode": {
            "id": state["episode"].id,
            "title": state["episode"].title,
            "guest_name": state["episode"].guest_name,
            "guest_role": state["episode"].guest_role,
            "guest_company": state["episode"].guest_company,
            "recording_date": state["episode"].recording_date,
        },
        "context": _context_payload(state["context"]),
        "request": state["request"].model_dump(),
        "transcript": {
            "segment_count": len(state["segments"]),
            "duration_seconds": round(state["segments"][-1].end_seconds, 3) if state["segments"] else 0,
        },
        "supporting_documents": _supporting_document_payloads(state["supporting_documents"]),
        "candidate_moments": candidates,
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


def _section_drafts_from_response(
    payload: dict[str, Any],
    candidate_map: dict[str, DraftClip],
    job: SectionJob,
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
            logger.warning("Skipping section clip with unknown source_candidate_id={}", source_id)
            continue
        window = _coerce_section_window(raw, source, job)
        if window is None:
            continue
        start, end = window
        metadata = _metadata_for_section(raw.get("platform_metadata"), job)
        draft = DraftClip(
            clip_type=job.spec.clip_type,
            target_platform=job.spec.target_platform,
            purpose=job.spec.purpose,
            moment_type=_safe_moment_type(str(raw.get("moment_type") or source.moment_type)),
            start_seconds=round(start, 3),
            end_seconds=round(end, 3),
            excerpt=_clip_text(str(raw.get("excerpt") or source.excerpt), 1200) or source.excerpt,
            reasoning=_clip_text(str(raw.get("reasoning") or source.reasoning), 700),
            score_parts=source.score_parts,
            metadata_by_platform=metadata,
        )
        if not _is_duplicate_window(drafts, draft.clip_type, draft.start_seconds, draft.end_seconds):
            drafts.append(draft)
        if len(drafts) >= job.target_count:
            break
    return sorted(drafts, key=lambda item: item.total_score, reverse=True)


def _coerce_section_window(raw: dict[str, Any], source: DraftClip, job: SectionJob) -> tuple[float, float] | None:
    start = _coerce_float(raw.get("start_seconds"), source.start_seconds)
    end = _coerce_float(raw.get("end_seconds"), source.end_seconds)
    start = max(source.start_seconds, min(start, source.end_seconds - 1))
    end = max(start + 1, min(end, source.end_seconds))
    duration = end - start
    if job.spec.min_seconds <= duration <= job.spec.max_seconds:
        return start, end
    if job.spec.min_seconds <= source.duration_seconds <= job.spec.max_seconds:
        return source.start_seconds, source.end_seconds
    logger.warning(
        "Skipping section clip outside duration constraints section={} duration={} source_duration={}",
        job.spec.key,
        duration,
        source.duration_seconds,
    )
    return None


def _metadata_for_section(value: object, job: SectionJob) -> dict[str, PlatformMetadataDraft]:
    raw_metadata = value if isinstance(value, dict) else {}
    raw = raw_metadata.get(job.spec.target_platform)
    if not isinstance(raw, dict):
        return {}
    title = _clip_text(str(raw.get("title") or ""), 95)
    hook = _clip_text(str(raw.get("hook") or ""), 220)
    caption = _clip_text(str(raw.get("caption") or ""), 1200)
    if not title or not hook or not caption:
        return {}
    return {
        job.spec.target_platform: PlatformMetadataDraft(
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
    }


def _fallback_for_section(job: SectionJob, drafts: list[DraftClip]) -> list[DraftClip]:
    matching = [
        draft
        for draft in drafts
        if draft.clip_type == job.spec.clip_type
        and job.spec.min_seconds <= draft.duration_seconds <= job.spec.max_seconds
    ]
    if not matching:
        matching = [draft for draft in drafts if draft.clip_type == job.spec.clip_type]
    selected: list[DraftClip] = []
    for draft in sorted(matching, key=lambda item: item.total_score, reverse=True):
        if len(selected) >= job.target_count:
            break
        start = draft.start_seconds
        end = min(draft.end_seconds, start + job.spec.max_seconds)
        if end - start < job.spec.min_seconds:
            continue
        candidate = replace(
            draft,
            target_platform=job.spec.target_platform,
            purpose=job.spec.purpose,
            start_seconds=round(start, 3),
            end_seconds=round(end, 3),
            reasoning=(
                f"{draft.reasoning} Selected by {job.spec.purpose} fallback using section-specific "
                "heuristic scoring."
            ),
            metadata_by_platform={},
        )
        if not _is_duplicate_window(selected, candidate.clip_type, candidate.start_seconds, candidate.end_seconds):
            selected.append(candidate)
    return selected


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
