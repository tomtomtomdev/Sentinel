"""Pure uptime/latency stats over a window of raw `CheckResult`s (SPEC §3.5, §7).
`now` is injected and results outside `[now - window, now]` are ignored, so the
computation is deterministic and I/O-free (PLAN D4).

In S7 every window (incl. 7d/30d) is computed here from raw rows; S7a will serve
the long windows from hourly rollups instead so a 30-day query never scans
millions of rows (SPEC §6, PLAN D7).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from sentinel.domain.entities import CheckResult
from sentinel.domain.value_objects import Stats, StatsWindow

_WINDOW_DURATIONS: dict[StatsWindow, timedelta] = {
    StatsWindow.H24: timedelta(hours=24),
    StatsWindow.D7: timedelta(days=7),
    StatsWindow.D30: timedelta(days=30),
}


def window_start(window: StatsWindow, now: datetime) -> datetime:
    """The inclusive lower bound of `window` ending at `now`. Shared so a caller
    can fetch exactly the window's raw results before folding them here."""
    return now - _WINDOW_DURATIONS[window]


def compute_stats(results: list[CheckResult], window: StatsWindow, now: datetime) -> Stats:
    """Uptime %, check/failure counts, and p50/p95/p99 latency over `window`
    ending at `now`.

    A result is in-window when `now - window <= finished_at <= now` (cutoff
    inclusive). Percentiles are computed only over results that recorded a latency
    (transport failures have none) and are `None` when there are none. With no
    in-window results, `uptime_pct` is `0.0` — callers treat `checks == 0` as
    "no data" (there is no meaningful uptime without checks).
    """
    cutoff = window_start(window, now)
    in_window = [r for r in results if cutoff <= r.finished_at <= now]

    checks = len(in_window)
    failures = sum(1 for r in in_window if not r.success)
    uptime_pct = round((checks - failures) / checks * 100, 2) if checks else 0.0

    latencies = sorted(r.latency_ms for r in in_window if r.latency_ms is not None)
    return Stats(
        window=window.value,
        checks=checks,
        failures=failures,
        uptime_pct=uptime_pct,
        latency_p50_ms=_percentile(latencies, 50),
        latency_p95_ms=_percentile(latencies, 95),
        latency_p99_ms=_percentile(latencies, 99),
    )


def _percentile(values_sorted: list[int], pct: float) -> int | None:
    """Nearest-rank percentile of an ascending list, or `None` if empty. Returns
    an actual observed value (no interpolation), so results stay integer ms."""
    if not values_sorted:
        return None
    rank = math.ceil(pct / 100 * len(values_sorted))
    index = min(max(rank, 1), len(values_sorted)) - 1
    return values_sorted[index]
