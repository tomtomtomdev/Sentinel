"""In-memory `EventBus` adapter for SSE live updates (SPEC §3.6).

Each subscriber gets its own bounded `asyncio.Queue`; `publish` offers the event to
every queue without ever blocking or raising — a slow or disconnected SSE client
must not stall the check pipeline. When a subscriber's queue is full its **oldest**
event is dropped so the client stays current (a live dashboard wants the latest
state, not a stale backlog). Delivery is process-local: this bus fans out only to
subscribers in the same process, so the API's manual-check pipeline reaches its own
`GET /events` clients. Cross-process delivery (the scheduler worker → API clients)
needs a Redis-backed adapter behind the same `EventBus` port — see PROGRESS.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sentinel.domain.value_objects import Event

DEFAULT_MAX_QUEUE = 100


class InProcessEventBus:
    def __init__(self, *, max_queue: int = DEFAULT_MAX_QUEUE) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._max_queue = max_queue

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def publish(self, event: Event) -> None:
        for queue in list(self._subscribers):
            _offer(queue, event)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[AsyncIterator[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.add(queue)
        try:
            yield _drain(queue)
        finally:
            self._subscribers.discard(queue)


async def _drain(queue: asyncio.Queue[Event]) -> AsyncIterator[Event]:
    while True:
        yield await queue.get()


def _offer(queue: asyncio.Queue[Event], event: Event) -> None:
    """Enqueue without blocking; on a full queue drop the oldest event first so the
    subscriber keeps the newest ones. The suppressed races (a concurrent drain
    emptied, or a concurrent publish refilled, the queue) just mean this event is
    skipped — never a block or a raise."""
    if queue.full():
        with contextlib.suppress(asyncio.QueueEmpty):
            queue.get_nowait()
    with contextlib.suppress(asyncio.QueueFull):
        queue.put_nowait(event)
