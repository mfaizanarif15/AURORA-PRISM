from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services import audio_transcription as audio_transcription_module
from app.services.audio_transcription import (
    AudioTranscriptionUnavailable,
    _segments_from_transcription,
    is_transcribable_upload,
)
from app.services.transcripts import parse_transcript, timestamp_to_seconds


def test_timestamp_to_seconds_supports_minutes_and_hours() -> None:
    assert timestamp_to_seconds("04:06") == 246
    assert timestamp_to_seconds("01:02:03.500") == 3723.5


def test_parse_riverside_style_transcript() -> None:
    content = """Jocelyn Byrne Houle (00:02.053)
Hello and welcome.

Seth Dobrin (00:10.644)
AI systems need better representation and governance.
"""
    segments = parse_transcript(content, "txt")
    assert len(segments) == 2
    assert segments[0].speaker == "Jocelyn Byrne Houle"
    assert segments[1].start_seconds == 10.644
    assert "governance" in segments[1].text


def test_parse_vtt_cues() -> None:
    content = """WEBVTT

00:00:01.000 --> 00:00:04.000
Speaker: This is a strong hook.
"""
    segments = parse_transcript(content, "vtt")
    assert len(segments) == 1
    assert segments[0].speaker == "Speaker"
    assert segments[0].end_seconds == 4


def test_audio_upload_detection() -> None:
    assert is_transcribable_upload("episode-audio.mp3", None)
    assert is_transcribable_upload("episode.webm", "video/webm")
    assert not is_transcribable_upload("transcript.txt", "text/plain")


def test_verbose_audio_transcription_segments_are_normalized() -> None:
    response = SimpleNamespace(
        segments=[
            SimpleNamespace(start=1.23456, end=4.56789, text="The opening hook.", avg_logprob=-0.2),
            SimpleNamespace(start=4.6, end=8.0, text=""),
        ]
    )

    segments = _segments_from_transcription(response)

    assert len(segments) == 1
    assert segments[0].start_seconds == 1.235
    assert segments[0].end_seconds == 4.568
    assert segments[0].text == "The opening hook."
    assert segments[0].confidence == 0.8


def test_plain_audio_transcription_falls_back_to_untimed_text() -> None:
    response = SimpleNamespace(text="This is a plain audio transcript without timestamps.")

    segments = _segments_from_transcription(response)

    assert len(segments) == 1
    assert segments[0].confidence == 0.35
    assert "plain audio transcript" in segments[0].text


def test_audio_transcription_accepts_dict_payloads() -> None:
    response = {"segments": [{"start": 2, "end": 5, "text": "Dictionary segment."}]}

    segments = _segments_from_transcription(response)

    assert len(segments) == 1
    assert segments[0].start_seconds == 2
    assert segments[0].text == "Dictionary segment."


@pytest.mark.asyncio
async def test_audio_transcription_uses_openai_whisper_when_available(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "episode.mp3"
    path.write_bytes(b"fake audio")
    calls: list[dict] = []
    providers: list[str | None] = []

    class FakeTranscriptions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                segments=[
                    SimpleNamespace(
                        start=0,
                        end=2.5,
                        text="OpenAI Whisper transcript.",
                        avg_logprob=-0.1,
                    )
                ]
            )

    fake_client = SimpleNamespace(audio=SimpleNamespace(transcriptions=FakeTranscriptions()))

    def fake_make_chat_client(settings: Settings, provider: str | None = None):
        providers.append(provider)
        return fake_client

    monkeypatch.setattr(
        audio_transcription_module,
        "make_chat_client",
        fake_make_chat_client,
    )

    segments = await audio_transcription_module.transcribe_audio_file(
        path,
        "audio/mpeg",
        Settings(
            openai_api_key="test-key",
            openai_transcription_model="whisper-1",
            azure_openai_endpoint=None,
            azure_openai_api_key=None,
            azure_openai_transcription_deployment=None,
        ),
    )

    assert providers == ["openai"]
    assert calls[0]["model"] == "whisper-1"
    assert calls[0]["response_format"] == "verbose_json"
    assert calls[0]["timestamp_granularities"] == ["segment"]
    assert len(segments) == 1
    assert segments[0].text == "OpenAI Whisper transcript."


@pytest.mark.asyncio
async def test_audio_transcription_skips_when_no_transcriber_is_configured(tmp_path) -> None:
    path = tmp_path / "episode.mp3"
    path.write_bytes(b"fake audio")

    with pytest.raises(AudioTranscriptionUnavailable):
        await audio_transcription_module.transcribe_audio_file(
            path,
            "audio/mpeg",
            Settings(
                openai_api_key=None,
                azure_openai_endpoint=None,
                azure_openai_api_key=None,
                azure_openai_transcription_deployment=None,
            ),
        )
