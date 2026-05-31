from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_session
from app.models import (
    ApprovalEvent,
    Asset,
    ClipCandidate,
    ClipMetadata,
    ClipScore,
    Episode,
    EpisodeContext,
    ExportPack,
    RenderedClip,
    TranscriptSegment,
    User,
)
from app.models.entities import utcnow
from app.schemas.api import (
    AiProviderRead,
    AnalysisRequest,
    AnalysisRunRead,
    AssetRead,
    AuthLoginRequest,
    AuthProfileUpdate,
    AuthSessionRead,
    AuthSignupRequest,
    AuthUserRead,
    CLIP_STATUSES,
    ClipRead,
    ClipStatusUpdate,
    EpisodeAutoTitleRequest,
    EpisodeContextUpdate,
    EpisodeCreate,
    EpisodeRead,
    EpisodeUpdate,
    ExportPackRead,
    RenderRequest,
    TranscriptUploadResult,
)
from app.core.config import get_settings
from app.services.ai_clients import provider_status
from app.services.analysis import analyze_episode
from app.services.analysis_events import analysis_event_stream, publish_analysis_event
from app.services.audio_transcription import (
    AudioTranscriptionUnavailable,
    is_transcribable_upload,
    transcribe_audio_file,
)
from app.services.auth import (
    AuthUser,
    authenticate_credentials,
    configured_user,
    hash_password,
    issue_access_token,
    normalize_username,
    request_token,
    revoke_access_token,
    verify_password,
)
from app.services.assets import save_upload
from app.services.exports import create_export_pack
from app.services.llm import suggest_episode_title
from app.services.observability import langfuse_status
from app.services.rendering import RenderPreconditionError, render_clip
from app.services.transcripts import parse_transcript

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    logger.debug("Health check requested")
    return {"status": "ok"}


@router.post("/auth/login", response_model=AuthSessionRead)
async def login(
    payload: AuthLoginRequest, session: AsyncSession = Depends(get_session)
) -> AuthSessionRead:
    settings = get_settings()
    user_record = await _user_by_username(session, payload.username)
    if user_record is None:
        configured = authenticate_credentials(payload.username, payload.password, settings)
        if configured is not None and await _count(session, User) == 0:
            user_record = User(
                username=normalize_username(configured.username),
                display_name=configured.display_name,
                password_hash=hash_password(payload.password),
            )
            session.add(user_record)
            await session.commit()
            await session.refresh(user_record)
            logger.info("Bootstrapped configured admin user username={}", user_record.username)

    if (
        user_record is None
        or not user_record.is_active
        or not verify_password(payload.password, user_record.password_hash)
    ):
        logger.warning("Login failed username={}", payload.username)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    user_record.last_login_at = utcnow()
    await session.commit()
    user = _auth_user_from_record(user_record)
    token, expires_at = issue_access_token(user, settings)
    logger.info("Login succeeded username={}", user.username)
    return AuthSessionRead(
        access_token=token,
        expires_at=expires_at,
        user=_auth_user_read(user),
    )


@router.post("/auth/signup", response_model=AuthSessionRead, status_code=201)
async def signup(
    payload: AuthSignupRequest, session: AsyncSession = Depends(get_session)
) -> AuthSessionRead:
    username = normalize_username(payload.username)
    display_name = (payload.display_name or username).strip() or username
    if await _user_by_username(session, username) is not None:
        logger.warning("Signup rejected, username exists username={}", username)
        raise HTTPException(status_code=409, detail="Username already exists")

    user_record = User(
        username=username,
        display_name=display_name,
        password_hash=hash_password(payload.password),
        last_login_at=utcnow(),
    )
    session.add(user_record)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        logger.warning("Signup conflict username={}", username)
        raise HTTPException(status_code=409, detail="Username already exists") from exc
    await session.refresh(user_record)

    user = _auth_user_from_record(user_record)
    token, expires_at = issue_access_token(user, get_settings())
    logger.info("Signup succeeded username={}", user.username)
    return AuthSessionRead(
        access_token=token,
        expires_at=expires_at,
        user=_auth_user_read(user),
    )


@router.get("/auth/me", response_model=AuthUserRead)
async def current_user(
    request: Request, session: AsyncSession = Depends(get_session)
) -> AuthUserRead:
    user = getattr(request.state, "auth_user", None) or configured_user(get_settings())
    user_record = await _user_by_id(session, user.id)
    if user_record is not None:
        user = _auth_user_from_record(user_record)
    return _auth_user_read(user)


@router.patch("/auth/me", response_model=AuthSessionRead)
async def update_current_user(
    payload: AuthProfileUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AuthSessionRead:
    auth_user = getattr(request.state, "auth_user", None)
    if auth_user is None:
        raise HTTPException(status_code=401, detail="Missing authentication token")

    user_record = await _user_by_id(session, auth_user.id)
    if user_record is None or not user_record.is_active:
        logger.warning("Profile update rejected, user not found user_id={}", auth_user.id)
        raise HTTPException(status_code=404, detail="User not found")

    username = normalize_username(payload.username) if payload.username is not None else user_record.username
    display_name = (
        payload.display_name.strip()
        if payload.display_name is not None
        else user_record.display_name
    ) or username

    if username != user_record.username:
        existing = await _user_by_username(session, username)
        if existing is not None and existing.id != user_record.id:
            logger.warning("Profile update rejected, username exists username={}", username)
            raise HTTPException(status_code=409, detail="Username already exists")
        user_record.username = username

    user_record.display_name = display_name

    if payload.new_password is not None:
        if not payload.current_password:
            raise HTTPException(status_code=400, detail="Current password is required")
        if not verify_password(payload.current_password, user_record.password_hash):
            logger.warning("Password update rejected username={}", user_record.username)
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        user_record.password_hash = hash_password(payload.new_password)

    await session.commit()
    await session.refresh(user_record)
    user = _auth_user_from_record(user_record)
    settings = get_settings()
    token, expires_at = issue_access_token(user, settings)
    old_token = request_token(request)
    if old_token:
        revoke_access_token(old_token, settings)
    logger.info("Profile updated username={}", user.username)
    return AuthSessionRead(
        access_token=token,
        expires_at=expires_at,
        user=_auth_user_read(user),
    )


@router.post("/auth/logout")
async def logout(request: Request) -> dict[str, str]:
    user = getattr(request.state, "auth_user", None)
    token = request_token(request)
    if token:
        revoke_access_token(token, get_settings())
    logger.info("Logout requested username={}", user.username if user else "unknown")
    return {"status": "ok"}


@router.get("/ai/providers", response_model=AiProviderRead)
async def ai_providers() -> dict:
    status = provider_status(get_settings())
    logger.debug(
        "AI provider status requested default_provider={} azure_configured={} transcription_configured={} openai_configured={}",
        status["default_provider"],
        status["azure_openai_configured"],
        status["azure_openai_transcription_configured"],
        status["openai_configured"],
    )
    return status


@router.get("/observability/langfuse")
async def langfuse_observability() -> dict:
    status = langfuse_status(get_settings())
    logger.debug(
        "Langfuse observability status requested enabled={} configured={}",
        status["enabled"],
        status["configured"],
    )
    return status


@router.get("/episodes", response_model=list[EpisodeRead])
async def list_episodes(
    request: Request, session: AsyncSession = Depends(get_session)
) -> list[EpisodeRead]:
    owner_user_id = _current_owner_user_id(request)
    statement = select(Episode).order_by(Episode.created_at.desc())
    if owner_user_id is not None:
        statement = statement.where(Episode.owner_user_id == owner_user_id)
    result = await session.execute(statement)
    episodes = list(result.scalars())
    response = [await _episode_read(session, episode) for episode in episodes]
    logger.info("Listed episodes owner_user_id={} count={}", owner_user_id, len(response))
    return response


@router.post("/episodes", response_model=EpisodeRead)
async def create_episode(
    payload: EpisodeCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> EpisodeRead:
    owner_user_id = _current_owner_user_id(request)
    values = _clean_episode_values(payload.model_dump())
    episode = Episode(**values, status="draft", owner_user_id=owner_user_id)
    session.add(episode)
    await session.commit()
    await session.refresh(episode)
    logger.info(
        "Created episode episode_id={} owner_user_id={} title={}",
        episode.id,
        owner_user_id,
        episode.title,
    )
    return await _episode_read(session, episode)


@router.get("/episodes/{episode_id}", response_model=EpisodeRead)
async def get_episode(
    episode_id: str, request: Request, session: AsyncSession = Depends(get_session)
) -> EpisodeRead:
    episode = await _get_owned_episode(session, episode_id, _current_owner_user_id(request))
    if episode is None:
        logger.warning("Episode not found episode_id={}", episode_id)
        raise HTTPException(status_code=404, detail="Episode not found")
    logger.debug("Fetched episode episode_id={}", episode_id)
    return await _episode_read(session, episode)


@router.delete("/episodes/{episode_id}")
async def delete_episode(
    episode_id: str, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, str]:
    episode = await _get_owned_episode(session, episode_id, _current_owner_user_id(request))
    if episode is None:
        logger.warning("Cannot delete episode, episode not found episode_id={}", episode_id)
        raise HTTPException(status_code=404, detail="Episode not found")

    title = episode.title
    await session.delete(episode)
    await session.commit()
    logger.info("Deleted episode episode_id={} title={}", episode_id, title)
    return {"status": "deleted", "episode_id": episode_id}


@router.patch("/episodes/{episode_id}", response_model=EpisodeRead)
async def update_episode(
    episode_id: str,
    payload: EpisodeUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> EpisodeRead:
    episode = await _get_owned_episode(session, episode_id, _current_owner_user_id(request))
    if episode is None:
        logger.warning("Cannot update episode, episode not found episode_id={}", episode_id)
        raise HTTPException(status_code=404, detail="Episode not found")

    for key, value in _clean_episode_values(payload.model_dump(exclude_unset=True)).items():
        setattr(episode, key, value)
    await session.commit()
    await session.refresh(episode)
    logger.info("Episode updated episode_id={} title={}", episode.id, episode.title)
    return await _episode_read(session, episode)


@router.post("/episodes/{episode_id}/auto-title", response_model=EpisodeRead)
async def auto_title_episode(
    episode_id: str,
    payload: EpisodeAutoTitleRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> EpisodeRead:
    episode = await _get_owned_episode(session, episode_id, _current_owner_user_id(request))
    if episode is None:
        logger.warning("Cannot auto-title episode, episode not found episode_id={}", episode_id)
        raise HTTPException(status_code=404, detail="Episode not found")

    context = await _episode_context(session, episode_id)
    transcript_result = await session.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.episode_id == episode.id)
        .order_by(TranscriptSegment.start_seconds)
        .limit(8)
    )
    title = await suggest_episode_title(
        episode,
        context,
        transcript_result.scalars().all(),
        payload.ai_provider,
    )
    episode.title = title
    await session.commit()
    await session.refresh(episode)
    logger.info("Episode auto-title applied episode_id={} title={}", episode_id, title)
    return await _episode_read(session, episode)


@router.patch("/episodes/{episode_id}/context")
async def upsert_context(
    episode_id: str,
    payload: EpisodeContextUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    episode = await _get_owned_episode(session, episode_id, _current_owner_user_id(request))
    if episode is None:
        logger.warning("Cannot save context, episode not found episode_id={}", episode_id)
        raise HTTPException(status_code=404, detail="Episode not found")
    result = await session.execute(select(EpisodeContext).where(EpisodeContext.episode_id == episode_id))
    context = result.scalar_one_or_none()
    values = payload.model_dump()
    created = context is None
    if context is None:
        context = EpisodeContext(episode_id=episode_id, **values)
        session.add(context)
    else:
        for key, value in values.items():
            setattr(context, key, value)
    await session.commit()
    logger.info("Saved episode context episode_id={} created={}", episode_id, created)
    return {"status": "saved", "episode_id": episode_id}


@router.post("/episodes/{episode_id}/assets", response_model=AssetRead)
async def upload_asset(
    episode_id: str,
    request: Request,
    asset_type: str = Form(...),
    tags: str = Form(""),
    is_primary: bool = Form(False),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> AssetRead:
    if await _get_owned_episode(session, episode_id, _current_owner_user_id(request)) is None:
        logger.warning("Cannot upload asset, episode not found episode_id={}", episode_id)
        raise HTTPException(status_code=404, detail="Episode not found")
    asset_type = asset_type.strip().lower()
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
    logger.info(
        "Uploaded asset asset_id={} episode_id={} asset_type={} filename={} extracted_text={}",
        asset.id,
        episode_id,
        asset_type,
        asset.filename,
        bool(extracted_text),
    )
    return _asset_read(asset)


@router.post("/episodes/{episode_id}/transcript", response_model=TranscriptUploadResult)
async def upload_transcript(
    episode_id: str,
    request: Request,
    content: str | None = Form(None),
    source_format: str = Form("txt"),
    file: UploadFile | None = File(None),
    session: AsyncSession = Depends(get_session),
) -> TranscriptUploadResult:
    if await _get_owned_episode(session, episode_id, _current_owner_user_id(request)) is None:
        logger.warning("Cannot upload transcript, episode not found episode_id={}", episode_id)
        raise HTTPException(status_code=404, detail="Episode not found")
    if file is not None:
        file_suffix = Path(file.filename or "").suffix.lower()
        if is_transcribable_upload(file.filename, file.content_type):
            path, _ = await save_upload(episode_id, file, "audio")
            audio_asset = Asset(
                episode_id=episode_id,
                asset_type="audio",
                filename=file.filename or path.name,
                content_type=file.content_type,
                path=str(path),
                tags=["transcript_source"],
                is_primary=True,
            )
            session.add(audio_asset)
            try:
                parsed = await transcribe_audio_file(path, file.content_type)
            except AudioTranscriptionUnavailable as exc:
                logger.info("Audio transcription skipped episode_id={} reason={}", episode_id, exc)
                await session.commit()
                return TranscriptUploadResult(
                    segment_count=0,
                    first_timestamp=None,
                    last_timestamp=None,
                )
            except Exception as exc:
                logger.warning("Audio transcription failed episode_id={} error={}", episode_id, exc)
                await session.rollback()
                raise HTTPException(status_code=400, detail="Audio transcription failed") from exc
            if not parsed:
                await session.rollback()
                raise HTTPException(
                    status_code=400,
                    detail="Audio transcription produced no transcript text",
                )
            source_format = "audio"
            logger.info(
                "Audio transcript parsed episode_id={} filename={} segment_count={}",
                episode_id,
                file.filename,
                len(parsed),
            )
        elif file_suffix in {".pdf", ".docx"}:
            path, extracted_text = await save_upload(episode_id, file, "transcript_source")
            if not extracted_text:
                raise HTTPException(
                    status_code=400,
                    detail="Transcript document did not contain extractable text",
                )
            session.add(
                Asset(
                    episode_id=episode_id,
                    asset_type="transcript_source",
                    filename=file.filename or path.name,
                    content_type=file.content_type,
                    path=str(path),
                    extracted_text=extracted_text,
                    tags=["transcript_source"],
                    is_primary=False,
                )
            )
            source_format = file_suffix.lstrip(".") or source_format
            parsed = parse_transcript(extracted_text, source_format)
            logger.info(
                "Transcript document parsed episode_id={} filename={} segment_count={}",
                episode_id,
                file.filename,
                len(parsed),
            )
        else:
            raw = (await file.read()).decode("utf-8", errors="ignore")
            source_format = Path(file.filename or "transcript.txt").suffix.lstrip(".") or source_format
            logger.info(
                "Transcript file received episode_id={} filename={} source_format={}",
                episode_id,
                file.filename,
                source_format,
            )
            parsed = parse_transcript(raw, source_format)
    elif content:
        raw = content
        logger.info("Transcript content received episode_id={} source_format={}", episode_id, source_format)
        parsed = parse_transcript(raw, source_format)
    else:
        logger.warning("Transcript upload missing content episode_id={}", episode_id)
        raise HTTPException(status_code=400, detail="Provide transcript content or file")

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
    logger.info(
        "Transcript saved episode_id={} segment_count={} first_timestamp={} last_timestamp={}",
        episode_id,
        len(parsed),
        parsed[0].start_seconds if parsed else None,
        parsed[-1].end_seconds if parsed else None,
    )
    return TranscriptUploadResult(
        segment_count=len(parsed),
        first_timestamp=parsed[0].start_seconds if parsed else None,
        last_timestamp=parsed[-1].end_seconds if parsed else None,
    )


@router.post("/episodes/{episode_id}/analyze", response_model=AnalysisRunRead)
async def analyze(
    episode_id: str,
    payload: AnalysisRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AnalysisRunRead:
    if await _get_owned_episode(session, episode_id, _current_owner_user_id(request)) is None:
        logger.warning("Analysis rejected, episode not found episode_id={}", episode_id)
        raise HTTPException(status_code=404, detail="Episode not found")
    logger.info(
        "Analysis requested episode_id={} mode={} provider={} sections={}",
        episode_id,
        payload.mode,
        payload.ai_provider,
        {key: config.target_count for key, config in payload.enabled_sections()},
    )
    await publish_analysis_event(
        episode_id,
        "analysis.requested",
        "Analysis request received",
        progress=5,
        data={
            "mode": payload.mode,
            "provider": payload.ai_provider,
            "sections": {key: config.target_count for key, config in payload.enabled_sections()},
        },
    )
    try:
        run = await analyze_episode(session, episode_id, payload)
    except ValueError as exc:
        logger.warning("Analysis rejected episode_id={} error={}", episode_id, exc)
        await publish_analysis_event(
            episode_id,
            "analysis.failed",
            str(exc),
            level="error",
            progress=100,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    count = await _count(session, ClipCandidate, ClipCandidate.analysis_run_id == run.id)
    logger.info(
        "Analysis completed episode_id={} analysis_run_id={} generated_clip_count={}",
        episode_id,
        run.id,
        count,
    )
    await publish_analysis_event(
        episode_id,
        "analysis.completed",
        f"Analysis completed with {count} outputs",
        level="success",
        progress=100,
        data={"analysis_run_id": run.id, "generated_clip_count": count},
    )
    return AnalysisRunRead(
        id=run.id,
        episode_id=run.episode_id,
        status=run.status,
        mode=run.mode,
        summary=run.summary,
        generated_clip_count=count,
    )


@router.get("/episodes/{episode_id}/analysis-events")
async def stream_analysis_events(
    episode_id: str,
    request: Request,
    since: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    if await _get_owned_episode(session, episode_id, _current_owner_user_id(request)) is None:
        logger.warning("Analysis SSE stream rejected, episode not found episode_id={}", episode_id)
        raise HTTPException(status_code=404, detail="Episode not found")
    logger.info("Analysis SSE stream requested episode_id={}", episode_id)
    return StreamingResponse(
        analysis_event_stream(episode_id, request, since),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/episodes/{episode_id}/clips", response_model=list[ClipRead])
async def list_clips(
    episode_id: str,
    request: Request,
    clip_type: str | None = None,
    target_platform: str | None = None,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[ClipRead]:
    if await _get_owned_episode(session, episode_id, _current_owner_user_id(request)) is None:
        logger.warning("Cannot list clips, episode not found episode_id={}", episode_id)
        raise HTTPException(status_code=404, detail="Episode not found")
    statement = (
        select(ClipCandidate)
        .where(ClipCandidate.episode_id == episode_id)
        .options(
            selectinload(ClipCandidate.metadata_items),
            selectinload(ClipCandidate.rendered_clips),
        )
        .order_by(ClipCandidate.target_platform, ClipCandidate.rank)
    )
    if clip_type:
        statement = statement.where(ClipCandidate.clip_type == clip_type)
    if target_platform:
        statement = statement.where(ClipCandidate.target_platform == target_platform)
    if status:
        if status not in CLIP_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid clip status")
        statement = statement.where(ClipCandidate.status == status)
    result = await session.execute(statement)
    clips = [_clip_read(clip) for clip in result.scalars()]
    logger.info(
        "Listed clips episode_id={} clip_type={} target_platform={} status={} count={}",
        episode_id,
        clip_type,
        target_platform,
        status,
        len(clips),
    )
    return clips


@router.get("/clips/{clip_id}", response_model=ClipRead)
async def get_clip(
    clip_id: str, request: Request, session: AsyncSession = Depends(get_session)
) -> ClipRead:
    clip = await _get_owned_clip(
        session,
        clip_id,
        _current_owner_user_id(request),
        include_details=True,
    )
    if clip is None:
        logger.warning("Clip not found clip_id={}", clip_id)
        raise HTTPException(status_code=404, detail="Clip not found")
    logger.debug("Fetched clip clip_id={}", clip_id)
    return _clip_read(clip)


@router.patch("/clips/{clip_id}/status", response_model=ClipRead)
async def update_clip_status(
    clip_id: str,
    payload: ClipStatusUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ClipRead:
    owner_user_id = _current_owner_user_id(request)
    clip = await _get_owned_clip(session, clip_id, owner_user_id)
    if clip is None:
        logger.warning("Cannot update clip status, clip not found clip_id={}", clip_id)
        raise HTTPException(status_code=404, detail="Clip not found")
    clip.status = payload.status
    session.add(ApprovalEvent(clip_id=clip_id, **payload.model_dump()))
    await session.commit()
    logger.info(
        "Clip status updated clip_id={} status={} user_name={}",
        clip_id,
        payload.status,
        payload.user_name,
    )
    refreshed = await _get_owned_clip(session, clip_id, owner_user_id, include_details=True)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    return _clip_read(refreshed)


@router.delete("/clips/{clip_id}")
async def delete_clip(
    clip_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    owner_user_id = _current_owner_user_id(request)
    clip = await _get_owned_clip(session, clip_id, owner_user_id)
    if clip is None:
        logger.warning("Cannot delete clip, clip not found clip_id={}", clip_id)
        raise HTTPException(status_code=404, detail="Clip not found")

    episode_id = clip.episode_id
    await session.execute(delete(RenderedClip).where(RenderedClip.clip_id == clip_id))
    await session.execute(delete(ApprovalEvent).where(ApprovalEvent.clip_id == clip_id))
    await session.execute(delete(ClipMetadata).where(ClipMetadata.clip_id == clip_id))
    await session.execute(delete(ClipScore).where(ClipScore.clip_id == clip_id))
    await session.delete(clip)
    await session.commit()
    logger.info("Deleted clip clip_id={} episode_id={}", clip_id, episode_id)
    return {"status": "deleted", "clip_id": clip_id}


@router.post("/clips/{clip_id}/render", response_model=list[dict])
async def render(
    clip_id: str,
    payload: RenderRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    logger.info("Render requested clip_id={} render_types={}", clip_id, payload.render_types)
    if await _get_owned_clip(session, clip_id, _current_owner_user_id(request)) is None:
        logger.warning("Render rejected, clip not found clip_id={}", clip_id)
        raise HTTPException(status_code=404, detail="Clip not found")
    try:
        rendered = await render_clip(session, clip_id, payload)
    except RenderPreconditionError as exc:
        logger.warning("Render precondition failed clip_id={} error={}", clip_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        logger.warning("Render rejected clip_id={} error={}", clip_id, exc)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    logger.info(
        "Render request finished clip_id={} results={}",
        clip_id,
        [{"id": item.id, "type": item.render_type, "status": item.status} for item in rendered],
    )
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
    episode_id: str, request: Request, session: AsyncSession = Depends(get_session)
) -> ExportPackRead:
    logger.info("Export requested episode_id={}", episode_id)
    if await _get_owned_episode(session, episode_id, _current_owner_user_id(request)) is None:
        logger.warning("Export rejected, episode not found episode_id={}", episode_id)
        raise HTTPException(status_code=404, detail="Episode not found")
    try:
        pack = await create_export_pack(session, episode_id)
    except ValueError as exc:
        logger.warning("Export rejected episode_id={} error={}", episode_id, exc)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    logger.info(
        "Export request finished episode_id={} export_pack_id={} status={} filename={}",
        episode_id,
        pack.id,
        pack.status,
        pack.filename,
    )
    return ExportPackRead(
        id=pack.id,
        status=pack.status,
        filename=pack.filename,
        manifest=pack.manifest,
        error=pack.error,
    )


@router.get("/renders/{render_id}/download")
async def download_render(
    render_id: str, request: Request, session: AsyncSession = Depends(get_session)
) -> FileResponse:
    rendered = await _get_owned_render(session, render_id, _current_owner_user_id(request))
    if rendered is None or not rendered.path or not Path(rendered.path).exists():
        logger.warning("Rendered clip download not found render_id={}", render_id)
        raise HTTPException(status_code=404, detail="Rendered clip not found")
    logger.info("Rendered clip download render_id={} filename={}", render_id, rendered.filename)
    return FileResponse(rendered.path, filename=rendered.filename)


@router.get("/exports/{export_id}/download")
async def download_export(
    export_id: str, request: Request, session: AsyncSession = Depends(get_session)
) -> FileResponse:
    pack = await _get_owned_export(session, export_id, _current_owner_user_id(request))
    if pack is None or not pack.path or not Path(pack.path).exists():
        logger.warning("Export download not found export_id={}", export_id)
        raise HTTPException(status_code=404, detail="Export pack not found")
    logger.info("Export download export_id={} filename={}", export_id, pack.filename)
    return FileResponse(pack.path, filename=pack.filename)


def _current_owner_user_id(request: Request) -> str | None:
    user = getattr(request.state, "auth_user", None)
    if user is not None:
        return user.id
    if get_settings().auth_enabled:
        logger.warning("Authenticated route missing request.state.auth_user path={}", request.url.path)
        raise HTTPException(status_code=401, detail="Missing authentication token")
    return None


def _clean_episode_values(values: dict) -> dict:
    cleaned = {}
    for key, value in values.items():
        if isinstance(value, str):
            value = value.strip()
            if key == "title" and not value:
                value = "Untitled episode"
            elif key != "title" and not value:
                value = None
        cleaned[key] = value
    return cleaned


async def _get_owned_episode(
    session: AsyncSession, episode_id: str, owner_user_id: str | None
) -> Episode | None:
    if owner_user_id is None:
        return await session.get(Episode, episode_id)
    result = await session.execute(
        select(Episode).where(Episode.id == episode_id, Episode.owner_user_id == owner_user_id)
    )
    return result.scalar_one_or_none()


async def _get_owned_clip(
    session: AsyncSession,
    clip_id: str,
    owner_user_id: str | None,
    *,
    include_details: bool = False,
) -> ClipCandidate | None:
    statement = select(ClipCandidate).where(ClipCandidate.id == clip_id)
    if owner_user_id is not None:
        statement = statement.join(Episode, ClipCandidate.episode_id == Episode.id).where(
            Episode.owner_user_id == owner_user_id
        )
    if include_details:
        statement = statement.options(
            selectinload(ClipCandidate.metadata_items),
            selectinload(ClipCandidate.rendered_clips),
        )
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def _get_owned_render(
    session: AsyncSession, render_id: str, owner_user_id: str | None
) -> RenderedClip | None:
    statement = select(RenderedClip).where(RenderedClip.id == render_id)
    if owner_user_id is not None:
        statement = (
            statement.join(ClipCandidate, RenderedClip.clip_id == ClipCandidate.id)
            .join(Episode, ClipCandidate.episode_id == Episode.id)
            .where(Episode.owner_user_id == owner_user_id)
        )
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def _get_owned_export(
    session: AsyncSession, export_id: str, owner_user_id: str | None
) -> ExportPack | None:
    statement = select(ExportPack).where(ExportPack.id == export_id)
    if owner_user_id is not None:
        statement = statement.join(Episode, ExportPack.episode_id == Episode.id).where(
            Episode.owner_user_id == owner_user_id
        )
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def _episode_context(session: AsyncSession, episode_id: str) -> EpisodeContext | None:
    result = await session.execute(select(EpisodeContext).where(EpisodeContext.episode_id == episode_id))
    return result.scalar_one_or_none()


async def _episode_read(session: AsyncSession, episode: Episode) -> EpisodeRead:
    return EpisodeRead(
        id=episode.id,
        title=episode.title,
        guest_name=episode.guest_name,
        guest_role=episode.guest_role,
        guest_company=episode.guest_company,
        recording_date=episode.recording_date,
        status=episode.status,
        clip_count=await _count(session, ClipCandidate, ClipCandidate.episode_id == episode.id),
        asset_count=await _count(session, Asset, Asset.episode_id == episode.id),
        media_asset_count=await _count(
            session,
            Asset,
            Asset.episode_id == episode.id,
            Asset.asset_type.in_(["audio", "video"]),
        ),
        transcript_segment_count=await _count(
            session, TranscriptSegment, TranscriptSegment.episode_id == episode.id
        ),
    )


async def _count(session: AsyncSession, model, *criteria) -> int:
    result = await session.execute(select(func.count()).select_from(model).where(*criteria))
    count = int(result.scalar_one())
    logger.debug("Counted model={} count={}", getattr(model, "__name__", str(model)), count)
    return count


async def _user_by_username(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(select(User).where(User.username == normalize_username(username)))
    return result.scalar_one_or_none()


async def _user_by_id(session: AsyncSession, user_id: str) -> User | None:
    return await session.get(User, user_id)


def _auth_user_from_record(user: User) -> AuthUser:
    return AuthUser(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
    )


def _auth_user_read(user: AuthUser) -> AuthUserRead:
    return AuthUserRead(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
    )


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
        target_platform=clip.target_platform,
        purpose=clip.purpose,
        moment_type=clip.moment_type,
        status=clip.status,
        start_seconds=clip.start_seconds,
        end_seconds=clip.end_seconds,
        duration_seconds=clip.duration_seconds,
        excerpt=clip.excerpt,
        reasoning=clip.reasoning,
        rank=clip.rank,
        metadata=clip.metadata_items,
        rendered_clips=clip.rendered_clips,
    )
