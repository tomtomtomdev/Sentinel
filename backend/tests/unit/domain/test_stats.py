"""S7.1 — pure uptime/latency stats over a window (SPEC §3.5, §7). Fixture-based:
a known set of results yields known counts, uptime %, and percentiles. `now` is
injected; results outside the window are ignored."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sentinel.domain.entities import CheckResult
from sentinel.domain.logic.stats import compute_stats
from sentinel.domain.value_objects import StatsWindow

MID = uuid4()
NOW = datetime(2026, 6, 27, 12, 0, tzinfo=UTC)


def _result(*, success: bool, latency_ms: int | None, at: datetime) -> CheckResult:
    return CheckResult(
        monitor_id=MID,
        started_at=at,
        finished_at=at,
        success=success,
        status_code=200 if success else None,
        latency_ms=latency_ms,
    )


def test_all_success_gives_100_uptime_and_nearest_rank_percentiles() -> None:
    results = [
        _result(success=True, latency_ms=(i + 1) * 10, at=NOW - timedelta(minutes=i))
        for i in range(10)  # latencies 10,20,...,100
    ]
    stats = compute_stats(results, StatsWindow.H24, NOW)
    assert stats.window == "24h"
    assert stats.checks == 10
    assert stats.failures == 0
    assert stats.uptime_pct == 100.0
    assert stats.latency_p50_ms == 50
    assert stats.latency_p95_ms == 100
    assert stats.latency_p99_ms == 100


def test_failures_reduce_uptime_and_transport_failures_excluded_from_percentiles() -> None:
    results = [
        _result(success=True, latency_ms=100, at=NOW - timedelta(minutes=1)),
        _result(success=True, latency_ms=200, at=NOW - timedelta(minutes=2)),
        _result(success=False, latency_ms=None, at=NOW - timedelta(minutes=3)),  # transport fail
        _result(success=False, latency_ms=300, at=NOW - timedelta(minutes=4)),  # assertion fail
    ]
    stats = compute_stats(results, StatsWindow.H24, NOW)
    assert stats.checks == 4
    assert stats.failures == 2
    assert stats.uptime_pct == 50.0
    # percentiles over [100, 200, 300] — the latency-less transport failure is excluded
    assert stats.latency_p50_ms == 200


def test_results_outside_window_are_excluded() -> None:
    inside = _result(success=True, latency_ms=100, at=NOW - timedelta(hours=1))
    outside = _result(success=False, latency_ms=None, at=NOW - timedelta(hours=25))
    stats = compute_stats([inside, outside], StatsWindow.H24, NOW)
    assert stats.checks == 1
    assert stats.failures == 0
    assert stats.uptime_pct == 100.0


def test_result_exactly_at_window_cutoff_is_included() -> None:
    at_cutoff = _result(success=True, latency_ms=100, at=NOW - timedelta(hours=24))
    stats = compute_stats([at_cutoff], StatsWindow.H24, NOW)
    assert stats.checks == 1


def test_no_results_in_window_yields_zeroes_and_null_percentiles() -> None:
    stats = compute_stats([], StatsWindow.H24, NOW)
    assert stats.checks == 0
    assert stats.failures == 0
    assert stats.uptime_pct == 0.0
    assert stats.latency_p50_ms is None
    assert stats.latency_p95_ms is None
    assert stats.latency_p99_ms is None


def test_all_transport_failures_have_null_percentiles() -> None:
    results = [
        _result(success=False, latency_ms=None, at=NOW - timedelta(minutes=i)) for i in range(3)
    ]
    stats = compute_stats(results, StatsWindow.H24, NOW)
    assert stats.checks == 3
    assert stats.failures == 3
    assert stats.uptime_pct == 0.0
    assert stats.latency_p50_ms is None


def test_longer_windows_include_older_results() -> None:
    six_days_old = _result(success=True, latency_ms=100, at=NOW - timedelta(days=6))
    assert compute_stats([six_days_old], StatsWindow.H24, NOW).checks == 0
    assert compute_stats([six_days_old], StatsWindow.D7, NOW).checks == 1
    assert compute_stats([six_days_old], StatsWindow.D30, NOW).checks == 1


def test_uptime_pct_rounds_to_two_decimals() -> None:
    # 1437 successes + 3 failures = 1440 checks -> 99.7916.. -> 99.79 (SPEC §5 example)
    results = [
        _result(success=True, latency_ms=100, at=NOW - timedelta(seconds=i)) for i in range(1437)
    ]
    results += [
        _result(success=False, latency_ms=None, at=NOW - timedelta(seconds=2000 + i))
        for i in range(3)
    ]
    stats = compute_stats(results, StatsWindow.H24, NOW)
    assert stats.checks == 1440
    assert stats.failures == 3
    assert stats.uptime_pct == 99.79
