"""Minimal API auth gate (S9a; sentinel-security §4, PLAN D9). With AUTH_TOKEN
configured, every `/api/v1/*` route — reads, writes, and the SSE stream — demands
`Authorization: Bearer <AUTH_TOKEN>`; missing/invalid credentials get a 401 in the
SPEC §5 error envelope. The `/api/v1/health` liveness probe stays open, and an
empty AUTH_TOKEN leaves the whole gate open (dev mode — never deploy like that)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from sentinel.application.monitor_service import MonitorService
from sentinel.application.stats_service import StatsService
from sentinel.config import Settings, get_settings
from sentinel.interface.api.deps import get_monitor_service, get_stats_service
from sentinel.interface.main import create_app
from tests.support.fakes import (
    FixedClock,
    InMemoryCheckResultRepository,
    InMemoryCheckRollupRepository,
    InMemoryMonitorRepository,
    InMemoryMonitorStateRepository,
)

TOKEN = "s3ntinel-test-token"
CLOCK_NOW = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)


def build_client(auth_token: str) -> httpx.AsyncClient:
    """App with the gate driven by `auth_token` and fake-backed monitor reads, so
    authorized requests can reach a real handler without a DB."""
    clock = FixedClock(CLOCK_NOW)
    repo = InMemoryMonitorRepository(clock=clock)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(auth_token=auth_token)
    app.dependency_overrides[get_monitor_service] = lambda: MonitorService(repo)
    app.dependency_overrides[get_stats_service] = lambda: StatsService(
        monitors=repo,
        results=InMemoryCheckResultRepository(),
        states=InMemoryMonitorStateRepository(),
        rollups=InMemoryCheckRollupRepository(clock=clock),
        clock=clock,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with build_client(auth_token=TOKEN) as client:
        yield client


async def test_missing_token_is_401_in_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/monitors")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_wrong_token_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/monitors", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401
    assert TOKEN not in response.text


async def test_non_bearer_scheme_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/monitors", headers={"Authorization": f"Basic {TOKEN}"})
    assert response.status_code == 401


async def test_valid_token_is_accepted(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/monitors", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert response.json() == []


# One (method, path) per registered router — proves the gate covers the whole
# /api/v1 surface (writes, reads, imports, auth sources, channels, SSE events),
# not just the monitors router.
GATED_ROUTES = [
    ("GET", "/api/v1/monitors"),
    ("POST", "/api/v1/monitors"),
    ("GET", f"/api/v1/monitors/{uuid4()}/results"),
    ("POST", "/api/v1/imports/curl"),
    ("GET", "/api/v1/auth-sources"),
    ("GET", "/api/v1/channels"),
    ("GET", "/api/v1/events"),
]


@pytest.mark.parametrize(("method", "path"), GATED_ROUTES)
async def test_every_router_is_gated(client: httpx.AsyncClient, method: str, path: str) -> None:
    response = await client.request(method, path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_health_liveness_probe_stays_open(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_empty_auth_token_leaves_gate_open_for_dev() -> None:
    async with build_client(auth_token="") as client:
        response = await client.get("/api/v1/monitors")
    assert response.status_code == 200
