from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import AnalysisRun, ClipCandidate, Episode, RenderedClip
from app.schemas.api import RenderRequest
from app.services import rendering


def test_ffmpeg_executable_uses_system_path(monkeypatch) -> None:
    monkeypatch.setattr(rendering.shutil, "which", lambda name: "/usr/bin/ffmpeg")

    assert rendering._ffmpeg_executable() == "/usr/bin/ffmpeg"


def test_ffmpeg_executable_returns_none_when_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(rendering.shutil, "which", lambda name: None)
    monkeypatch.setattr(rendering, "_imageio_ffmpeg_executable", lambda: None)

    assert rendering._ffmpeg_executable() is None


def test_render_request_defaults_to_no_outputs() -> None:
    assert RenderRequest().render_types == []


async def test_render_clip_with_no_render_types_is_noop() -> None:
    sessionmaker = await _sessionmaker()
    async with sessionmaker() as session:
        episode = Episode(id="episode-a", title="A", status="draft")
        run = AnalysisRun(id="run-a", episode_id=episode.id, mode="mock", status="completed")
        clip = ClipCandidate(
            id="clip-a",
            episode_id=episode.id,
            analysis_run_id=run.id,
            clip_type="short",
            moment_type="expert_insight",
            status="recommended",
            start_seconds=0,
            end_seconds=60,
            duration_seconds=60,
            excerpt="A useful clip excerpt.",
            reasoning="A strong reason.",
            rank=1,
        )
        session.add_all([episode, run, clip])
        await session.commit()

        rendered = await rendering.render_clip(
            session,
            clip.id,
            RenderRequest(render_types=[]),
        )

        assert rendered == []
        result = await session.execute(select(RenderedClip))
        assert result.scalars().all() == []


async def _sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
