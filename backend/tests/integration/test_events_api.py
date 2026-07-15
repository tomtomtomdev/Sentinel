"""Live events (SPEC §3.6, §7 "Live"). Two levels:

- `CheckService.run_check` publishes a `check_completed` for **every** recorded check
  and a `status_changed` **only** on a confirmed state transition (the point where
  the `StateTransition` from `advance_state` is finally consumed).
- `GET /api/v1/events` streams those events to a connected SSE client over
  `text/event-stream`, exercised end to end via `httpx.ASGITransport` — no DB, no
  network.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sentinel.application.check_service import CheckService
from sentinel.domain.entities import Monitor
from sentinel.domain.value_objects import (
    CheckCompleted,
    MonitorStatus,
    ProbeResponse,
    StateTransition,
)
from sentinel.infrastructure.events import InProcessEventBus
from sentinel.interface.api.events import stream_events
from sentinel.interface.main import create_app
from tests.support.fakes import (
    FakeEventBus,
    FakeHttpProbe,
    FixedClock,
    InMemoryCheckResultRepository,
    InMemoryMonitorRepository,
    InMemoryMonitorStateRepository,
)

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
STREAM_TIMEOUT = 3.0  # generous ceiling; the in-process stream resolves in ms


async def _add_monitor(monitors: InMemoryMonitorRepository, **overrides: object) -> Monitor:
    params: dict[str, object] = {
        "name": "Prod health",
        "url": "https://api.example.com/health",
        "interval_seconds": 60,
        "timeout_seconds": 5,
    }
    params.update(overrides)
    return await monitors.add(Monitor(**params))  # type: ignore[arg-type]


# --- CheckService publishes ---------------------------------------------------


@dataclass
class PublishHarness:
    service: CheckService
    monitors: InMemoryMonitorRepository
    probe: FakeHttpProbe
    bus: FakeEventBus
    clock: FixedClock


def _publish_harness(*, with_state: bool = True, with_bus: bool = True) -> PublishHarness:
    clock = FixedClock(NOW)
    monitors = InMemoryMonitorRepository(clock=clock)
    results = InMemoryCheckResultRepository()
    states = InMemoryMonitorStateRepository() if with_state else None
    bus = FakeEventBus()
    probe = FakeHttpProbe()
    service = CheckService(
        monitors=monitors,
        results=results,
        probe=probe,
        clock=clock,
        states=states,
        events=bus if with_bus else None,
    )
    return PublishHarness(service=service, monitors=monitors, probe=probe, bus=bus, clock=clock)


async def test_check_completed_published_on_every_check() -> None:
    h = _publish_harness()
    # failure_threshold=2 so a single failure does NOT cross the threshold — proves
    # check_completed fires independently of any transition.
    monitor = await _add_monitor(h.monitors, failure_threshold=2)
    h.probe.queue(ProbeResponse(status_code=500, latency_ms=5))

    await h.service.run_check(monitor.id)

    assert len(h.bus.published) == 1
    event = h.bus.published[0]
    assert isinstance(event, CheckCompleted)
    assert event.monitor_id == monitor.id
    assert event.success is False
    assert event.status_code == 500
    assert event.latency_ms == 5
    assert event.at == NOW


async def test_status_changed_published_only_on_confirmed_transition() -> None:
    h = _publish_harness()
    monitor = await _add_monitor(h.monitors, failure_threshold=2, recovery_threshold=1)

    # First failure: threshold not reached → check_completed only.
    h.probe.queue(ProbeResponse(status_code=500, latency_ms=5))
    await h.service.run_check(monitor.id)
    assert [type(e) for e in h.bus.published] == [CheckCompleted]

    # Second failure crosses failure_threshold → confirmed DOWN.
    t1 = NOW + timedelta(seconds=60)
    h.clock.set(t1)
    h.probe.queue(ProbeResponse(status_code=500, latency_ms=5))
    await h.service.run_check(monitor.id)
    assert [type(e) for e in h.bus.published] == [CheckCompleted, CheckCompleted, StateTransition]
    transition = h.bus.published[-1]
    assert isinstance(transition, StateTransition)
    assert transition.monitor_id == monitor.id
    assert transition.from_status is MonitorStatus.UNKNOWN
    assert transition.to_status is MonitorStatus.DOWN
    assert transition.at == t1

    # One success recovers → confirmed UP.
    t2 = t1 + timedelta(seconds=60)
    h.clock.set(t2)
    h.probe.queue(ProbeResponse(status_code=200, latency_ms=5))
    await h.service.run_check(monitor.id)
    recovery = h.bus.published[-1]
    assert isinstance(recovery, StateTransition)
    assert recovery.from_status is MonitorStatus.DOWN
    assert recovery.to_status is MonitorStatus.UP
    assert recovery.at == t2


async def test_check_completed_published_without_a_state_repo() -> None:
    # No state repo → no transition can be derived, but check_completed still fires.
    h = _publish_harness(with_state=False)
    monitor = await _add_monitor(h.monitors)
    h.probe.queue(ProbeResponse(status_code=200, latency_ms=5))

    await h.service.run_check(monitor.id)

    assert [type(e) for e in h.bus.published] == [CheckCompleted]


async def test_run_check_works_without_an_event_bus() -> None:
    h = _publish_harness(with_bus=False)
    monitor = await _add_monitor(h.monitors)
    h.probe.queue(ProbeResponse(status_code=200, latency_ms=5))

    result = await h.service.run_check(monitor.id)

    assert result.success is True
    assert h.bus.published == []  # the bus we built was never wired in


# --- GET /api/v1/events (end to end) ------------------------------------------
#
# httpx's ASGITransport buffers a response until it completes, so it hangs on an
# infinite SSE stream. Instead we drive the endpoint's `StreamingResponse`
# body_iterator directly — that iterator is exactly the byte stream a connected
# client receives — so the assertion is still "a connected client observes the
# event" (SPEC §7 "Live"), just without a socket. The HTTP framing on top is
# Starlette's, covered by `test_events_route_is_registered`.


@dataclass
class ApiHarness:
    service: CheckService
    monitors: InMemoryMonitorRepository
    probe: FakeHttpProbe
    bus: InProcessEventBus
    clock: FixedClock


def _api_harness() -> ApiHarness:
    clock = FixedClock(NOW)
    monitors = InMemoryMonitorRepository(clock=clock)
    results = InMemoryCheckResultRepository()
    states = InMemoryMonitorStateRepository()
    bus = InProcessEventBus()
    probe = FakeHttpProbe()
    service = CheckService(
        monitors=monitors,
        results=results,
        probe=probe,
        clock=clock,
        states=states,
        events=bus,
    )
    return ApiHarness(service=service, monitors=monitors, probe=probe, bus=bus, clock=clock)


def _parse_frame(chunk: str) -> dict:
    """Parse one SSE frame (`event:` + `data:` + blank line) into `{name, data}`."""
    event: dict = {}
    for line in chunk.strip("\n").splitlines():
        field, _, value = line.partition(":")
        if field == "event":
            event["name"] = value.strip()
        elif field == "data":
            event["data"] = json.loads(value.strip())
    return event


async def _collect(
    harness: ApiHarness,
    trigger: Callable[[], Awaitable[object]],
    *,
    count: int,
) -> list[dict]:
    """Open the SSE stream via the endpoint, wait until it has subscribed, fire
    `trigger`, then read `count` frames from the client-facing body iterator."""
    response = await stream_events(harness.bus)
    assert response.media_type == "text/event-stream"

    frames: asyncio.Queue[str] = asyncio.Queue()

    async def consume() -> None:
        async for chunk in response.body_iterator:
            text = chunk.decode() if isinstance(chunk, bytes | bytearray) else str(chunk)
            await frames.put(text)

    task = asyncio.create_task(consume())
    try:
        async with asyncio.timeout(STREAM_TIMEOUT):
            # poll: the subscription registers inside the endpoint's generator task,
            # whose side effect on the shared counter is what we're waiting for
            while harness.bus.subscriber_count == 0:  # noqa: ASYNC110
                await asyncio.sleep(0.01)
        await trigger()
        async with asyncio.timeout(STREAM_TIMEOUT):
            return [_parse_frame(await frames.get()) for _ in range(count)]
    finally:
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
        with contextlib.suppress(BaseException):
            await response.body_iterator.aclose()  # type: ignore[attr-defined]


def test_events_route_is_registered() -> None:
    assert "/api/v1/events" in create_app().openapi()["paths"]


async def test_connected_client_receives_check_completed() -> None:
    h = _api_harness()
    # failure_threshold=2 so a single 500 emits exactly one event (no transition).
    monitor = await _add_monitor(h.monitors, failure_threshold=2)
    h.probe.queue(ProbeResponse(status_code=500, latency_ms=5))

    events = await _collect(h, lambda: h.service.run_check(monitor.id), count=1)

    assert events[0]["name"] == "check_completed"
    assert events[0]["data"]["monitor_id"] == str(monitor.id)
    assert events[0]["data"]["success"] is False
    assert events[0]["data"]["status_code"] == 500


async def test_connected_client_receives_status_changed_on_transition() -> None:
    h = _api_harness()
    # failure_threshold=1 → one failure confirms DOWN, so the client sees both a
    # check_completed and a status_changed.
    monitor = await _add_monitor(h.monitors, failure_threshold=1)
    h.probe.queue(ProbeResponse(status_code=500, latency_ms=5))

    events = await _collect(h, lambda: h.service.run_check(monitor.id), count=2)

    assert [e["name"] for e in events] == ["check_completed", "status_changed"]
    changed = events[1]["data"]
    assert changed == {
        "monitor_id": str(monitor.id),
        "from": "unknown",
        "to": "down",
        "at": NOW.isoformat().replace("+00:00", "Z"),
    }
