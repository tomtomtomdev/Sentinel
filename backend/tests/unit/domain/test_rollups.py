"""S7a — pure hourly-rollup logic (SPEC §3.5, §6, §7 "Rollups", PLAN D7).

`fold_results_into_rollup` recomputes a single hour bucket's aggregate from the
raw `CheckResult`s in it, so re-folding a bucket never double-counts (idempotent)
and per-bucket stats match `compute_stats` exactly. `aggregate_rollups` rolls the
hourly buckets up into a long-window `Stats`: counts/uptime are summed exactly and
the latency percentiles are count-weighted across the per-bucket sketches.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sentinel.domain.entities import CheckResult, CheckRollup
from sentinel.domain.logic.rollups import (
    aggregate_rollups,
    fold_results_into_rollup,
    hour_bucket,
)
from sentinel.domain.logic.stats import compute_stats
from sentinel.domain.value_objects import StatsWindow

MID = uuid4()
NOW = datetime(2026, 7, 14, 12, 30, tzinfo=UTC)
BUCKET = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def _result(*, success: bool, latency_ms: int | None, at: datetime) -> CheckResult:
    return CheckResult(
        monitor_id=MID,
        started_at=at,
        finished_at=at,
        success=success,
        status_code=200 if success else None,
        latency_ms=latency_ms,
    )


def _rollup(**overrides: object) -> CheckRollup:
    params: dict[str, object] = {
        "monitor_id": MID,
        "bucket_start": BUCKET,
        "checks": 10,
        "failures": 0,
        "latency_p50_ms": 500,
        "latency_p95_ms": 1000,
        "latency_p99_ms": 1000,
        "latency_sum_ms": 5500,
    }
    params.update(overrides)
    return CheckRollup(**params)  # type: ignore[arg-type]


# --- hour_bucket -------------------------------------------------------------


def test_hour_bucket_truncates_to_the_hour_keeping_tz() -> None:
    dt = datetime(2026, 7, 14, 12, 37, 45, 123456, tzinfo=UTC)
    assert hour_bucket(dt) == datetime(2026, 7, 14, 12, 0, 0, 0, tzinfo=UTC)


# --- fold_results_into_rollup ------------------------------------------------


def test_fold_computes_counts_sum_and_nearest_rank_percentiles() -> None:
    results = [
        _result(success=True, latency_ms=(i + 1) * 100, at=BUCKET + timedelta(minutes=i))
        for i in range(10)  # latencies 100,200,...,1000 in the 12:00 bucket
    ]
    rollup = fold_results_into_rollup(None, results)

    assert rollup.monitor_id == MID
    assert rollup.bucket_start == BUCKET
    assert rollup.checks == 10
    assert rollup.failures == 0
    assert rollup.latency_sum_ms == 5500
    # nearest-rank over [100..1000]: p50=500, p95=p99=1000 (matches compute_stats)
    assert rollup.latency_p50_ms == 500
    assert rollup.latency_p95_ms == 1000
    assert rollup.latency_p99_ms == 1000
    assert rollup.updated_at is None  # stamped only at persistence (Clock, D10)


def test_fold_counts_failures_and_excludes_transport_failures_from_latency() -> None:
    results = [
        _result(success=True, latency_ms=100, at=BUCKET + timedelta(minutes=1)),
        _result(success=True, latency_ms=200, at=BUCKET + timedelta(minutes=2)),
        _result(success=False, latency_ms=None, at=BUCKET + timedelta(minutes=3)),  # transport
        _result(success=False, latency_ms=300, at=BUCKET + timedelta(minutes=4)),  # assertion
    ]
    rollup = fold_results_into_rollup(None, results)

    assert rollup.checks == 4
    assert rollup.failures == 2
    assert rollup.latency_sum_ms == 600  # 100 + 200 + 300, the latency-less one excluded
    assert rollup.latency_p50_ms == 200  # nearest-rank over [100, 200, 300]


def test_fold_is_idempotent_per_bucket() -> None:
    results = [
        _result(success=True, latency_ms=(i + 1) * 100, at=BUCKET + timedelta(minutes=i))
        for i in range(5)
    ]
    once = fold_results_into_rollup(None, results)
    twice = fold_results_into_rollup(once, results)  # re-folding the same bucket

    assert twice == once  # no double-counting


def test_fold_only_includes_results_in_the_existing_bucket() -> None:
    existing = _rollup(checks=0, latency_sum_ms=0)  # bucket_start = 12:00
    mixed = [
        _result(success=True, latency_ms=100, at=BUCKET + timedelta(minutes=10)),
        _result(success=True, latency_ms=200, at=BUCKET + timedelta(minutes=50)),
        _result(success=True, latency_ms=300, at=BUCKET + timedelta(hours=1, minutes=5)),  # 13:xx
    ]
    rollup = fold_results_into_rollup(existing, mixed)

    assert rollup.bucket_start == BUCKET
    assert rollup.checks == 2  # the 13:05 result belongs to the next bucket


def test_fold_without_existing_takes_bucket_from_the_first_result() -> None:
    results = [
        _result(success=True, latency_ms=100, at=BUCKET + timedelta(minutes=10)),
        _result(success=True, latency_ms=300, at=BUCKET + timedelta(hours=1, minutes=5)),  # 13:xx
    ]
    rollup = fold_results_into_rollup(None, results)

    assert rollup.bucket_start == BUCKET
    assert rollup.checks == 1


def test_fold_transport_only_bucket_has_zero_latency_fields() -> None:
    results = [_result(success=False, latency_ms=None, at=BUCKET + timedelta(minutes=1))]
    rollup = fold_results_into_rollup(None, results)

    assert rollup.checks == 1
    assert rollup.failures == 1
    assert rollup.latency_sum_ms == 0
    assert rollup.latency_p50_ms == 0
    assert rollup.latency_p95_ms == 0
    assert rollup.latency_p99_ms == 0


def test_fold_no_existing_and_no_results_raises() -> None:
    with pytest.raises(ValueError):
        fold_results_into_rollup(None, [])


# --- fold parity with compute_stats (per bucket) -----------------------------


def test_fold_bucket_matches_compute_stats_over_the_same_results() -> None:
    results = [
        _result(success=(i % 4 != 0), latency_ms=None if i % 4 == 0 else (i + 1) * 50, at=at)
        for i, at in enumerate(BUCKET + timedelta(minutes=m) for m in range(12))
    ]
    rollup = fold_results_into_rollup(None, results)
    raw = compute_stats(results, StatsWindow.H24, BUCKET + timedelta(minutes=30))

    assert rollup.checks == raw.checks
    assert rollup.failures == raw.failures
    assert rollup.latency_p50_ms == raw.latency_p50_ms
    assert rollup.latency_p95_ms == raw.latency_p95_ms
    assert rollup.latency_p99_ms == raw.latency_p99_ms


# --- aggregate_rollups -------------------------------------------------------


def test_aggregate_sums_counts_and_computes_uptime() -> None:
    rollups = [
        _rollup(bucket_start=BUCKET, checks=10, failures=1),
        _rollup(bucket_start=BUCKET + timedelta(hours=1), checks=10, failures=0),
        _rollup(bucket_start=BUCKET + timedelta(hours=2), checks=5, failures=4),
    ]
    stats = aggregate_rollups(rollups, StatsWindow.D30)

    assert stats.window == "30d"
    assert stats.checks == 25
    assert stats.failures == 5
    assert stats.uptime_pct == 80.0  # (25 - 5) / 25 * 100


def test_aggregate_empty_yields_no_data() -> None:
    stats = aggregate_rollups([], StatsWindow.D7)

    assert stats.checks == 0
    assert stats.failures == 0
    assert stats.uptime_pct == 0.0
    assert stats.latency_p50_ms is None
    assert stats.latency_p95_ms is None
    assert stats.latency_p99_ms is None


def test_aggregate_transport_only_buckets_have_null_percentiles() -> None:
    rollups = [
        _rollup(
            checks=3,
            failures=3,
            latency_p50_ms=0,
            latency_p95_ms=0,
            latency_p99_ms=0,
            latency_sum_ms=0,
        ),
    ]
    stats = aggregate_rollups(rollups, StatsWindow.D7)

    assert stats.checks == 3
    assert stats.failures == 3
    assert stats.uptime_pct == 0.0
    assert stats.latency_p50_ms is None
    assert stats.latency_p95_ms is None
    assert stats.latency_p99_ms is None


# --- rollups-vs-raw parity (SPEC §7 acceptance) ------------------------------


def test_fold_then_aggregate_matches_raw_stats() -> None:
    """Fold a multi-bucket fixture of raw results into hourly rollups, aggregate a
    30-day window, and match the raw `compute_stats` computation (SPEC §7)."""
    hours = [datetime(2026, 7, 14, h, 0, tzinfo=UTC) for h in (10, 11, 12)]
    per_bucket: list[list[CheckResult]] = [
        [
            _result(success=True, latency_ms=(m + 1) * 100, at=hour + timedelta(minutes=m))
            for m in range(10)  # latencies 100..1000 in each hour
        ]
        for hour in hours
    ]
    all_results = [r for bucket in per_bucket for r in bucket]
    now = datetime(2026, 7, 14, 12, 30, tzinfo=UTC)

    rollups = [fold_results_into_rollup(None, bucket) for bucket in per_bucket]
    agg = aggregate_rollups(rollups, StatsWindow.D30)
    raw = compute_stats(all_results, StatsWindow.D30, now)

    assert agg.checks == raw.checks == 30
    assert agg.failures == raw.failures == 0
    assert agg.uptime_pct == raw.uptime_pct == 100.0
    assert agg.latency_p50_ms == raw.latency_p50_ms
    assert agg.latency_p95_ms == raw.latency_p95_ms
    assert agg.latency_p99_ms == raw.latency_p99_ms
