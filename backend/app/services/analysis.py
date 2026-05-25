from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

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
from app.services.audio import audio_confidence_for_range
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


@dataclass
class DraftClip:
    clip_type: str
    moment_type: str
    start_seconds: float
    end_seconds: float
    excerpt: str
    reasoning: str
    score_parts: dict[str, int]

    @property
    def total_score(self) -> int:
        return round(mean(self.score_parts.values()))

    @property
    def duration_seconds(self) -> float:
        return round(self.end_seconds - self.start_seconds, 3)


async def analyze_episode(
    session: AsyncSession, episode_id: str, request: AnalysisRequest
) -> AnalysisRun:
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
            raise ValueError("Episode not found")

        context = await _get_context(session, episode_id)
        segments = await _get_segments(session, episode_id)
        if not segments:
            raise ValueError("Transcript is required before analysis")

        await session.execute(delete(ClipCandidate).where(ClipCandidate.episode_id == episode_id))
        run = AnalysisRun(
            episode_id=episode_id,
            mode=request.mode,
            status="running",
            request=request.model_dump(),
            summary=f"Finding short-form and highlight candidates with {request.ai_provider}.",
        )
        session.add(run)
        await session.flush()

        media_path = await _primary_audio_path(session, episode_id)
        drafts = _generate_drafts(episode, context, segments, request, media_path)
        drafts = sorted(drafts, key=lambda item: item.total_score, reverse=True)[
            : request.target_clip_count
        ]

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
            f"using {request.ai_provider} provider settings."
        )
        await session.commit()
        await session.refresh(run)
        safe_update(
            span,
            output={
                "analysis_run_id": run.id,
                "generated_clip_count": len(drafts),
                "top_score": drafts[0].total_score if drafts else None,
            },
        )
        return run


def _generate_drafts(
    episode: Episode,
    context: EpisodeContext | None,
    segments: list[TranscriptSegment],
    request: AnalysisRequest,
    media_path: Path | None,
) -> list[DraftClip]:
    terms = _context_terms(episode, context, request)
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
    return drafts


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
    return result.scalar_one_or_none()


async def _get_segments(session: AsyncSession, episode_id: str) -> list[TranscriptSegment]:
    result = await session.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.episode_id == episode_id)
        .order_by(TranscriptSegment.start_seconds)
    )
    return list(result.scalars())


async def _primary_audio_path(session: AsyncSession, episode_id: str) -> Path | None:
    result = await session.execute(
        select(Asset)
        .where(Asset.episode_id == episode_id, Asset.asset_type.in_(["audio", "video"]))
        .order_by(Asset.is_primary.desc(), Asset.created_at.desc())
    )
    asset = result.scalars().first()
    return Path(asset.path) if asset else None


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
