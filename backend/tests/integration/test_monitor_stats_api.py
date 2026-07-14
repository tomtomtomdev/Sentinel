"""Read endpoints for history, stats, and the list summary (SPEC §3.5, §5, §7
"Stats"). Exercised via httpx.ASGITransport with in-memory repos injected through
`dependency_overrides` (PLAN D13) — no DB, no network.

- `GET /monitors/{id}/results?from&to&limit` — windowed, newest-first history.
- `GET /monitors/{id}/stats?window=24h|7d|30d` — 24h from raw `compute_stats`,
  7d/30d from the hourly `CheckRollup`s (S7a), plus `status`/`since` from the
  monitor's `MonitorState`.
- `GET /monitors?include=summary` — each monitor gets its status + 24h uptime.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from sentinel.application.monitor_service import MonitorService
from sentinel.application.stats_service import StatsService
from sentinel.domain.entities import CheckResult, Monitor, MonitorState
from sentinel.domain.logic.rollups import fold_results_into_rollup, hour_bucket
from sentinel.domain.value_objects import ErrorKind, MonitorStatus
from sentinel.interface.api.deps import get_monitor_service, get_stats_service
from sentinel.interface.main import create_app
from tests.support.fakes import (
    FixedClock,
    InMemoryCheckResultRepository,
    InMemoryCheckRollupRepository,
    InMemoryMonitorRepository,
    InMemoryMonitorStateRepository,
)

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def iso(dt: datetime) -> str:
    """The API's datetime rendering — Pydantic v2 emits UTC as `...Z`, not `+00:00`."""
    return dt.isoformat().replace("+00:00", "Z")


@dataclass
class Harness:
    client: httpx.AsyncClient
    monitors: InMemoryMonitorRepository
    results: InMemoryCheckResultRepository
    states: InMemoryMonitorStateRepository
    rollups: InMemoryCheckRollupRepository
    clock: FixedClock

    async def fold_rollups(self, monitor_id: object) -> None:
        """Fold the monitor's raw results into hourly `CheckRollup`s, exactly as the
        check pipeline does — so the long-window (7d/30d) path has data to serve."""
        results = await self.results.list_for_monitor(monitor_id, limit=None)  # type: ignore[arg-type]
        buckets: dict[datetime, list[CheckResult]] = {}
        for r in results:
            buckets.setdefault(hour_bucket(r.finished_at), []).append(r)
        for bucket, group in buckets.items():
            existing = await self.rollups.get(monitor_id, bucket)  # type: ignore[arg-type]
            await self.rollups.save(fold_results_into_rollup(existing, group))

    async def add_monitor(self, **overrides: object) -> Monitor:
        params: dict[str, object] = {
            "name": "Prod health",
            "url": "https://api.example.com/health",
            "interval_seconds": 60,
            "timeout_seconds": 5,
        }
        params.update(overrides)
        return await self.monitors.add(Monitor(**params))  # type: ignore[arg-type]

    async def add_result(
        self,
        monitor_id: object,
        *,
        finished_at: datetime,
        success: bool = True,
        latency_ms: int | None = None,
        error: ErrorKind | None = None,
    ) -> CheckResult:
        return await self.results.add(
            CheckResult(
                monitor_id=monitor_id,  # type: ignore[arg-type]
                started_at=finished_at,
                finished_at=finished_at,
                success=success,
                status_code=None if error else 200,
                latency_ms=latency_ms,
                error=error,
            )
        )


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    clock = FixedClock(NOW)
    monitors = InMemoryMonitorRepository(clock=clock)
    results = InMemoryCheckResultRepository()
    states = InMemoryMonitorStateRepository()
    rollups = InMemoryCheckRollupRepository(clock=clock)
    app = create_app()
    app.dependency_overrides[get_monitor_service] = lambda: MonitorService(monitors)
    app.dependency_overrides[get_stats_service] = lambda: StatsService(
        monitors=monitors, results=results, states=states, rollups=rollups, clock=clock
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Harness(
            client=client,
            monitors=monitors,
            results=results,
            states=states,
            rollups=rollups,
            clock=clock,
        )
    app.dependency_overrides.clear()


# --- GET /monitors/{id}/results ---------------------------------------------


class TestResults:
    async def test_returns_history_newest_first(self, harness: Harness) -> None:
        monitor = await harness.add_monitor()
        await harness.add_result(monitor.id, finished_at=NOW - timedelta(minutes=2), latency_ms=10)
        newest = await harness.add_result(
            monitor.id, finished_at=NOW - timedelta(minutes=1), latency_ms=20
        )

        response = await harness.client.get(f"/api/v1/monitors/{monitor.id}/results")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 2
        assert body[0]["id"] == str(newest.id)  # newest first
        assert body[0]["latency_ms"] == 20

    async def test_from_to_window_filters_inclusive(self, harness: Harness) -> None:
        monitor = await harness.add_monitor()
        for minutes in (10, 20, 30, 40):
            await harness.add_result(monitor.id, finished_at=NOW - timedelta(minutes=minutes))

        frm = (NOW - timedelta(minutes=30)).isoformat()
        to = (NOW - timedelta(minutes=20)).isoformat()
        response = await harness.client.get(
            f"/api/v1/monitors/{monitor.id}/results", params={"from": frm, "to": to}
        )

        assert response.status_code == 200
        finished = {r["finished_at"] for r in response.json()}
        assert finished == {
            iso(NOW - timedelta(minutes=20)),
            iso(NOW - timedelta(minutes=30)),
        }

    async def test_respects_limit(self, harness: Harness) -> None:
        monitor = await harness.add_monitor()
        for minutes in range(5):
            await harness.add_result(monitor.id, finished_at=NOW - timedelta(minutes=minutes))

        response = await harness.client.get(
            f"/api/v1/monitors/{monitor.id}/results", params={"limit": 2}
        )
        assert len(response.json()) == 2

    async def test_unknown_monitor_returns_404(self, harness: Harness) -> None:
        response = await harness.client.get(f"/api/v1/monitors/{uuid4()}/results")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


# --- GET /monitors/{id}/stats -----------------------------------------------


class TestStats:
    async def test_stats_match_fixture_with_status_and_since(self, harness: Harness) -> None:
        monitor = await harness.add_monitor()
        # 9 successes with latencies 100..900, plus one transport failure (no latency).
        for i, latency in enumerate(range(100, 1000, 100)):
            await harness.add_result(
                monitor.id, finished_at=NOW - timedelta(minutes=i + 1), latency_ms=latency
            )
        await harness.add_result(
            monitor.id,
            finished_at=NOW - timedelta(minutes=10),
            success=False,
            error=ErrorKind.TIMEOUT,
        )
        since = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
        await harness.states.save(
            MonitorState(monitor_id=monitor.id, since=since, status=MonitorStatus.UP)
        )

        response = await harness.client.get(f"/api/v1/monitors/{monitor.id}/stats")

        assert response.status_code == 200
        body = response.json()
        assert body["window"] == "24h"
        assert body["checks"] == 10
        assert body["failures"] == 1
        assert body["uptime_pct"] == 90.0
        # nearest-rank over [100..900]: p50=500, p95=p99=900
        assert body["latency_ms"] == {"p50": 500, "p95": 900, "p99": 900}
        assert body["status"] == "up"
        assert body["since"] == iso(since)

    async def test_window_selects_the_range(self, harness: Harness) -> None:
        monitor = await harness.add_monitor()
        await harness.add_result(monitor.id, finished_at=NOW - timedelta(hours=1), latency_ms=50)
        # 2 days ago: outside 24h, inside 7d.
        await harness.add_result(monitor.id, finished_at=NOW - timedelta(days=2), latency_ms=90)
        await harness.fold_rollups(monitor.id)  # 7d/30d are served from rollups (S7a)

        # 24h is still computed from raw — only the 1h-old result is in range.
        h24 = (await harness.client.get(f"/api/v1/monitors/{monitor.id}/stats")).json()
        assert h24["checks"] == 1

        # 7d is aggregated from the two hourly rollups.
        d7 = (
            await harness.client.get(
                f"/api/v1/monitors/{monitor.id}/stats", params={"window": "7d"}
            )
        ).json()
        assert d7["window"] == "7d"
        assert d7["checks"] == 2

    async def test_long_window_served_from_rollups(self, harness: Harness) -> None:
        monitor = await harness.add_monitor()
        # Two hourly buckets 8 days back (outside 24h, inside 30d), each with
        # latencies 100..1000 over 10 successful checks.
        base = NOW - timedelta(days=8)
        for hour in (base, base + timedelta(hours=1)):
            for m in range(10):
                await harness.add_result(
                    monitor.id, finished_at=hour + timedelta(minutes=m), latency_ms=(m + 1) * 100
                )
        await harness.fold_rollups(monitor.id)

        d30 = (
            await harness.client.get(
                f"/api/v1/monitors/{monitor.id}/stats", params={"window": "30d"}
            )
        ).json()
        assert d30["window"] == "30d"
        assert d30["checks"] == 20
        assert d30["uptime_pct"] == 100.0
        # Uniform buckets → aggregated percentiles equal the raw nearest-rank values.
        assert d30["latency_ms"] == {"p50": 500, "p95": 1000, "p99": 1000}

        # 24h (raw) sees none of the 8-day-old checks.
        h24 = (await harness.client.get(f"/api/v1/monitors/{monitor.id}/stats")).json()
        assert h24["checks"] == 0

    async def test_no_data_reads_unknown(self, harness: Harness) -> None:
        monitor = await harness.add_monitor()

        body = (await harness.client.get(f"/api/v1/monitors/{monitor.id}/stats")).json()

        assert body["checks"] == 0
        assert body["failures"] == 0
        assert body["uptime_pct"] == 0.0
        assert body["latency_ms"] == {"p50": None, "p95": None, "p99": None}
        assert body["status"] == "unknown"
        assert body["since"] is None

    async def test_unknown_window_returns_422(self, harness: Harness) -> None:
        monitor = await harness.add_monitor()
        response = await harness.client.get(
            f"/api/v1/monitors/{monitor.id}/stats", params={"window": "90d"}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    async def test_unknown_monitor_returns_404(self, harness: Harness) -> None:
        response = await harness.client.get(f"/api/v1/monitors/{uuid4()}/stats")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


# --- GET /monitors?include=summary ------------------------------------------


class TestListSummary:
    async def test_include_summary_attaches_status_and_uptime(self, harness: Harness) -> None:
        monitor = await harness.add_monitor()
        for i, latency in enumerate((100, 200, 300, 400)):
            await harness.add_result(
                monitor.id, finished_at=NOW - timedelta(minutes=i + 1), latency_ms=latency
            )
        last_check = NOW - timedelta(minutes=1)
        since = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)
        await harness.states.save(
            MonitorState(
                monitor_id=monitor.id,
                since=since,
                status=MonitorStatus.UP,
                last_check_at=last_check,
            )
        )

        response = await harness.client.get("/api/v1/monitors", params={"include": "summary"})

        assert response.status_code == 200
        summary = response.json()[0]["summary"]
        assert summary is not None
        assert summary["status"] == "up"
        assert summary["since"] == iso(since)
        assert summary["last_check_at"] == iso(last_check)
        assert summary["uptime_pct"] == 100.0
        assert summary["checks"] == 4
        assert summary["latency_p95_ms"] == 400

    async def test_summary_unknown_when_no_state_or_results(self, harness: Harness) -> None:
        await harness.add_monitor()

        response = await harness.client.get("/api/v1/monitors", params={"include": "summary"})

        summary = response.json()[0]["summary"]
        assert summary["status"] == "unknown"
        assert summary["checks"] == 0
        assert summary["uptime_pct"] == 0.0
        assert summary["latency_p95_ms"] is None
        assert summary["since"] is None
        assert summary["last_check_at"] is None

    async def test_list_without_include_has_no_summary(self, harness: Harness) -> None:
        await harness.add_monitor()

        response = await harness.client.get("/api/v1/monitors")

        assert response.status_code == 200
        assert response.json()[0]["summary"] is None
