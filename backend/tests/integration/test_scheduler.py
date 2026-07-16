"""One scheduler cycle, driven against in-memory fakes (SPEC §3.3, §6, §7). The
runner is a thin loop over the pure `select_due_monitors` decision: it probes due
enabled monitors via the real `CheckService` (reused), records their results,
advances its per-monitor schedule, and pings the heartbeat each cycle. No network,
no DB — a `FakeHttpProbe`, `FakeHeartbeat`, and `FixedClock` make it deterministic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sentinel.application.check_service import CheckService
from sentinel.application.retention_service import RetentionReport
from sentinel.domain.entities import CheckResult, Monitor
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


class Harness:
    def __init__(self) -> None:
        self.clock = FixedClock(NOW)
        self.monitors = InMemoryMonitorRepository(clock=self.clock)
        self.results = InMemoryCheckResultRepository()
        self.probe = FakeHttpProbe()
        self.heartbeat = FakeHeartbeat()
        self.checks = CheckService(
            monitors=self.monitors,
            results=self.results,
            probe=self.probe,
            clock=self.clock,
        )
        self.runner = SchedulerRunner(
            monitors=self.monitors,
            checks=self.checks,
            results=self.results,
            clock=self.clock,
            heartbeat=self.heartbeat,
            max_concurrency=10,
        )

    async def add_monitor(self, *, enabled: bool = True, name: str = "m") -> Monitor:
        return await self.monitors.add(
            Monitor(
                name=name,
                url="https://api.example.com/health",
                interval_seconds=60,
                timeout_seconds=5,
                enabled=enabled,
            )
        )

    def ok(self) -> None:
        self.probe.queue(ProbeResponse(status_code=200, latency_ms=4))


async def test_cycle_probes_due_monitors_and_records_results() -> None:
    h = Harness()
    a = await h.add_monitor(name="a")
    b = await h.add_monitor(name="b")
    h.ok()
    h.ok()

    probed = await h.runner.run_cycle()

    assert probed == 2
    assert len(await h.results.list_for_monitor(a.id)) == 1
    assert len(await h.results.list_for_monitor(b.id)) == 1
    assert len(h.probe.requests) == 2


async def test_disabled_monitor_is_not_probed() -> None:
    h = Harness()
    enabled = await h.add_monitor(name="on", enabled=True)
    disabled = await h.add_monitor(name="off", enabled=False)
    h.ok()

    probed = await h.runner.run_cycle()

    assert probed == 1
    assert len(await h.results.list_for_monitor(enabled.id)) == 1
    assert await h.results.list_for_monitor(disabled.id) == []


async def test_each_cycle_pings_the_heartbeat() -> None:
    h = Harness()
    await h.add_monitor()
    h.ok()

    await h.runner.run_cycle()

    assert h.heartbeat.pings == 1


async def test_heartbeat_fires_even_when_nothing_is_due() -> None:
    h = Harness()  # no monitors → nothing to probe, but the dead-man's switch must still beat

    probed = await h.runner.run_cycle()

    assert probed == 0
    assert h.heartbeat.pings == 1


async def test_just_probed_monitor_is_not_due_again_in_the_same_instant() -> None:
    h = Harness()
    await h.add_monitor()
    h.ok()

    first = await h.runner.run_cycle()
    second = await h.runner.run_cycle()  # clock unchanged → interval not elapsed

    assert first == 1
    assert second == 0


async def test_seed_resumes_from_persisted_results_and_skips_recent_checks() -> None:
    h = Harness()
    monitor = await h.add_monitor()
    # A check finished 10s ago is already persisted (a prior worker run).
    await h.results.add(
        CheckResult(
            monitor_id=monitor.id,
            started_at=NOW - timedelta(seconds=11),
            finished_at=NOW - timedelta(seconds=10),
            success=True,
        )
    )

    await h.runner.seed_schedule()
    probed = await h.runner.run_cycle()

    # Interval is 60s and only 10s have elapsed → not due, no re-probe burst on restart.
    assert probed == 0
    assert h.probe.requests == []


class FlakyChecks:
    """Wraps the real `CheckService`, raising for one monitor to simulate an
    unexpected failure mid-cycle (e.g. a monitor deleted between selection and
    probe -> `NotFoundError`)."""

    def __init__(self, inner: CheckService, fail_id: object) -> None:
        self._inner = inner
        self._fail_id = fail_id

    async def run_check(self, monitor_id: object) -> CheckResult:
        if monitor_id == self._fail_id:
            raise RuntimeError("simulated check failure")
        return await self._inner.run_check(monitor_id)  # type: ignore[arg-type]


async def test_one_failing_check_does_not_abort_the_cycle() -> None:
    h = Harness()
    survivor = await h.add_monitor(name="ok")
    boom = await h.add_monitor(name="boom")
    h.ok()  # only the surviving monitor reaches the probe
    h.runner = SchedulerRunner(
        monitors=h.monitors,
        checks=FlakyChecks(h.checks, boom.id),  # type: ignore[arg-type]
        results=h.results,
        clock=h.clock,
        heartbeat=h.heartbeat,
        max_concurrency=10,
    )

    probed = await h.runner.run_cycle()

    assert probed == 2  # both selected...
    assert len(await h.results.list_for_monitor(survivor.id)) == 1  # ...one still recorded
    assert await h.results.list_for_monitor(boom.id) == []  # the failure recorded nothing
    assert h.heartbeat.pings == 1  # cycle completed despite the failure


class CountingRetention:
    """A `RetentionService` stand-in that counts prune runs (optionally raising)."""

    def __init__(self, *, raises: bool = False) -> None:
        self.runs = 0
        self._raises = raises

    async def prune(self) -> RetentionReport:
        self.runs += 1
        if self._raises:
            raise RuntimeError("db unavailable")
        return RetentionReport(results_deleted=0, transitions_deleted=0, rollups_deleted=0)


def _runner_with_retention(h: Harness, retention: CountingRetention) -> SchedulerRunner:
    return SchedulerRunner(
        monitors=h.monitors,
        checks=h.checks,
        results=h.results,
        clock=h.clock,
        heartbeat=h.heartbeat,
        retention=retention,  # type: ignore[arg-type]
        retention_interval_seconds=3600,
    )


async def test_retention_prunes_on_the_first_cycle_then_waits_for_the_interval() -> None:
    """S10.2 (SPEC §6): pruning is scheduled — it runs at most once per interval,
    not every poll cycle, and the first cycle primes it."""
    h = Harness()
    retention = CountingRetention()
    runner = _runner_with_retention(h, retention)

    await runner.run_cycle()
    await runner.run_cycle()  # same instant — inside the interval
    assert retention.runs == 1

    h.clock.set(NOW + timedelta(seconds=3600))  # interval elapsed
    await runner.run_cycle()
    assert retention.runs == 2


async def test_retention_failure_does_not_abort_the_cycle() -> None:
    h = Harness()
    await h.add_monitor()
    h.ok()
    runner = _runner_with_retention(h, CountingRetention(raises=True))

    probed = await runner.run_cycle()

    assert probed == 1  # the cycle still probed…
    assert h.heartbeat.pings == 1  # …and completed


async def test_runner_without_retention_still_cycles() -> None:
    h = Harness()
    await h.add_monitor()
    h.ok()

    probed = await h.runner.run_cycle()

    assert probed == 1
    assert h.heartbeat.pings == 1
