"""`RetentionService.prune` (SPEC §6 retention, S10.2): raw `CheckResult`s and
`state_transitions` are pruned at the raw cutoff (default 30 days), hourly
`check_rollups` at the far longer rollup cutoff (default 13 months ≈ 396 days) —
so long-range history survives raw pruning. Idempotent: a second run at the same
instant deletes nothing. Pure orchestration over the repos + injected `Clock`;
driven with the in-memory fakes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sentinel.application.retention_service import RetentionService
from sentinel.domain.entities import CheckResult, CheckRollup
from sentinel.domain.errors import ValidationError
from sentinel.domain.value_objects import MonitorStatus, RetentionPolicy, StateTransition
from tests.support.fakes import (
    FixedClock,
    InMemoryCheckResultRepository,
    InMemoryCheckRollupRepository,
    InMemoryStateTransitionRepository,
)

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
MONITOR_ID = uuid4()


class Harness:
    def __init__(self, policy: RetentionPolicy | None = None) -> None:
        self.clock = FixedClock(NOW)
        self.results = InMemoryCheckResultRepository()
        self.transitions = InMemoryStateTransitionRepository()
        self.rollups = InMemoryCheckRollupRepository(clock=self.clock)
        self.service = RetentionService(
            results=self.results,
            transitions=self.transitions,
            rollups=self.rollups,
            clock=self.clock,
            policy=policy or RetentionPolicy(),
        )

    async def add_result(self, *, age: timedelta) -> None:
        finished = NOW - age
        await self.results.add(
            CheckResult(
                monitor_id=MONITOR_ID,
                started_at=finished - timedelta(seconds=1),
                finished_at=finished,
                success=True,
                status_code=200,
                latency_ms=5,
            )
        )

    async def add_transition(self, *, age: timedelta) -> None:
        await self.transitions.add(
            StateTransition(
                monitor_id=MONITOR_ID,
                from_status=MonitorStatus.UP,
                to_status=MonitorStatus.DOWN,
                at=NOW - age,
            )
        )

    async def add_rollup(self, *, age: timedelta) -> None:
        await self.rollups.save(
            CheckRollup(monitor_id=MONITOR_ID, bucket_start=NOW - age, checks=1)
        )


async def test_prunes_each_store_at_its_own_cutoff_and_reports_counts() -> None:
    h = Harness()
    # Raw + transitions: 30-day cutoff — 31d pruned, 29d kept.
    await h.add_result(age=timedelta(days=31))
    await h.add_result(age=timedelta(days=29))
    await h.add_transition(age=timedelta(days=31))
    await h.add_transition(age=timedelta(days=29))
    # Rollups: 396-day cutoff — 31d-old survives raw pruning, 400d pruned.
    await h.add_rollup(age=timedelta(days=400))
    await h.add_rollup(age=timedelta(days=31))

    report = await h.service.prune()

    assert report.results_deleted == 1
    assert report.transitions_deleted == 1
    assert report.rollups_deleted == 1
    assert len(await h.results.list_for_monitor(MONITOR_ID, limit=None)) == 1
    assert len(await h.transitions.list_since(MONITOR_ID, since=NOW - timedelta(days=999))) == 1
    kept_rollups = await h.rollups.list_for_window(
        MONITOR_ID, since=NOW - timedelta(days=999), until=NOW
    )
    assert [r.bucket_start for r in kept_rollups] == [NOW - timedelta(days=31)]


async def test_second_run_at_the_same_instant_deletes_nothing() -> None:
    h = Harness()
    await h.add_result(age=timedelta(days=31))
    await h.add_rollup(age=timedelta(days=400))
    await h.service.prune()

    report = await h.service.prune()

    assert report.results_deleted == 0
    assert report.transitions_deleted == 0
    assert report.rollups_deleted == 0


async def test_custom_policy_windows_are_honoured() -> None:
    h = Harness(policy=RetentionPolicy(raw_days=7, rollup_days=30))
    await h.add_result(age=timedelta(days=8))
    await h.add_result(age=timedelta(days=6))
    await h.add_rollup(age=timedelta(days=31))
    await h.add_rollup(age=timedelta(days=8))

    report = await h.service.prune()

    assert report.results_deleted == 1
    assert report.rollups_deleted == 1


@pytest.mark.parametrize("kwargs", [{"raw_days": 0}, {"rollup_days": 0}, {"raw_days": -3}])
def test_a_non_positive_retention_window_is_rejected(kwargs: dict[str, int]) -> None:
    """A zero/negative window would silently delete everything on the next run, so
    the service refuses to be built with one (fails the worker at boot, loudly)."""
    with pytest.raises(ValidationError):
        Harness(policy=RetentionPolicy(**kwargs))
