"""`CheckService.run_check` folds each recorded `CheckResult` into its hour bucket's
`CheckRollup` (SPEC §3.5, §6, S7a). Exercised with in-memory repos + a scriptable
`FakeHttpProbe` (PLAN D13) — no DB, no network. Proves the bucket is recomputed from
raw (so counts stay correct across checks in the same hour), that separate hours get
separate rollups, and that the fold is a no-op when no rollup repository is wired."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sentinel.application.check_service import CheckService
from sentinel.domain.entities import Monitor
from sentinel.domain.errors import ProbeError
from sentinel.domain.logic.rollups import hour_bucket
from sentinel.domain.value_objects import ErrorKind, ProbeResponse
from tests.support.fakes import (
    FakeHttpProbe,
    FixedClock,
    InMemoryCheckResultRepository,
    InMemoryCheckRollupRepository,
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
        self.rollups = InMemoryCheckRollupRepository(clock=self.clock)
        self.probe = FakeHttpProbe()
        self.service = CheckService(
            monitors=self.monitors,
            results=self.results,
            probe=self.probe,
            clock=self.clock,
            states=self.states,
            rollups=self.rollups,
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


async def test_checks_in_the_same_hour_fold_into_one_rollup() -> None:
    h = Harness()
    monitor = await h.add_monitor()
    h.probe.queue(ProbeResponse(status_code=200, latency_ms=40))
    await h.service.run_check(monitor.id)
    h.clock.set(NOW + timedelta(minutes=5))
    h.probe.queue(ProbeResponse(status_code=200, latency_ms=60))
    await h.service.run_check(monitor.id)

    rollup = await h.rollups.get(monitor.id, hour_bucket(NOW))
    assert rollup is not None
    assert rollup.checks == 2  # recomputed from raw, not double-added
    assert rollup.failures == 0
    assert rollup.latency_sum_ms == 100
    assert rollup.latency_p50_ms == 40  # nearest-rank over [40, 60]
    assert rollup.updated_at == NOW + timedelta(minutes=5)  # stamped on the latest fold


async def test_checks_across_hours_produce_separate_rollups() -> None:
    h = Harness()
    monitor = await h.add_monitor()
    h.probe.queue(ProbeResponse(status_code=200, latency_ms=40))
    await h.service.run_check(monitor.id)
    h.clock.set(NOW + timedelta(hours=1, minutes=5))
    h.probe.queue(ProbeResponse(status_code=200, latency_ms=60))
    await h.service.run_check(monitor.id)

    first = await h.rollups.get(monitor.id, hour_bucket(NOW))
    second = await h.rollups.get(monitor.id, hour_bucket(NOW + timedelta(hours=1)))
    assert first is not None and first.checks == 1
    assert second is not None and second.checks == 1


async def test_failed_assertion_counts_as_a_failure_in_the_rollup() -> None:
    h = Harness()
    monitor = await h.add_monitor()
    h.probe.queue(ProbeResponse(status_code=500, latency_ms=25))  # fails the default 2xx

    await h.service.run_check(monitor.id)

    rollup = await h.rollups.get(monitor.id, hour_bucket(NOW))
    assert rollup is not None
    assert rollup.checks == 1
    assert rollup.failures == 1
    assert rollup.latency_sum_ms == 25  # assertion failures still record a latency


async def test_transport_failure_folds_with_no_latency() -> None:
    h = Harness()
    monitor = await h.add_monitor()
    h.probe.queue(ProbeError(ErrorKind.TIMEOUT, "read timed out"))

    await h.service.run_check(monitor.id)

    rollup = await h.rollups.get(monitor.id, hour_bucket(NOW))
    assert rollup is not None
    assert rollup.checks == 1
    assert rollup.failures == 1
    assert rollup.latency_sum_ms == 0
    assert rollup.latency_p50_ms == 0


async def test_no_rollup_repository_still_records_result() -> None:
    h = Harness()
    service = CheckService(
        monitors=h.monitors, results=h.results, probe=h.probe, clock=h.clock, states=h.states
    )
    monitor = await h.add_monitor()
    h.probe.queue(ProbeResponse(status_code=200, latency_ms=5))

    result = await service.run_check(monitor.id)

    assert result.success is True
    assert await h.rollups.get(monitor.id, hour_bucket(NOW)) is None
