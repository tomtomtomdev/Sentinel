"""Retention use case (SPEC §6). One `prune()` deletes history past its window:
raw `CheckResult`s and the `state_transitions` flap history at `policy.raw_days`
(default 30), hourly rollups at `policy.rollup_days` (default ≈ 13 months) — so
long-range stats survive raw pruning. Naturally idempotent: `prune_before` is a
plain age cutoff, so a re-run at the same instant deletes nothing. Flow only —
the cutoffs are simple `Clock` arithmetic; scheduling (run once per interval)
belongs to the scheduler runner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sentinel.domain.errors import ValidationError
from sentinel.domain.ports import (
    CheckResultRepository,
    CheckRollupRepository,
    Clock,
    StateTransitionRepository,
)
from sentinel.domain.value_objects import RetentionPolicy


@dataclass(frozen=True)
class RetentionReport:
    """What one pruning pass deleted, for the worker log."""

    results_deleted: int
    transitions_deleted: int
    rollups_deleted: int


class RetentionService:
    def __init__(
        self,
        *,
        results: CheckResultRepository,
        transitions: StateTransitionRepository,
        rollups: CheckRollupRepository,
        clock: Clock,
        policy: RetentionPolicy | None = None,
    ) -> None:
        policy = policy or RetentionPolicy()
        # A zero/negative window would delete everything on the next run — refuse
        # at construction so a misconfigured worker fails at boot, loudly.
        if policy.raw_days < 1 or policy.rollup_days < 1:
            raise ValidationError("retention windows must be at least 1 day")
        self._results = results
        self._transitions = transitions
        self._rollups = rollups
        self._clock = clock
        self._policy = policy

    async def prune(self) -> RetentionReport:
        now = self._clock.now()
        raw_cutoff = now - timedelta(days=self._policy.raw_days)
        rollup_cutoff = now - timedelta(days=self._policy.rollup_days)
        return RetentionReport(
            results_deleted=await self._results.prune_before(raw_cutoff),
            transitions_deleted=await self._transitions.prune_before(raw_cutoff),
            rollups_deleted=await self._rollups.prune_before(rollup_cutoff),
        )
