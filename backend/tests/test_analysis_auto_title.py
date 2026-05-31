from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import AnalysisRun, ClipCandidate, Episode, TranscriptSegment
from app.schemas.api import AnalysisRequest
from app.services import analysis as analysis_module
from app.services import analysis_graph
from app.services.analysis import DraftClip, analyze_episode


async def test_analyze_episode_generates_default_episode_title(monkeypatch) -> None:
    sessionmaker = await _sessionmaker()
    title_calls: list[dict[str, object]] = []

    async def fake_suggest_episode_title(episode, context, segments, provider):
        title_calls.append(
            {
                "episode_id": episode.id,
                "segment_count": len(list(segments)),
                "provider": provider,
            }
        )
        return "Generated LLM Title"

    async def fake_run_section_analysis(*_args, **_kwargs):
        return (
            [
                DraftClip(
                    clip_type="short",
                    moment_type="expert_insight",
                    target_platform="linkedin",
                    purpose="LinkedIn",
                    start_seconds=0,
                    end_seconds=60,
                    excerpt="AI strategy needs practical product outcomes.",
                    reasoning="A complete business insight for the audience.",
                    score_parts={
                        "icp_relevance": 80,
                        "tkxel_alignment": 80,
                        "hook_strength": 80,
                        "virality_potential": 80,
                        "business_value": 80,
                        "guest_authority": 80,
                        "topic_fit": 80,
                        "audio_confidence": 80,
                    },
                )
            ],
            "test_graph",
        )

    monkeypatch.setattr(analysis_module, "suggest_episode_title", fake_suggest_episode_title)
    monkeypatch.setattr(analysis_graph, "run_section_analysis", fake_run_section_analysis)

    async with sessionmaker() as session:
        episode = Episode(id="episode-a", title="Untitled episode", status="draft")
        segment = TranscriptSegment(
            episode_id=episode.id,
            start_seconds=0,
            end_seconds=80,
            text="AI strategy needs practical product outcomes for enterprise teams.",
        )
        session.add_all([episode, segment])
        await session.commit()

        run = await analyze_episode(session, episode.id, AnalysisRequest(mode="mock"))

        await session.refresh(episode)
        assert run.status == "completed"
        assert episode.title == "Generated LLM Title"
        assert title_calls == [
            {"episode_id": "episode-a", "segment_count": 1, "provider": "azure_openai"}
        ]


async def test_analyze_episode_preserves_existing_outputs_and_continues_section_rank(monkeypatch) -> None:
    sessionmaker = await _sessionmaker()

    async def fake_run_section_analysis(*_args, **_kwargs):
        return (
            [
                DraftClip(
                    clip_type="short",
                    moment_type="expert_insight",
                    target_platform="linkedin",
                    purpose="LinkedIn",
                    start_seconds=90,
                    end_seconds=150,
                    excerpt="A new output excerpt.",
                    reasoning="Another strong reason.",
                    score_parts={
                        "icp_relevance": 80,
                        "tkxel_alignment": 80,
                        "hook_strength": 80,
                        "virality_potential": 80,
                        "business_value": 80,
                        "guest_authority": 80,
                        "topic_fit": 80,
                        "audio_confidence": 80,
                    },
                )
            ],
            "test_graph",
        )

    monkeypatch.setattr(analysis_graph, "run_section_analysis", fake_run_section_analysis)

    async with sessionmaker() as session:
        episode = Episode(id="episode-a", title="Existing title", status="draft")
        existing_run = AnalysisRun(id="run-existing", episode_id=episode.id, mode="mock", status="completed")
        existing_clip = ClipCandidate(
            id="clip-existing",
            episode_id=episode.id,
            analysis_run_id=existing_run.id,
            clip_type="short",
            target_platform="linkedin",
            purpose="LinkedIn",
            moment_type="expert_insight",
            status="recommended",
            start_seconds=0,
            end_seconds=60,
            duration_seconds=60,
            excerpt="Existing output excerpt.",
            reasoning="Existing reason.",
            rank=2,
        )
        segment = TranscriptSegment(
            episode_id=episode.id,
            start_seconds=0,
            end_seconds=180,
            text="AI strategy needs practical product outcomes for enterprise teams.",
        )
        session.add_all([episode, existing_run, existing_clip, segment])
        await session.commit()

        await analyze_episode(session, episode.id, AnalysisRequest(mode="mock"))

        clips = (
            await session.execute(
                select(ClipCandidate).order_by(ClipCandidate.rank)
            )
        ).scalars().all()
        assert len(clips) == 2
        assert clips[0].id == "clip-existing"
        assert [clip.rank for clip in clips] == [2, 3]


async def _sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
