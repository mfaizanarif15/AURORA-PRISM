import json
from uuid import uuid4

from app.services.events import episode_event_stream, publish_episode_event


class NeverDisconnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


async def test_episode_event_stream_includes_clamped_progress() -> None:
    episode_id = f"episode-{uuid4()}"
    event = await publish_episode_event(
        episode_id,
        "analysis.started",
        "Analysis started",
        progress=142,
    )

    stream = episode_event_stream(episode_id, NeverDisconnectedRequest())
    chunk = await anext(stream)
    await stream.aclose()
    payload = json.loads(
        next(line.removeprefix("data: ") for line in chunk.splitlines() if line.startswith("data: "))
    )

    assert event.progress == 100
    assert payload["progress"] == 100
