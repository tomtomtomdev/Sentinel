"""Brute-force damping on the auth gate (S14.4, SPEC §6, PLAN D35). Repeated
failed-credential hits from one client are throttled to `429 rate_limited` (the
SPEC §5 envelope) once the per-IP token bucket empties; valid credentials are
never throttled, and the throttle refills over time. The limiter sits behind the
`require_auth` seam (D29) so a Redis-backed one can drop in for multi-instance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from sentinel.application.monitor_service import MonitorService
from sentinel.application.stats_service import StatsService
from sentinel.config import Settings, get_settings
from sentinel.domain.logic.rate_limit import RateLimitConfig
from sentinel.infrastructure.rate_limit import InProcessRateLimiter
from sentinel.interface.api.deps import get_monitor_service, get_rate_limiter, get_stats_service
from sentinel.interface.main import create_app
from tests.support.fakes import (
    FixedClock,
    InMemoryCheckResultRepository,
    InMemoryCheckRollupRepository,
    InMemoryMonitorRepository,
    InMemoryMonitorStateRepository,
)

TOKEN = "s3ntinel-test-token"
CLOCK_NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def build_client(
    *,
    clock: FixedClock,
    capacity: int = 2,
    rate_limit_enabled: bool = True,
    client_ip: str = "203.0.113.5",
) -> httpx.AsyncClient:
    """App gated by TOKEN with a controllable per-IP limiter (fixed clock so refill
    is deterministic). The limiter is a single shared instance for the app so state
    accumulates across requests."""
    limiter = InProcessRateLimiter(
        clock=clock,
        config=RateLimitConfig(capacity=float(capacity), refill_per_second=1.0),
    )
    repo = InMemoryMonitorRepository(clock=clock)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        auth_token=TOKEN, rate_limit_enabled=rate_limit_enabled, rate_limit_window_seconds=60
    )
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_monitor_service] = lambda: MonitorService(repo)
    app.dependency_overrides[get_stats_service] = lambda: StatsService(
        monitors=repo,
        results=InMemoryCheckResultRepository(),
        states=InMemoryMonitorStateRepository(),
        rollups=InMemoryCheckRollupRepository(clock=clock),
        clock=clock,
    )
    transport = httpx.ASGITransport(app=app, client=(client_ip, 12345))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
async def clock() -> FixedClock:
    return FixedClock(CLOCK_NOW)


async def _bad(client: httpx.AsyncClient) -> httpx.Response:
    return await client.get("/api/v1/monitors", headers={"Authorization": "Bearer nope"})


async def test_repeated_failures_get_429_after_the_limit(clock: FixedClock) -> None:
    async with build_client(clock=clock, capacity=2) as client:
        assert (await _bad(client)).status_code == 401
        assert (await _bad(client)).status_code == 401
        throttled = await _bad(client)

    assert throttled.status_code == 429
    assert throttled.json()["error"]["code"] == "rate_limited"
    assert throttled.headers["retry-after"] == "60"
    assert TOKEN not in throttled.text


async def test_valid_token_is_never_throttled(clock: FixedClock) -> None:
    async with build_client(clock=clock, capacity=1) as client:
        assert (await _bad(client)).status_code == 401  # drains the bucket
        assert (await _bad(client)).status_code == 429  # bucket empty
        # A legitimate user behind the same IP must still get through.
        ok = await client.get("/api/v1/monitors", headers={"Authorization": f"Bearer {TOKEN}"})

    assert ok.status_code == 200
    assert ok.json() == []


async def test_throttle_refills_over_time(clock: FixedClock) -> None:
    async with build_client(clock=clock, capacity=1) as client:
        assert (await _bad(client)).status_code == 401
        assert (await _bad(client)).status_code == 429

        clock.set(CLOCK_NOW + timedelta(seconds=2))  # tokens refill
        assert (await _bad(client)).status_code == 401


async def test_disabled_limiter_never_throttles(clock: FixedClock) -> None:
    async with build_client(clock=clock, capacity=1, rate_limit_enabled=False) as client:
        for _ in range(5):
            assert (await _bad(client)).status_code == 401
