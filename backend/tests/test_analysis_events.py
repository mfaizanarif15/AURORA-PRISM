from __future__ import annotations

import json

from app.services.analysis_events import analysis_event_stream, publish_analysis_event


class NeverDisconnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


async def test_analysis_event_stream_includes_clamped_progress() -> None:
    episode_id = "analysis-event-episode"
    event = await publish_analysis_event(
        episode_id,
        "analysis.section_specialists",
        "Running section specialists",
        progress=142,
    )

    stream = analysis_event_stream(episode_id, NeverDisconnectedRequest())
    raw = await stream.__anext__()
    await stream.aclose()
    payload = json.loads(raw.split("data: ", 1)[1])

    assert event.progress == 100
    assert payload["event_type"] == "analysis.section_specialists"
    assert payload["message"] == "Running section specialists"
    assert payload["progress"] == 100
