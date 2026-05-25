from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass


SPEAKER_TS_RE = re.compile(
    r"^(?P<speaker>.*?)\s*\((?P<ts>\d{1,2}:\d{2}(?::\d{2})?(?:[\.,]\d{1,3})?)\)\s*$"
)
INLINE_TS_RE = re.compile(
    r"^(?P<ts>\d{1,2}:\d{2}(?::\d{2})?(?:[\.,]\d{1,3})?)\s*[-–—:]\s*(?P<text>.+)$"
)
RANGE_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?(?:[\.,]\d{1,3})?)\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?(?:[\.,]\d{1,3})?)"
)


@dataclass(frozen=True)
class ParsedSegment:
    speaker: str | None
    start_seconds: float
    end_seconds: float
    text: str
    confidence: float | None = None


def timestamp_to_seconds(raw: str) -> float:
    clean = raw.strip().replace(",", ".")
    parts = clean.split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    raise ValueError(f"Unsupported timestamp: {raw}")


def seconds_to_timestamp(seconds: float) -> str:
    seconds = max(0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
    return f"{minutes:02d}:{secs:06.3f}"


def parse_transcript(content: str, source_format: str = "txt") -> list[ParsedSegment]:
    source_format = source_format.lower().strip(".")
    if source_format == "csv":
        segments = _parse_csv(content)
    elif "-->" in content or source_format in {"vtt", "srt"}:
        segments = _parse_timed_cues(content)
    else:
        segments = _parse_riverside_txt(content)

    if not segments:
        segments = _parse_untimed_text(content)
    return _finalize_end_times(segments)


def _parse_csv(content: str) -> list[ParsedSegment]:
    reader = csv.DictReader(io.StringIO(content))
    segments: list[ParsedSegment] = []
    for row in reader:
        start_raw = row.get("start") or row.get("start_time") or row.get("timestamp")
        text = row.get("text") or row.get("transcript") or row.get("content")
        if not start_raw or not text:
            continue
        end_raw = row.get("end") or row.get("end_time")
        start = timestamp_to_seconds(start_raw)
        end = timestamp_to_seconds(end_raw) if end_raw else start + _estimate_duration(text)
        segments.append(
            ParsedSegment(
                speaker=row.get("speaker") or row.get("name"),
                start_seconds=start,
                end_seconds=end,
                text=_clean_text(text),
            )
        )
    return segments


def _parse_timed_cues(content: str) -> list[ParsedSegment]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", normalized)
    segments: list[ParsedSegment] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        range_line_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if range_line_index is None:
            continue
        match = RANGE_RE.search(lines[range_line_index])
        if not match:
            continue
        body = " ".join(lines[range_line_index + 1 :])
        speaker, text = _split_speaker_text(body)
        segments.append(
            ParsedSegment(
                speaker=speaker,
                start_seconds=timestamp_to_seconds(match.group("start")),
                end_seconds=timestamp_to_seconds(match.group("end")),
                text=_clean_text(text),
            )
        )
    return [segment for segment in segments if segment.text]


def _parse_riverside_txt(content: str) -> list[ParsedSegment]:
    lines = content.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    segments: list[ParsedSegment] = []
    speaker: str | None = None
    start: float | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer, speaker, start
        if start is None:
            buffer = []
            return
        text = _clean_text(" ".join(buffer))
        if text:
            segments.append(
                ParsedSegment(
                    speaker=speaker,
                    start_seconds=start,
                    end_seconds=start + _estimate_duration(text),
                    text=text,
                )
            )
        buffer = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        speaker_match = SPEAKER_TS_RE.match(stripped)
        inline_match = INLINE_TS_RE.match(stripped)
        if speaker_match:
            flush()
            speaker = _clean_text(speaker_match.group("speaker")) or None
            start = timestamp_to_seconds(speaker_match.group("ts"))
        elif inline_match:
            flush()
            speaker = None
            start = timestamp_to_seconds(inline_match.group("ts"))
            buffer = [inline_match.group("text")]
        else:
            buffer.append(stripped)
    flush()
    return segments


def _parse_untimed_text(content: str) -> list[ParsedSegment]:
    words = content.split()
    segments: list[ParsedSegment] = []
    cursor = 0.0
    for index in range(0, len(words), 90):
        text = " ".join(words[index : index + 90])
        duration = _estimate_duration(text)
        segments.append(
            ParsedSegment(
                speaker=None,
                start_seconds=cursor,
                end_seconds=cursor + duration,
                text=text,
                confidence=0.35,
            )
        )
        cursor += duration
    return segments


def _finalize_end_times(segments: list[ParsedSegment]) -> list[ParsedSegment]:
    ordered = sorted(segments, key=lambda item: item.start_seconds)
    finalized: list[ParsedSegment] = []
    for index, segment in enumerate(ordered):
        next_start = ordered[index + 1].start_seconds if index + 1 < len(ordered) else None
        if next_start is not None and next_start > segment.start_seconds:
            end = min(max(segment.end_seconds, segment.start_seconds + 1), next_start - 0.05)
        else:
            end = max(segment.end_seconds, segment.start_seconds + 1)
        finalized.append(
            ParsedSegment(
                speaker=segment.speaker,
                start_seconds=round(segment.start_seconds, 3),
                end_seconds=round(end, 3),
                text=segment.text,
                confidence=segment.confidence,
            )
        )
    return finalized


def _estimate_duration(text: str) -> float:
    words = max(1, len(text.split()))
    return max(3.0, words / 2.6)


def _split_speaker_text(body: str) -> tuple[str | None, str]:
    if ":" in body:
        speaker, text = body.split(":", 1)
        if 1 <= len(speaker.split()) <= 6:
            return _clean_text(speaker), text
    return None, body


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
