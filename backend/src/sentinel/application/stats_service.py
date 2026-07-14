"""Read-model use cases for a monitor's history, stats, and dashboard summary
(SPEC §3.5). Orchestration only: it loads raw `CheckResult`s and the monitor's
`MonitorState` through ports and hands them to the pure `compute_stats` /
`aggregate_rollups` folds — no business rules live here. `now` comes from the
injected `Clock` (PLAN D4).

The 24h window is computed from raw `CheckResult`s; 7d/30d are aggregated from the
hourly `CheckRollup`s so a 30-day query never scans millions of raw rows (SPEC §6,
PLAN D7)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sentinel.domain.entities import CheckResult, Monitor
from sentinel.domain.errors import NotFoundError
from sentinel.domain.logic.rollups import aggregate_rollups, hour_bucket
from sentinel.domain.logic.stats import compute_stats, window_start
from sentinel.domain.ports import (
    CheckResultRepository,
    CheckRollupRepository,
    Clock,
    MonitorRepository,
    MonitorStateRepository,
)
from sentinel.domain.value_objects import MonitorStatus, Stats, StatsWindow


@dataclass(frozen=True)
class StatsView:
    """A window's `Stats` joined with the live `status`/`since` from the monitor's
    `MonitorState` — which `Stats` omits by design (PLAN D22). `status` is
    `unknown` and `since` is `None` before the monitor's first check."""

    stats: Stats
    status: MonitorStatus
    since: datetime | None


@dataclass(frozen=True)
class MonitorSummary:
    """Per-monitor dashboard rollup for `?include=summary` (SPEC §3.5): the current
    status plus a 24h window. `checks == 0` means "no data yet" — a caller must
    distinguish it from a genuine 0% uptime."""

    monitor_id: UUID
    status: MonitorStatus
    since: datetime | None
    last_check_at: datetime | None
    uptime_pct: float
    latency_p95_ms: int | None
    checks: int


class StatsService:
    def __init__(
        self,
        *,
        monitors: MonitorRepository,
        results: CheckResultRepository,
        states: MonitorStateRepository,
        rollups: CheckRollupRepository,
        clock: Clock,
    ) -> None:
        self._monitors = monitors
        self._results = results
        self._states = states
        self._rollups = rollups
        self._clock = clock

    async def history(
        self,
        monitor_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[CheckResult]:
        """Windowed, newest-first check history (SPEC §3.5). Raises `NotFoundError`
        for an unknown monitor so the API can return a 404."""
        await self._require_monitor(monitor_id)
        return await self._results.list_for_monitor(
            monitor_id, since=since, until=until, limit=limit
        )

    async def stats(self, monitor_id: UUID, window: StatsWindow) -> StatsView:
        """Uptime/latency over `window` plus live status/since (SPEC §3.5, §5). The
        24h window is computed from raw `CheckResult`s; 7d/30d are aggregated from
        the hourly `CheckRollup`s so a long window never scans millions of raw rows
        (SPEC §6, PLAN D7)."""
        await self._require_monitor(monitor_id)
        now = self._clock.now()
        if window is StatsWindow.H24:
            stats = compute_stats(await self._window_results(monitor_id, window, now), window, now)
        else:
            rollups = await self._rollups.list_for_window(
                monitor_id, since=hour_bucket(window_start(window, now)), until=now
            )
            stats = aggregate_rollups(rollups, window)
        state = await self._states.get(monitor_id)
        return StatsView(
            stats=stats,
            status=state.status if state else MonitorStatus.UNKNOWN,
            since=state.since if state else None,
        )

    async def summaries(self, monitors: list[Monitor]) -> dict[UUID, MonitorSummary]:
        """A 24h summary per monitor for the list view (SPEC §3.5). N+1 by design
        — one state load + one 24h stat per monitor — which is acceptable at v1
        scale; S7a's rollups make the long-window path cheap."""
        now = self._clock.now()
        summaries: dict[UUID, MonitorSummary] = {}
        for monitor in monitors:
            results = await self._window_results(monitor.id, StatsWindow.H24, now)
            stats = compute_stats(results, StatsWindow.H24, now)
            state = await self._states.get(monitor.id)
            summaries[monitor.id] = MonitorSummary(
                monitor_id=monitor.id,
                status=state.status if state else MonitorStatus.UNKNOWN,
                since=state.since if state else None,
                last_check_at=state.last_check_at if state else None,
                uptime_pct=stats.uptime_pct,
                latency_p95_ms=stats.latency_p95_ms,
                checks=stats.checks,
            )
        return summaries

    async def _window_results(
        self, monitor_id: UUID, window: StatsWindow, now: datetime
    ) -> list[CheckResult]:
        # Fetch the whole window unbounded (limit=None); compute_stats re-filters to
        # [now - window, now]. S7a's rollups will replace this raw scan for 7d/30d.
        return await self._results.list_for_monitor(
            monitor_id, since=window_start(window, now), until=now, limit=None
        )

    async def _require_monitor(self, monitor_id: UUID) -> None:
        if await self._monitors.get(monitor_id) is None:
            raise NotFoundError(f"monitor {monitor_id} not found")
