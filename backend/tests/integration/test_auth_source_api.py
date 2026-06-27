"""Auth-source CRUD + manual-refresh API (SPEC §3.9, §5). Exercised via
httpx.ASGITransport with the in-memory repos/store and a scriptable `FakeHttpProbe`
injected (PLAN D13) — no DB, no network. Proves responses redact every credential
(request body, secret headers, oauth secrets), that refresh returns metadata only
(never the token value), and that a monitor cannot link to a non-existent source."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from sentinel.application.auth_source_service import AuthSourceService
from sentinel.application.auth_token_service import AuthTokenService
from sentinel.application.monitor_service import MonitorService
from sentinel.domain.entities import AuthSource
from sentinel.domain.value_objects import (
    ExpiryKind,
    ExpirySpec,
    ExtractorKind,
    HttpMethod,
    Injection,
    InjectionTarget,
    ProbeRequest,
    ProbeResponse,
    TokenExtractor,
)
from sentinel.interface.api.deps import (
    get_auth_source_service,
    get_auth_token_service,
    get_clock,
    get_monitor_service,
    get_token_store,
)
from sentinel.interface.main import create_app
from tests.support.fakes import (
    FakeHttpProbe,
    FixedClock,
    InMemoryAuthSourceRepository,
    InMemoryMonitorRepository,
    InMemoryTokenStore,
)

NOW = datetime(2026, 6, 27, 12, 0, tzinfo=UTC)


def create_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Login",
        "mode": "custom",
        "request": {
            "method": "POST",
            "url": "https://id.example.com/login",
            "headers": {"Content-Type": "application/json", "X-Api-Key": "k"},
            "body": '{"username":"u","password":"p"}',
        },
        "extractor": {"kind": "json_path", "expr": "$.access_token"},
        "expiry": {"kind": "json_path_seconds", "value": "$.expires_in"},
        "injection": {"target": "header", "name": "Authorization"},
    }
    payload.update(overrides)
    return payload


@dataclass
class Harness:
    client: httpx.AsyncClient
    sources: InMemoryAuthSourceRepository
    tokens: InMemoryTokenStore
    monitors: InMemoryMonitorRepository
    probe: FakeHttpProbe

    async def add_source(self, **overrides: object) -> AuthSource:
        params: dict[str, object] = {
            "name": "Login",
            "request": ProbeRequest(
                method=HttpMethod.POST,
                url="https://id.example.com/login",
                body='{"username":"u","password":"p"}',
            ),
            "extractor": TokenExtractor(kind=ExtractorKind.JSON_PATH, expr="$.access_token"),
            "expiry": ExpirySpec(kind=ExpiryKind.JSON_PATH_SECONDS, value="$.expires_in"),
            "injection": Injection(target=InjectionTarget.HEADER, name="Authorization"),
        }
        params.update(overrides)
        return await self.sources.add(AuthSource(**params))  # type: ignore[arg-type]


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    clock = FixedClock(NOW)
    sources = InMemoryAuthSourceRepository(clock=clock)
    tokens = InMemoryTokenStore()
    monitors = InMemoryMonitorRepository(clock=clock)
    probe = FakeHttpProbe()
    app = create_app()
    app.dependency_overrides[get_clock] = lambda: clock
    app.dependency_overrides[get_auth_source_service] = lambda: AuthSourceService(sources)
    app.dependency_overrides[get_token_store] = lambda: tokens
    app.dependency_overrides[get_auth_token_service] = lambda: AuthTokenService(
        sources=sources, tokens=tokens, probe=probe, clock=clock
    )
    app.dependency_overrides[get_monitor_service] = lambda: MonitorService(
        monitors, auth_sources=sources
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Harness(client=client, sources=sources, tokens=tokens, monitors=monitors, probe=probe)
    app.dependency_overrides.clear()


# --------------------------------------------------------------------- CRUD


async def test_create_redacts_credentials_but_stores_full(harness: Harness) -> None:
    response = await harness.client.post("/api/v1/auth-sources", json=create_payload())

    assert response.status_code == 201
    body = response.json()
    # Credentials are redacted in the response...
    assert body["request"]["body"] == "••••"
    assert body["request"]["headers"]["X-Api-Key"] == "••••"
    assert body["request"]["headers"]["Content-Type"] == "application/json"
    # The credential payload never appears in the response.
    assert '{"username":"u","password":"p"}' not in response.text

    # ...but stored in full.
    stored = (await harness.sources.list())[0]
    assert stored.request.body == '{"username":"u","password":"p"}'
    assert stored.request.headers["X-Api-Key"] == "k"


async def test_create_oauth_redacts_client_secret(harness: Harness) -> None:
    payload = create_payload(
        mode="oauth2_client_credentials",
        oauth={
            "token_url": "https://id.example.com/token",
            "client_id": "cid",
            "client_secret": "super-secret",
            "client_auth": "basic",
        },
    )
    response = await harness.client.post("/api/v1/auth-sources", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["oauth"]["client_id"] == "cid"
    assert body["oauth"]["client_secret"] == "••••"
    assert "super-secret" not in response.text


async def test_list_returns_all(harness: Harness) -> None:
    await harness.add_source(name="A")
    await harness.add_source(name="B")
    response = await harness.client.get("/api/v1/auth-sources")
    assert response.status_code == 200
    assert {s["name"] for s in response.json()} == {"A", "B"}


async def test_get_includes_token_state_none_when_no_token(harness: Harness) -> None:
    source = await harness.add_source()
    response = await harness.client.get(f"/api/v1/auth-sources/{source.id}")
    assert response.status_code == 200
    assert response.json()["token_state"]["status"] == "none"


async def test_get_unknown_returns_404(harness: Harness) -> None:
    response = await harness.client.get(f"/api/v1/auth-sources/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_patch_updates_field(harness: Harness) -> None:
    source = await harness.add_source()
    response = await harness.client.patch(
        f"/api/v1/auth-sources/{source.id}", json={"name": "Renamed", "enabled": False}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed"
    assert body["enabled"] is False


async def test_delete_then_404(harness: Harness) -> None:
    source = await harness.add_source()
    assert (await harness.client.delete(f"/api/v1/auth-sources/{source.id}")).status_code == 204
    assert (await harness.client.get(f"/api/v1/auth-sources/{source.id}")).status_code == 404


# ----------------------------------------------------------------- refresh


async def test_refresh_returns_metadata_only_never_the_token(harness: Harness) -> None:
    source = await harness.add_source()
    harness.probe.queue(
        ProbeResponse(
            status_code=200,
            latency_ms=5,
            body_sample='{"access_token":"secret-tok-123","expires_in":3600}',
        )
    )

    response = await harness.client.post(f"/api/v1/auth-sources/{source.id}/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "valid"
    assert body["obtained_at"] is not None
    assert datetime.fromisoformat(body["expires_at"]) == NOW + timedelta(seconds=3600)
    # The token value must never appear anywhere in the response.
    assert "secret-tok-123" not in response.text
    assert (
        "token" not in {k for k in body if k not in ("token_state",)} or body.get("token") is None
    )

    # ...but it is cached for dependent monitors.
    cached = await harness.tokens.load(source.id)
    assert cached is not None
    assert cached.token == "secret-tok-123"


async def test_refresh_failure_records_error_status_no_leak(harness: Harness) -> None:
    source = await harness.add_source()
    harness.probe.queue(
        ProbeResponse(status_code=401, latency_ms=5, body_sample='{"error":"nope"}')
    )

    response = await harness.client.post(f"/api/v1/auth-sources/{source.id}/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["last_refresh_error"]
    cached = await harness.tokens.load(source.id)
    assert cached is None or not cached.token


async def test_refresh_unknown_source_returns_404(harness: Harness) -> None:
    response = await harness.client.post(f"/api/v1/auth-sources/{uuid4()}/refresh")
    assert response.status_code == 404


# ------------------------------------------------ monitor auth_source_id link


async def test_monitor_create_rejects_unknown_auth_source(harness: Harness) -> None:
    response = await harness.client.post(
        "/api/v1/monitors",
        json={
            "name": "Prod",
            "url": "https://api.example.com/health",
            "interval_seconds": 60,
            "timeout_seconds": 5,
            "auth_source_id": str(uuid4()),
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_monitor_create_accepts_existing_auth_source(harness: Harness) -> None:
    source = await harness.add_source()
    response = await harness.client.post(
        "/api/v1/monitors",
        json={
            "name": "Prod",
            "url": "https://api.example.com/health",
            "interval_seconds": 60,
            "timeout_seconds": 5,
            "auth_source_id": str(source.id),
        },
    )
    assert response.status_code == 201
    assert response.json()["auth_source_id"] == str(source.id)
