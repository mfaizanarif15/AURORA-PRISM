from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import (
    _get_owned_clip,
    _get_owned_episode,
    _get_owned_export,
    _get_owned_render,
    delete_episode,
    update_episode,
)
from app.db.base import Base
from app.models import AnalysisRun, ClipCandidate, Episode, ExportPack, RenderedClip, User
from app.schemas.api import EpisodeUpdate


async def test_owned_episode_lookup_filters_by_user() -> None:
    sessionmaker = await _sessionmaker()
    async with sessionmaker() as session:
        user_a, user_b = _users()
        episode_a = Episode(id="episode-a", owner_user_id=user_a.id, title="A", status="draft")
        episode_b = Episode(id="episode-b", owner_user_id=user_b.id, title="B", status="draft")
        session.add_all([user_a, user_b, episode_a, episode_b])
        await session.commit()

        assert await _get_owned_episode(session, "episode-a", user_a.id) is not None
        assert await _get_owned_episode(session, "episode-b", user_a.id) is None


async def test_owned_child_lookups_filter_by_episode_owner() -> None:
    sessionmaker = await _sessionmaker()
    async with sessionmaker() as session:
        user_a, user_b = _users()
        episode = Episode(id="episode-b", owner_user_id=user_b.id, title="B", status="draft")
        run = AnalysisRun(id="run-b", episode_id=episode.id, mode="mock", status="completed")
        clip = ClipCandidate(
            id="clip-b",
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
        rendered = RenderedClip(id="render-b", clip_id=clip.id, render_type="original", status="completed")
        export = ExportPack(id="export-b", episode_id=episode.id, status="completed", manifest={})
        session.add_all([user_a, user_b, episode, run, clip, rendered, export])
        await session.commit()

        assert await _get_owned_clip(session, clip.id, user_a.id) is None
        assert await _get_owned_render(session, rendered.id, user_a.id) is None
        assert await _get_owned_export(session, export.id, user_a.id) is None
        assert await _get_owned_clip(session, clip.id, user_b.id) is not None
        assert await _get_owned_render(session, rendered.id, user_b.id) is not None
        assert await _get_owned_export(session, export.id, user_b.id) is not None


async def test_update_episode_normalizes_blank_title_and_optional_fields() -> None:
    sessionmaker = await _sessionmaker()
    async with sessionmaker() as session:
        user_a, _user_b = _users()
        episode = Episode(
            id="episode-a",
            owner_user_id=user_a.id,
            title="Original title",
            guest_name="Original Guest",
            status="draft",
        )
        session.add_all([user_a, episode])
        await session.commit()

        request = SimpleNamespace(state=SimpleNamespace(auth_user=SimpleNamespace(id=user_a.id)))
        response = await update_episode(
            "episode-a",
            EpisodeUpdate(title="   ", guest_name="  "),
            request,
            session,
        )

        await session.refresh(episode)
        assert response.title == "Untitled episode"
        assert response.guest_name is None
        assert episode.title == "Untitled episode"
        assert episode.guest_name is None


async def test_delete_episode_removes_owned_episode_and_children() -> None:
    sessionmaker = await _sessionmaker()
    async with sessionmaker() as session:
        user_a, _user_b = _users()
        episode = Episode(id="episode-a", owner_user_id=user_a.id, title="A", status="draft")
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
        rendered = RenderedClip(id="render-a", clip_id=clip.id, render_type="original", status="completed")
        export = ExportPack(id="export-a", episode_id=episode.id, status="completed", manifest={})
        session.add_all([user_a, episode, run, clip, rendered, export])
        await session.commit()

        request = SimpleNamespace(state=SimpleNamespace(auth_user=SimpleNamespace(id=user_a.id)))
        response = await delete_episode("episode-a", request, session)

        assert response == {"status": "deleted", "episode_id": "episode-a"}
        assert await session.get(Episode, "episode-a") is None
        assert await session.get(ClipCandidate, "clip-a") is None
        assert await session.get(RenderedClip, "render-a") is None
        assert await session.get(ExportPack, "export-a") is None


async def _sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _users() -> tuple[User, User]:
    return (
        User(
            id="user-a",
            username="a",
            display_name="User A",
            role="Content Operations",
            password_hash="hash",
        ),
        User(
            id="user-b",
            username="b",
            display_name="User B",
            role="Content Operations",
            password_hash="hash",
        ),
    )
