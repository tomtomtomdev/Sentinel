"""The `run_forever` loop (SPEC §3.3): it seeds the schedule, cycles on a poll
interval, and shuts down promptly when its stop event is set. Driven with a tiny
poll interval and in-memory fakes so it exercises the real loop without real waits."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sentinel.application.check_service import CheckService
from sentinel.domain.entities import Monitor
from sentinel.domain.value_objects import ProbeResponse
from sentinel.infrastructure.scheduler import SchedulerRunner
from tests.support.fakes import (
    FakeHeartbeat,
    FakeHttpProbe,
    FixedClock,
    InMemoryCheckResultRepository,
    InMemoryMonitorRepository,
)

NOW = datetime(2026, 6, 27, 12, 0, tzinfo=UTC)


async def test_run_forever_cycles_then_stops_on_event() -> None:
    clock = FixedClock(NOW)
    monitors = InMemoryMonitorRepository(clock=clock)
    results = InMemoryCheckResultRepository()
    probe = FakeHttpProbe()
    heartbeat = FakeHeartbeat()
    await monitors.add(Monitor(name="m", url="https://api.example.com/health", interval_seconds=60))
    probe.queue(ProbeResponse(status_code=200, latency_ms=3))  # only the first cycle is due
    runner = SchedulerRunner(
        monitors=monitors,
        checks=CheckService(monitors=monitors, results=results, probe=probe, clock=clock),
        results=results,
        clock=clock,
        heartbeat=heartbeat,
        poll_seconds=0.01,
    )

    stop = asyncio.Event()
    task = asyncio.create_task(runner.run_forever(stop=stop))
    # Wait for at least one cycle to have run (the heartbeat beats every cycle).
    for _ in range(200):
        if heartbeat.pings >= 1:
            break
        await asyncio.sleep(0.005)
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)

    assert heartbeat.pings >= 1
    assert task.done()
    assert len(probe.requests) == 1  # the monitor was probed exactly once (clock frozen)
