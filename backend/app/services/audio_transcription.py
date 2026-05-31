from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from app.core.config import Settings, get_settings
from app.services.ai_clients import make_chat_client
from app.services.transcripts import ParsedSegment, parse_transcript


class AudioTranscriptionUnavailable(RuntimeError):
    """Raised when audio transcription is intentionally skipped due to missing config."""


TRANSCRIBABLE_SUFFIXES = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"}
TRANSCRIBABLE_CONTENT_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/mpga",
    "audio/m4a",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
    "video/mp4",
    "video/webm",
}


def is_transcribable_upload(filename: str | None, content_type: str | None) -> bool:
    suffix = Path(filename or "").suffix.lower()
    normalized_content_type = (content_type or "").split(";")[0].strip().lower()
    return (
        suffix in TRANSCRIBABLE_SUFFIXES
        or normalized_content_type.startswith("audio/")
        or normalized_content_type in TRANSCRIBABLE_CONTENT_TYPES
    )


async def transcribe_audio_file(
    path: Path, content_type: str | None = None, settings: Settings | None = None
) -> list[ParsedSegment]:
    settings = settings or get_settings()
    client: Any
    model: str
    provider: str
    if (settings.openai_api_key or "").strip():
        client = make_chat_client(settings, "openai")
        model = settings.openai_transcription_model
        provider = "openai"
    elif (
        settings.resolved_azure_openai_endpoint
        and settings.resolved_azure_openai_api_key
        and settings.resolved_azure_openai_transcription_deployment
    ):
        client = make_chat_client(settings, "azure_openai")
        model = settings.resolved_azure_openai_transcription_deployment
        provider = "azure_openai"
    else:
        raise AudioTranscriptionUnavailable(
            "OPENAI_API_KEY is not configured; skipping audio transcription"
        )

    logger.info(
        "Transcribing audio file path={} content_type={} provider={} model={}",
        path,
        content_type,
        provider,
        model,
    )
    try:
        response = await _request_verbose_transcription(client, path, model)
    except Exception as exc:
        logger.warning(
            "Verbose transcription failed path={} error={}; retrying without segment timestamps",
            path,
            exc,
        )
        response = await _request_plain_transcription(client, path, model)

    segments = _segments_from_transcription(response)
    logger.info("Audio transcription parsed path={} segment_count={}", path, len(segments))
    return segments


async def _request_verbose_transcription(client: Any, path: Path, model: str) -> Any:
    with path.open("rb") as audio_file:
        return await client.audio.transcriptions.create(
            model=model,
            file=audio_file,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )


async def _request_plain_transcription(client: Any, path: Path, model: str) -> Any:
    with path.open("rb") as audio_file:
        return await client.audio.transcriptions.create(
            model=model,
            file=audio_file,
            response_format="json",
        )


def _segments_from_transcription(response: Any) -> list[ParsedSegment]:
    raw_segments = _response_value(response, "segments")
    if raw_segments:
        segments = [_segment_from_response(item) for item in raw_segments]
        return [segment for segment in segments if segment is not None]

    text = str(_response_value(response, "text") or "").strip()
    if not text:
        return []
    return parse_transcript(text, "txt")


def _segment_from_response(item: Any) -> ParsedSegment | None:
    text = str(_response_value(item, "text") or "").strip()
    if not text:
        return None
    start = float(_response_value(item, "start") or 0)
    end = float(_response_value(item, "end") or start + 1)
    return ParsedSegment(
        speaker=None,
        start_seconds=round(max(0, start), 3),
        end_seconds=round(max(start + 1, end), 3),
        text=text,
        confidence=_segment_confidence(item),
    )


def _segment_confidence(item: Any) -> float | None:
    avg_logprob = _response_value(item, "avg_logprob")
    if avg_logprob is None:
        return None
    try:
        return max(0.0, min(1.0, 1.0 + float(avg_logprob)))
    except (TypeError, ValueError):
        return None


def _response_value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)
