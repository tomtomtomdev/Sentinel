"""Health/readiness probes (SPEC §6). `/health` is pure liveness — the process is
up, no dependency checks, so a transient DB outage never restarts a healthy web
process. `/ready` (S14.3) is readiness — it pings Postgres (`SELECT 1`) and returns
503 when the DB is unreachable so a load balancer drains this instance. Both stay
outside the S9a auth gate (orchestrators probe without credentials)."""

from __future__ import annotations

import httpx

from sentinel.config import Settings, get_settings
from sentinel.interface.api.deps import get_readiness_check
from sentinel.interface.main import app, create_app


class FakeReadinessCheck:
    def __init__(self, *, ok: bool) -> None:
        self._ok = ok

    async def check(self) -> bool:
        return self._ok


def build_client(*, ready: bool, auth_token: str = "") -> httpx.AsyncClient:
    test_app = create_app()
    test_app.dependency_overrides[get_readiness_check] = lambda: FakeReadinessCheck(ok=ready)
    test_app.dependency_overrides[get_settings] = lambda: Settings(auth_token=auth_token)
    transport = httpx.ASGITransport(app=test_app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_health_returns_ok() -> None:
    """SPEC §6 / §3: GET /api/v1/health is a liveness endpoint returning 200 OK."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_is_liveness_and_never_touches_the_db() -> None:
    # Even with readiness reporting the DB down, liveness stays 200: it must not
    # depend on the database, or a DB blip would restart a healthy process.
    async with build_client(ready=False) as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_returns_200_when_database_reachable() -> None:
    async with build_client(ready=True) as client:
        response = await client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


async def test_ready_returns_503_when_database_unreachable() -> None:
    async with build_client(ready=False) as client:
        response = await client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"database": "error"}}


async def test_health_and_ready_stay_outside_the_auth_gate() -> None:
    # With a token configured, both probes answer without credentials (a 401
    # would mean an orchestrator can't probe them).
    async with build_client(ready=True, auth_token="s3ntinel-token") as client:
        health = await client.get("/api/v1/health")
        ready = await client.get("/api/v1/ready")

    assert health.status_code == 200
    assert ready.status_code == 200
