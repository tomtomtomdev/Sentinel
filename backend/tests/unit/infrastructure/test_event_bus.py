"""`InProcessEventBus` — the in-memory fan-out behind the SSE endpoint (SPEC §3.6).
Asyncio-only, no DB/network. Proves: an event reaches every current subscriber;
subscribers deregister when their context exits; publishing with no subscribers (or
to a full, un-drained queue) never blocks or raises; a slow subscriber's queue drops
its oldest events so the pipeline stays current."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from sentinel.domain.value_objects import CheckCompleted
from sentinel.infrastructure.events import InProcessEventBus

AT = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def _event(latency_ms: int) -> CheckCompleted:
    """A distinguishable event — `latency_ms` doubles as an ordering marker."""
    return CheckCompleted(monitor_id=uuid4(), at=AT, success=True, latency_ms=latency_ms)


async def _next(events: object) -> CheckCompleted:
    async with asyncio.timeout(1.0):
        return await anext(events)  # type: ignore[arg-type]


async def test_published_event_reaches_a_subscriber() -> None:
    bus = InProcessEventBus()
    event = _event(1)

    async with bus.subscribe() as events:
        await bus.publish(event)
        assert await _next(events) == event


async def test_event_fans_out_to_every_subscriber() -> None:
    bus = InProcessEventBus()
    event = _event(1)

    async with bus.subscribe() as a, bus.subscribe() as b:
        assert bus.subscriber_count == 2
        await bus.publish(event)
        assert await _next(a) == event
        assert await _next(b) == event


async def test_subscriber_deregisters_on_context_exit() -> None:
    bus = InProcessEventBus()
    async with bus.subscribe():
        assert bus.subscriber_count == 1
    assert bus.subscriber_count == 0


async def test_publish_with_no_subscribers_is_a_noop() -> None:
    bus = InProcessEventBus()
    await bus.publish(_event(1))  # must not raise


async def test_full_queue_drops_oldest_and_never_blocks() -> None:
    bus = InProcessEventBus(max_queue=2)

    async with bus.subscribe() as events:
        # Publish more than the queue holds without ever draining it — publish must
        # stay non-blocking, and the subscriber keeps the two newest events in order.
        for i in range(5):
            await asyncio.wait_for(bus.publish(_event(i)), 1.0)
        first = await _next(events)
        second = await _next(events)
        assert [first.latency_ms, second.latency_ms] == [3, 4]
