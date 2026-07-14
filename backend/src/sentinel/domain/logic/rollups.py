"""Pure hourly-rollup logic (SPEC §3.5, §6, PLAN D7). Two I/O-free functions with
no clock — every timestamp comes from the results, so folding and aggregation are
deterministic and exhaustively unit-testable (PLAN D4).

`fold_results_into_rollup` recomputes a single hour bucket's aggregate from the raw
`CheckResult`s in it. Recomputing (rather than incrementing) makes it idempotent:
re-folding a bucket with the same raw rows yields an identical `CheckRollup`, so a
replayed check never double-counts, and the per-bucket stats match `compute_stats`
restricted to that hour exactly.

`aggregate_rollups` rolls the hourly buckets up into a long-window `Stats`:
check/failure counts and uptime are summed exactly, and the latency percentiles are
count-weighted across the per-bucket nearest-rank sketches (approximate across
heterogeneous buckets — the accepted rollup trade-off, SPEC §7 "within tolerance").
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sentinel.domain.entities import CheckResult, CheckRollup
from sentinel.domain.logic.stats import nearest_rank_percentile, uptime_pct
from sentinel.domain.value_objects import Stats, StatsWindow


def hour_bucket(at: datetime) -> datetime:
    """The UTC hour boundary `at` falls in — the `bucket_start` of its rollup."""
    return at.replace(minute=0, second=0, microsecond=0)


def fold_results_into_rollup(
    existing: CheckRollup | None, results: list[CheckResult]
) -> CheckRollup:
    """Recompute the rollup for one hour bucket from its raw `CheckResult`s.

    The bucket is `existing.bucket_start` when updating an existing rollup, else the
    hour of the first result. Only results in that bucket are counted, so a caller
    may pass a slightly wider fetch. Idempotent: folding the same rows again returns
    an equal rollup. Raises `ValueError` if the bucket can't be determined (no
    existing rollup and no results). `updated_at` is left `None` — the repository
    stamps it via the injected `Clock` (D10)."""
    if existing is not None:
        bucket = existing.bucket_start
        monitor_id = existing.monitor_id
    elif results:
        bucket = hour_bucket(results[0].finished_at)
        monitor_id = results[0].monitor_id
    else:
        raise ValueError("cannot fold a rollup without an existing bucket or any results")

    in_bucket = [r for r in results if hour_bucket(r.finished_at) == bucket]
    latencies = sorted(r.latency_ms for r in in_bucket if r.latency_ms is not None)
    return CheckRollup(
        monitor_id=monitor_id,
        bucket_start=bucket,
        checks=len(in_bucket),
        failures=sum(1 for r in in_bucket if not r.success),
        latency_p50_ms=nearest_rank_percentile(latencies, 50) or 0,
        latency_p95_ms=nearest_rank_percentile(latencies, 95) or 0,
        latency_p99_ms=nearest_rank_percentile(latencies, 99) or 0,
        latency_sum_ms=sum(latencies),
    )


def aggregate_rollups(rollups: list[CheckRollup], window: StatsWindow) -> Stats:
    """Roll hourly buckets up into a window `Stats` (SPEC §3.5). Counts and uptime
    are exact sums; latency percentiles are count-weighted over the buckets that
    recorded a latency (`None` when none did). The caller is responsible for passing
    only the buckets inside `window`."""
    checks = sum(r.checks for r in rollups)
    failures = sum(r.failures for r in rollups)
    timed = [r for r in rollups if r.latency_sum_ms > 0]
    return Stats(
        window=window.value,
        checks=checks,
        failures=failures,
        uptime_pct=uptime_pct(checks, failures),
        latency_p50_ms=_weighted_percentile(timed, lambda r: r.latency_p50_ms),
        latency_p95_ms=_weighted_percentile(timed, lambda r: r.latency_p95_ms),
        latency_p99_ms=_weighted_percentile(timed, lambda r: r.latency_p99_ms),
    )


def _weighted_percentile(
    rollups: list[CheckRollup], value: Callable[[CheckRollup], int]
) -> int | None:
    """Check-weighted mean of a per-bucket percentile across buckets, or `None` when
    no bucket recorded a latency."""
    if not rollups:
        return None
    total = sum(r.checks for r in rollups)
    if total == 0:
        return None
    return round(sum(value(r) * r.checks for r in rollups) / total)
