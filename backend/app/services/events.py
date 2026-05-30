from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from itertools import count
from typing import Any

from fastapi import Request
from loguru import logger


@dataclass(frozen=True)
class EpisodeEvent:
    id: int
    episode_id: str
    event_type: str
    message: str
    level: str = "info"
    progress: int | None = None
    data: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


_event_ids = count(1)
_subscribers: dict[str, set[asyncio.Queue[EpisodeEvent]]] = defaultdict(set)
_history: dict[str, deque[EpisodeEvent]] = defaultdict(lambda: deque(maxlen=80))


async def publish_episode_event(
    episode_id: str,
    event_type: str,
    message: str,
    *,
    level: str = "info",
    progress: int | None = None,
    data: dict[str, Any] | None = None,
) -> EpisodeEvent:
    event = EpisodeEvent(
        id=next(_event_ids),
        episode_id=episode_id,
        event_type=event_type,
        message=message,
        level=level,
        progress=_normalize_progress(progress),
        data=data or {},
    )
    _history[episode_id].append(event)
    stale: list[asyncio.Queue[EpisodeEvent]] = []
    for queue in list(_subscribers[episode_id]):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            stale.append(queue)
    for queue in stale:
        _subscribers[episode_id].discard(queue)
    logger.debug(
        "Published episode event episode_id={} event_type={} subscriber_count={}",
        episode_id,
        event_type,
        len(_subscribers[episode_id]),
    )
    return event


async def episode_event_stream(episode_id: str, request: Request) -> AsyncIterator[str]:
    queue: asyncio.Queue[EpisodeEvent] = asyncio.Queue(maxsize=100)
    _subscribers[episode_id].add(queue)
    logger.info("SSE client connected episode_id={} subscriber_count={}", episode_id, len(_subscribers[episode_id]))
    try:
        for event in list(_history[episode_id]):
            yield _format_event(event)
        yield _format_comment("connected")
        while not await request.is_disconnected():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield _format_comment("heartbeat")
            else:
                yield _format_event(event)
    finally:
        _subscribers[episode_id].discard(queue)
        logger.info(
            "SSE client disconnected episode_id={} subscriber_count={}",
            episode_id,
            len(_subscribers[episode_id]),
        )


def _format_event(event: EpisodeEvent) -> str:
    payload = json.dumps(asdict(event), ensure_ascii=True, default=str)
    return f"id: {event.id}\nevent: episode\ndata: {payload}\n\n"


def _format_comment(message: str) -> str:
    return f": {message}\n\n"


def _normalize_progress(progress: int | None) -> int | None:
    if progress is None:
        return None
    return max(0, min(100, int(progress)))
