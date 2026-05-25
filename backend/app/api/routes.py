from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_session
from app.models import (
    ApprovalEvent,
    Asset,
    ClipCandidate,
    Episode,
    EpisodeContext,
    ExportPack,
    RenderedClip,
    TranscriptSegment,
)
from app.schemas.api import (
    AiProviderRead,
    AnalysisRequest,
    AnalysisRunRead,
    AssetRead,
    ClipRead,
    ClipStatusUpdate,
    EpisodeContextUpdate,
    EpisodeCreate,
    EpisodeRead,
    ExportPackRead,
    RenderRequest,
    TranscriptUploadResult,
)
from app.core.config import get_settings
from app.services.ai_clients import provider_status
from app.services.analysis import analyze_episode
from app.services.assets import save_upload
from app.services.exports import create_export_pack
from app.services.observability import langfuse_status
from app.services.rendering import render_clip
from app.services.transcripts import parse_transcript

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ai/providers", response_model=AiProviderRead)
async def ai_providers() -> dict:
    return provider_status(get_settings())


@router.get("/observability/langfuse")
async def langfuse_observability() -> dict:
    return langfuse_status(get_settings())


@router.get("/episodes", response_model=list[EpisodeRead])
async def list_episodes(session: AsyncSession = Depends(get_session)) -> list[EpisodeRead]:
    result = await session.execute(select(Episode).order_by(Episode.created_at.desc()))
    episodes = list(result.scalars())
    return [await _episode_read(session, episode) for episode in episodes]


@router.post("/episodes", response_model=EpisodeRead)
async def create_episode(
    payload: EpisodeCreate, session: AsyncSession = Depends(get_session)
) -> EpisodeRead:
    episode = Episode(**payload.model_dump(), status="draft")
    session.add(episode)
    await session.commit()
    await session.refresh(episode)
    return await _episode_read(session, episode)


@router.get("/episodes/{episode_id}", response_model=EpisodeRead)
async def get_episode(episode_id: str, session: AsyncSession = Depends(get_session)) -> EpisodeRead:
    episode = await session.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    return await _episode_read(session, episode)


@router.patch("/episodes/{episode_id}/context")
async def upsert_context(
    episode_id: str,
    payload: EpisodeContextUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict:
    episode = await session.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    result = await session.execute(select(EpisodeContext).where(EpisodeContext.episode_id == episode_id))
    context = result.scalar_one_or_none()
    values = payload.model_dump()
    if context is None:
        context = EpisodeContext(episode_id=episode_id, **values)
        session.add(context)
    else:
        for key, value in values.items():
            setattr(context, key, value)
    await session.commit()
    return {"status": "saved", "episode_id": episode_id}


@router.post("/episodes/{episode_id}/assets", response_model=AssetRead)
async def upload_asset(
    episode_id: str,
    asset_type: str = Form(...),
    tags: str = Form(""),
    is_primary: bool = Form(False),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> AssetRead:
    if await session.get(Episode, episode_id) is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    path, extracted_text = await save_upload(episode_id, file, asset_type)
    asset = Asset(
        episode_id=episode_id,
        asset_type=asset_type,
        filename=file.filename or path.name,
        content_type=file.content_type,
        path=str(path),
        extracted_text=extracted_text,
        tags=[tag.strip() for tag in tags.split(",") if tag.strip()],
        is_primary=is_primary,
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return _asset_read(asset)


@router.post("/episodes/{episode_id}/transcript", response_model=TranscriptUploadResult)
async def upload_transcript(
    episode_id: str,
    content: str | None = Form(None),
    source_format: str = Form("txt"),
    file: UploadFile | None = File(None),
    session: AsyncSession = Depends(get_session),
) -> TranscriptUploadResult:
    if await session.get(Episode, episode_id) is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    if file is not None:
        raw = (await file.read()).decode("utf-8", errors="ignore")
        source_format = Path(file.filename or "transcript.txt").suffix.lstrip(".") or source_format
    elif content:
        raw = content
    else:
        raise HTTPException(status_code=400, detail="Provide transcript content or file")

    parsed = parse_transcript(raw, source_format)
    await session.execute(delete(TranscriptSegment).where(TranscriptSegment.episode_id == episode_id))
    for segment in parsed:
        session.add(
            TranscriptSegment(
                episode_id=episode_id,
                speaker=segment.speaker,
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                text=segment.text,
                confidence=segment.confidence,
            )
        )
    await session.commit()
    return TranscriptUploadResult(
        segment_count=len(parsed),
        first_timestamp=parsed[0].start_seconds if parsed else None,
        last_timestamp=parsed[-1].end_seconds if parsed else None,
    )


@router.post("/episodes/{episode_id}/analyze", response_model=AnalysisRunRead)
async def analyze(
    episode_id: str,
    payload: AnalysisRequest,
    session: AsyncSession = Depends(get_session),
) -> AnalysisRunRead:
    try:
        run = await analyze_episode(session, episode_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    count = await _count(session, ClipCandidate, ClipCandidate.analysis_run_id == run.id)
    return AnalysisRunRead(
        id=run.id,
        episode_id=run.episode_id,
        status=run.status,
        mode=run.mode,
        summary=run.summary,
        generated_clip_count=count,
    )


@router.get("/episodes/{episode_id}/clips", response_model=list[ClipRead])
async def list_clips(
    episode_id: str,
    clip_type: str | None = None,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[ClipRead]:
    statement = (
        select(ClipCandidate)
        .where(ClipCandidate.episode_id == episode_id)
        .options(
            selectinload(ClipCandidate.score),
            selectinload(ClipCandidate.metadata_items),
            selectinload(ClipCandidate.rendered_clips),
        )
        .order_by(ClipCandidate.rank)
    )
    if clip_type:
        statement = statement.where(ClipCandidate.clip_type == clip_type)
    if status:
        statement = statement.where(ClipCandidate.status == status)
    result = await session.execute(statement)
    return [_clip_read(clip) for clip in result.scalars()]


@router.get("/clips/{clip_id}", response_model=ClipRead)
async def get_clip(clip_id: str, session: AsyncSession = Depends(get_session)) -> ClipRead:
    result = await session.execute(
        select(ClipCandidate)
        .where(ClipCandidate.id == clip_id)
        .options(
            selectinload(ClipCandidate.score),
            selectinload(ClipCandidate.metadata_items),
            selectinload(ClipCandidate.rendered_clips),
        )
    )
    clip = result.scalar_one_or_none()
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    return _clip_read(clip)


@router.patch("/clips/{clip_id}/status", response_model=ClipRead)
async def update_clip_status(
    clip_id: str,
    payload: ClipStatusUpdate,
    session: AsyncSession = Depends(get_session),
) -> ClipRead:
    clip = await session.get(ClipCandidate, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    clip.status = payload.status
    session.add(ApprovalEvent(clip_id=clip_id, **payload.model_dump()))
    await session.commit()
    return await get_clip(clip_id, session)


@router.post("/clips/{clip_id}/render", response_model=list[dict])
async def render(
    clip_id: str,
    payload: RenderRequest,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    try:
        rendered = await render_clip(session, clip_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [
        {
            "id": item.id,
            "render_type": item.render_type,
            "status": item.status,
            "filename": item.filename,
            "error": item.error,
        }
        for item in rendered
    ]


@router.post("/episodes/{episode_id}/exports", response_model=ExportPackRead)
async def export_episode(
    episode_id: str, session: AsyncSession = Depends(get_session)
) -> ExportPackRead:
    try:
        pack = await create_export_pack(session, episode_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ExportPackRead(
        id=pack.id,
        status=pack.status,
        filename=pack.filename,
        manifest=pack.manifest,
        error=pack.error,
    )


@router.get("/renders/{render_id}/download")
async def download_render(render_id: str, session: AsyncSession = Depends(get_session)) -> FileResponse:
    rendered = await session.get(RenderedClip, render_id)
    if rendered is None or not rendered.path or not Path(rendered.path).exists():
        raise HTTPException(status_code=404, detail="Rendered clip not found")
    return FileResponse(rendered.path, filename=rendered.filename)


@router.get("/exports/{export_id}/download")
async def download_export(export_id: str, session: AsyncSession = Depends(get_session)) -> FileResponse:
    pack = await session.get(ExportPack, export_id)
    if pack is None or not pack.path or not Path(pack.path).exists():
        raise HTTPException(status_code=404, detail="Export pack not found")
    return FileResponse(pack.path, filename=pack.filename)


async def _episode_read(session: AsyncSession, episode: Episode) -> EpisodeRead:
    return EpisodeRead(
        id=episode.id,
        title=episode.title,
        guest_name=episode.guest_name,
        guest_role=episode.guest_role,
        guest_company=episode.guest_company,
        recording_date=episode.recording_date,
        theme=episode.theme,
        status=episode.status,
        clip_count=await _count(session, ClipCandidate, ClipCandidate.episode_id == episode.id),
        asset_count=await _count(session, Asset, Asset.episode_id == episode.id),
        transcript_segment_count=await _count(
            session, TranscriptSegment, TranscriptSegment.episode_id == episode.id
        ),
    )


async def _count(session: AsyncSession, model, criterion) -> int:
    result = await session.execute(select(func.count()).select_from(model).where(criterion))
    return int(result.scalar_one())


def _asset_read(asset: Asset) -> AssetRead:
    return AssetRead(
        id=asset.id,
        asset_type=asset.asset_type,
        filename=asset.filename,
        content_type=asset.content_type,
        tags=asset.tags,
        is_primary=asset.is_primary,
        has_extracted_text=bool(asset.extracted_text),
    )


def _clip_read(clip: ClipCandidate) -> ClipRead:
    return ClipRead(
        id=clip.id,
        episode_id=clip.episode_id,
        clip_type=clip.clip_type,
        moment_type=clip.moment_type,
        status=clip.status,
        start_seconds=clip.start_seconds,
        end_seconds=clip.end_seconds,
        duration_seconds=clip.duration_seconds,
        excerpt=clip.excerpt,
        reasoning=clip.reasoning,
        rank=clip.rank,
        score=clip.score,
        metadata=clip.metadata_items,
        rendered_clips=clip.rendered_clips,
    )
