from __future__ import annotations

import contextlib
import math
import wave
from pathlib import Path


def audio_confidence_for_range(path: Path | None, start_seconds: float, end_seconds: float) -> int:
    if path is None or not path.exists() or path.suffix.lower() != ".wav":
        return 64
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as wav:
            frame_rate = wav.getframerate()
            sample_width = wav.getsampwidth()
            channels = wav.getnchannels()
            start_frame = max(0, int(start_seconds * frame_rate))
            end_frame = max(start_frame + 1, int(end_seconds * frame_rate))
            wav.setpos(min(start_frame, wav.getnframes()))
            raw = wav.readframes(min(end_frame - start_frame, wav.getnframes() - start_frame))
            if not raw:
                return 55
            rms = _rms(raw, sample_width, channels)
            normalized = min(1.0, rms / 12000)
            confidence = 52 + int(normalized * 38)
            return max(45, min(92, confidence))
    except Exception:
        return 64


def _rms(raw: bytes, sample_width: int, channels: int) -> float:
    if sample_width != 2:
        return 8000.0
    total = 0
    count = 0
    step = sample_width * channels
    for index in range(0, len(raw) - step + 1, step):
        sample = int.from_bytes(raw[index : index + 2], "little", signed=True)
        total += sample * sample
        count += 1
    return math.sqrt(total / max(1, count))
