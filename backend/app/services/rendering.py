from __future__ import annotations

import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Asset, ClipCandidate, RenderedClip
from app.schemas.api import RenderRequest
from app.services.assets import safe_filename
from app.services.observability import observation, safe_update


async def render_clip(session: AsyncSession, clip_id: str, request: RenderRequest) -> list[RenderedClip]:
    with observation(
        "render_clip",
        as_type="span",
        input={"clip_id": clip_id, "render_types": request.render_types},
        metadata={"operation": "render"},
    ) as span:
        clip = await session.get(ClipCandidate, clip_id)
        if clip is None:
            raise ValueError("Clip not found")

        video_asset = await _source_asset(session, clip.episode_id, ["video"])
        audio_asset = await _source_asset(session, clip.episode_id, ["audio", "video"])
        outputs: list[RenderedClip] = []
        render_types = _normalize_render_types(request.render_types, video_asset is not None)

        for render_type in render_types:
            record = RenderedClip(clip_id=clip.id, render_type=render_type, status="running")
            session.add(record)
            await session.flush()
            source = video_asset if render_type in {"original", "vertical"} else audio_asset
            try:
                if source is None:
                    raise RuntimeError("No compatible media asset is available for this render type")
                output_path = _output_path(clip, render_type)
                command = _command_for(render_type, Path(source.path), output_path, clip)
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
            except Exception as exc:
                record.status = "failed"
                record.error = str(exc)
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
        return outputs


def _normalize_render_types(render_types: list[str], has_video: bool) -> list[str]:
    normalized: list[str] = []
    for render_type in render_types:
        if render_type in {"original", "vertical"} and not has_video:
            replacement = "waveform" if render_type == "vertical" else "audio"
            if replacement not in normalized:
                normalized.append(replacement)
        elif render_type not in normalized:
            normalized.append(render_type)
    return normalized


async def _source_asset(session: AsyncSession, episode_id: str, asset_types: list[str]) -> Asset | None:
    result = await session.execute(
        select(Asset)
        .where(Asset.episode_id == episode_id, Asset.asset_type.in_(asset_types))
        .order_by(Asset.is_primary.desc(), Asset.created_at.desc())
    )
    return result.scalars().first()


def _output_path(clip: ClipCandidate, render_type: str) -> Path:
    settings = get_settings()
    directory = settings.exports_dir / clip.episode_id / "clips"
    directory.mkdir(parents=True, exist_ok=True)
    stem = safe_filename(f"{clip.rank:02d}-{clip.clip_type}-{render_type}-{int(clip.start_seconds)}")
    suffix = ".m4a" if render_type == "audio" else ".mp4"
    return directory / f"{stem}{suffix}"


def _command_for(render_type: str, source: Path, output: Path, clip: ClipCandidate) -> list[str]:
    start = f"{clip.start_seconds:.3f}"
    duration = f"{clip.duration_seconds:.3f}"
    if render_type == "original":
        return [
            "ffmpeg",
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
    if render_type == "vertical":
        return [
            "ffmpeg",
            "-y",
            "-ss",
            start,
            "-i",
            str(source),
            "-t",
            duration,
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
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
            "ffmpeg",
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
    if render_type == "waveform":
        return [
            "ffmpeg",
            "-y",
            "-ss",
            start,
            "-i",
            str(source),
            "-t",
            duration,
            "-filter_complex",
            "[0:a]showwaves=s=1080x520:mode=line:colors=0x6EE7B7[v];"
            "color=c=0x111827:s=1080x1920[bg];[bg][v]overlay=0:700",
            "-map",
            "0:a",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output),
        ]
    raise ValueError(f"Unsupported render type: {render_type}")


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "ffmpeg failed")
