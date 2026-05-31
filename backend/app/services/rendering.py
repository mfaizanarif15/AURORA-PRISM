from __future__ import annotations

import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Asset, ClipCandidate, RenderedClip
from app.schemas.api import RenderRequest
from app.services.assets import safe_filename
from app.services.observability import observation, safe_update


class RenderPreconditionError(ValueError):
    """Raised when a clip cannot be rendered because required source media is missing."""


@dataclass(frozen=True)
class SourceAsset:
    asset: Asset
    path: Path


async def render_clip(session: AsyncSession, clip_id: str, request: RenderRequest) -> list[RenderedClip]:
    logger.info("Rendering clip started clip_id={} render_types={}", clip_id, request.render_types)
    with observation(
        "render_clip",
        as_type="span",
        input={"clip_id": clip_id, "render_types": request.render_types},
        metadata={"operation": "render"},
    ) as span:
        clip = await session.get(ClipCandidate, clip_id)
        if clip is None:
            logger.warning("Rendering failed, clip not found clip_id={}", clip_id)
            raise ValueError("Clip not found")

        render_types = _normalize_render_types(request.render_types)
        if not render_types:
            safe_update(span, output={"rendered": []})
            logger.info("Rendering skipped, no render output types selected clip_id={}", clip_id)
            return []

        video_asset = await _source_asset(session, clip.episode_id, ["video"])
        audio_asset = await _source_asset(session, clip.episode_id, ["audio", "video"])
        if video_asset is None and audio_asset is None:
            raise RenderPreconditionError(
                "Upload a video or audio asset before rendering clips. This episode has no usable media source."
            )
        ffmpeg = _ffmpeg_executable()
        if ffmpeg is None:
            raise RenderPreconditionError(
                "FFmpeg is not installed or not available in PATH. Install ffmpeg locally, "
                "or run the backend with Docker where ffmpeg is included."
            )
        outputs: list[RenderedClip] = []
        logger.debug(
            "Render assets resolved clip_id={} episode_id={} has_video={} has_audio_or_video={} normalized_render_types={}",
            clip_id,
            clip.episode_id,
            video_asset is not None,
            audio_asset is not None,
            render_types,
        )

        for render_type in render_types:
            record = RenderedClip(clip_id=clip.id, render_type=render_type, status="running")
            session.add(record)
            await session.flush()
            source = video_asset if render_type == "video" else audio_asset
            try:
                if source is None:
                    raise RuntimeError("No compatible media asset is available for this render type")
                output_path = _output_path(clip, render_type)
                command = _command_for(render_type, source.path, output_path, clip, ffmpeg)
                logger.info(
                    "Render started clip_id={} render_type={} asset_id={} source={} output={}",
                    clip.id,
                    render_type,
                    source.asset.id,
                    source.path,
                    output_path,
                )
                with observation(
                    "ffmpeg_render",
                    as_type="span",
                    input={"render_type": render_type, "duration_seconds": clip.duration_seconds},
                    metadata={"episode_id": clip.episode_id, "clip_id": clip.id},
                ) as render_span:
                    _run(command)
                    safe_update(render_span, output={"filename": output_path.name})
                record.status = "completed"
                record.path = str(output_path)
                record.filename = output_path.name
                logger.info(
                    "Render completed clip_id={} render_type={} output={}",
                    clip.id,
                    render_type,
                    output_path,
                )
            except Exception as exc:
                record.status = "failed"
                record.error = str(exc)
                logger.exception(
                    "Render failed clip_id={} render_type={} error={}",
                    clip.id,
                    render_type,
                    exc,
                )
            outputs.append(record)

        await session.commit()
        for record in outputs:
            await session.refresh(record)
        safe_update(
            span,
            output={
                "rendered": [
                    {"id": item.id, "type": item.render_type, "status": item.status}
                    for item in outputs
                ]
            },
        )
        logger.info(
            "Rendering clip finished clip_id={} statuses={}",
            clip_id,
            [{"id": item.id, "type": item.render_type, "status": item.status} for item in outputs],
        )
        return outputs


def _normalize_render_types(render_types: list[str]) -> list[str]:
    normalized: list[str] = []
    for render_type in render_types:
        if render_type not in normalized:
            normalized.append(render_type)
    return normalized


async def _source_asset(session: AsyncSession, episode_id: str, asset_types: list[str]) -> SourceAsset | None:
    result = await session.execute(
        select(Asset)
        .where(Asset.episode_id == episode_id, Asset.asset_type.in_(asset_types))
        .order_by(Asset.is_primary.desc(), Asset.created_at.desc())
    )
    assets = result.scalars().all()
    for asset in assets:
        resolved_path = _resolve_asset_path(asset)
        if resolved_path is not None:
            logger.debug(
                "Source asset lookup episode_id={} asset_types={} asset_id={} path={}",
                episode_id,
                asset_types,
                asset.id,
                resolved_path,
            )
            return SourceAsset(asset=asset, path=resolved_path)
        logger.warning(
            "Source asset file missing episode_id={} asset_id={} stored_path={}",
            episode_id,
            asset.id,
            asset.path,
        )
    logger.debug(
        "Source asset lookup episode_id={} asset_types={} found={}",
        episode_id,
        asset_types,
        False,
    )
    return None


def _resolve_asset_path(asset: Asset) -> Path | None:
    stored_path = Path(asset.path)
    if stored_path.exists():
        return stored_path

    settings = get_settings()
    candidates: list[Path] = []
    parts = stored_path.parts
    if "storage" in parts:
        storage_index = parts.index("storage")
        candidates.append(settings.storage_root.joinpath(*parts[storage_index + 1 :]))
    if not stored_path.is_absolute():
        candidates.append(settings.storage_root / stored_path)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _output_path(clip: ClipCandidate, render_type: str) -> Path:
    settings = get_settings()
    directory = settings.exports_dir / clip.episode_id / "clips"
    directory.mkdir(parents=True, exist_ok=True)
    stem = safe_filename(f"{clip.rank:02d}-{clip.target_platform}-{render_type}-{int(clip.start_seconds)}")
    suffix = ".m4a" if render_type == "audio" else ".mp4"
    output = directory / f"{stem}{suffix}"
    logger.debug("Render output path prepared clip_id={} render_type={} path={}", clip.id, render_type, output)
    return output


def _ffmpeg_executable() -> str | None:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    return _imageio_ffmpeg_executable()


def _imageio_ffmpeg_executable() -> str | None:
    try:
        import imageio_ffmpeg  # type: ignore[import-not-found]
    except ImportError:
        return None
    executable = imageio_ffmpeg.get_ffmpeg_exe()
    return executable if executable and Path(executable).exists() else None


def _command_for(
    render_type: str,
    source: Path,
    output: Path,
    clip: ClipCandidate,
    ffmpeg: str,
) -> list[str]:
    start = f"{clip.start_seconds:.3f}"
    duration = f"{clip.duration_seconds:.3f}"
    if render_type == "video":
        return [
            ffmpeg,
            "-y",
            "-ss",
            start,
            "-i",
            str(source),
            "-t",
            duration,
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output),
        ]
    if render_type == "audio":
        return [
            ffmpeg,
            "-y",
            "-ss",
            start,
            "-i",
            str(source),
            "-t",
            duration,
            "-vn",
            "-c:a",
            "aac",
            str(output),
        ]
    raise ValueError(f"Unsupported render type: {render_type}")


def _run(command: list[str]) -> None:
    logger.debug("Running render command command={}", command)
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError("FFmpeg is not installed or not available in PATH") from exc
    if completed.returncode != 0:
        logger.warning("Render command failed returncode={} stderr={}", completed.returncode, completed.stderr)
        raise RuntimeError(completed.stderr.strip() or "ffmpeg failed")
    logger.debug("Render command completed returncode={}", completed.returncode)
