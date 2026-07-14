"""`CheckService.run_check` folds each `CheckResult` into the monitor's persisted
`MonitorState` (SPEC §3.8, S7.2). Exercised with the in-memory repos + a scriptable
`FakeHttpProbe` (PLAN D13) — no DB, no network. Proves the counters and
`last_check_at` advance every check while `status`/`since` flip only on a threshold
crossing, that the state is created on first check, and that a transport failure
advances the state as a failure."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sentinel.application.check_service import CheckService
from sentinel.domain.entities import Monitor
from sentinel.domain.errors import ProbeError
from sentinel.domain.value_objects import ErrorKind, MonitorStatus, ProbeResponse
from tests.support.fakes import (
    FakeHttpProbe,
    FixedClock,
    InMemoryCheckResultRepository,
    InMemoryMonitorRepository,
    InMemoryMonitorStateRepository,
)

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


class Harness:
    def __init__(self) -> None:
        self.clock = FixedClock(NOW)
        self.monitors = InMemoryMonitorRepository(clock=self.clock)
        self.results = InMemoryCheckResultRepository()
        self.states = InMemoryMonitorStateRepository()
        self.probe = FakeHttpProbe()
        self.service = CheckService(
            monitors=self.monitors,
            results=self.results,
            probe=self.probe,
            clock=self.clock,
            states=self.states,
        )

    async def add_monitor(self, **overrides: object) -> Monitor:
        params: dict[str, object] = {
            "name": "Prod health",
            "url": "https://api.example.com/health",
            "interval_seconds": 60,
            "timeout_seconds": 5,
        }
        params.update(overrides)
        return await self.monitors.add(Monitor(**params))  # type: ignore[arg-type]


async def test_sequence_of_checks_advances_and_persists_state() -> None:
    h = Harness()
    monitor = await h.add_monitor(failure_threshold=2, recovery_threshold=1)
    assert await h.states.get(monitor.id) is None  # no state until the first check

    # First failure (500 fails the default 2xx assertion): counter bumps, but
    # failure_threshold=2 isn't reached, so status stays unknown.
    h.probe.queue(ProbeResponse(status_code=500, latency_ms=5))
    await h.service.run_check(monitor.id)
    state = await h.states.get(monitor.id)
    assert state is not None
    assert state.status is MonitorStatus.UNKNOWN
    assert state.consecutive_failures == 1
    assert state.last_check_at == NOW

    # Second failure crosses the threshold → confirmed DOWN at t1.
    t1 = NOW + timedelta(seconds=60)
    h.clock.set(t1)
    h.probe.queue(ProbeResponse(status_code=500, latency_ms=5))
    await h.service.run_check(monitor.id)
    state = await h.states.get(monitor.id)
    assert state is not None
    assert state.status is MonitorStatus.DOWN
    assert state.consecutive_failures == 2
    assert state.since == t1
    assert state.last_check_at == t1

    # One success recovers (recovery_threshold=1) → confirmed UP at t2.
    t2 = t1 + timedelta(seconds=60)
    h.clock.set(t2)
    h.probe.queue(ProbeResponse(status_code=200, latency_ms=5))
    await h.service.run_check(monitor.id)
    state = await h.states.get(monitor.id)
    assert state is not None
    assert state.status is MonitorStatus.UP
    assert state.consecutive_successes == 1
    assert state.consecutive_failures == 0
    assert state.since == t2


async def test_transport_failure_advances_state_as_a_failure() -> None:
    h = Harness()
    monitor = await h.add_monitor(failure_threshold=1)
    h.probe.queue(ProbeError(ErrorKind.TIMEOUT, "read timed out"))

    await h.service.run_check(monitor.id)

    state = await h.states.get(monitor.id)
    assert state is not None
    assert state.status is MonitorStatus.DOWN
    assert state.consecutive_failures == 1
    assert state.last_check_at == NOW


async def test_state_not_tracked_when_repository_absent() -> None:
    # A CheckService built without a state repo still probes + records results
    # (the manual-check path and pre-S7.2 tests keep working).
    h = Harness()
    service = CheckService(monitors=h.monitors, results=h.results, probe=h.probe, clock=h.clock)
    monitor = await h.add_monitor()
    h.probe.queue(ProbeResponse(status_code=200, latency_ms=5))

    result = await service.run_check(monitor.id)

    assert result.success is True
    assert await h.states.get(monitor.id) is None
