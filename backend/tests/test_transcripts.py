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
