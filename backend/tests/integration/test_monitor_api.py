"""Monitor CRUD API (SPEC §3.2, §5, §7). Exercised via httpx.ASGITransport with
the in-memory repository injected, so the suite stays DB-free and fast. The
Postgres repository contract is proven separately in test_monitor_repository.py.

Asserts the SPEC §7 acceptance criterion for manual create (201 + redacted
Authorization), redaction at the boundary, and the §5 error envelope."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from sentinel.application.monitor_service import MonitorService
from sentinel.application.stats_service import StatsService
from sentinel.domain.logic.redaction import MASK
from sentinel.interface.api.deps import get_monitor_service, get_stats_service
from sentinel.interface.main import create_app
from tests.support.fakes import (
    FixedClock,
    InMemoryCheckResultRepository,
    InMemoryMonitorRepository,
    InMemoryMonitorStateRepository,
)

CLOCK_NOW = datetime(2026, 6, 26, 9, 0, tzinfo=UTC)

VALID_PAYLOAD = {
    "name": "Prod health",
    "method": "GET",
    "url": "https://api.example.com/health",
    "headers": {
        "Authorization": "Bearer supersecret",
        "X-Api-Key": "k",
        "Accept": "application/json",
    },
    "assertions": [{"type": "status_code", "params": {"equals": 200}}],
    "interval_seconds": 60,
    "timeout_seconds": 10,
}

MONITORS = "/api/v1/monitors"


@pytest.fixture
async def api() -> AsyncIterator[tuple[httpx.AsyncClient, InMemoryMonitorRepository]]:
    clock = FixedClock(CLOCK_NOW)
    repo = InMemoryMonitorRepository(clock=clock)
    app = create_app()
    app.dependency_overrides[get_monitor_service] = lambda: MonitorService(repo)
    # The list route composes StatsService for `?include=summary`; wire a fake-backed
    # one over the same monitor repo so plain-list tests resolve it without a DB.
    app.dependency_overrides[get_stats_service] = lambda: StatsService(
        monitors=repo,
        results=InMemoryCheckResultRepository(),
        states=InMemoryMonitorStateRepository(),
        clock=clock,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, repo
    app.dependency_overrides.clear()


class TestCreate:
    async def test_valid_monitor_returns_201_and_persists(
        self, api: tuple[httpx.AsyncClient, InMemoryMonitorRepository]
    ) -> None:
        client, repo = api
        response = await client.post(MONITORS, json=VALID_PAYLOAD)

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Prod health"
        assert body["url"] == "https://api.example.com/health"
        assert body["interval_seconds"] == 60
        assert UUID(body["id"])
        assert body["created_at"] is not None
        assert body["updated_at"] is not None

        stored = await repo.get(UUID(body["id"]))
        assert stored is not None
        assert stored.name == "Prod health"

    async def test_response_redacts_secret_headers(
        self, api: tuple[httpx.AsyncClient, InMemoryMonitorRepository]
    ) -> None:
        client, _ = api
        body = (await client.post(MONITORS, json=VALID_PAYLOAD)).json()
        assert body["headers"]["Authorization"] == f"Bearer {MASK}"
        assert body["headers"]["X-Api-Key"] == MASK
        assert body["headers"]["Accept"] == "application/json"

    async def test_stored_secret_is_not_redacted(
        self, api: tuple[httpx.AsyncClient, InMemoryMonitorRepository]
    ) -> None:
        client, repo = api
        body = (await client.post(MONITORS, json=VALID_PAYLOAD)).json()
        stored = await repo.get(UUID(body["id"]))
        assert stored is not None
        assert stored.headers["Authorization"] == "Bearer supersecret"

    async def test_domain_invariant_violation_returns_422_envelope(
        self, api: tuple[httpx.AsyncClient, InMemoryMonitorRepository]
    ) -> None:
        client, _ = api
        response = await client.post(MONITORS, json={**VALID_PAYLOAD, "interval_seconds": 10})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    async def test_malformed_request_returns_422_envelope(
        self, api: tuple[httpx.AsyncClient, InMemoryMonitorRepository]
    ) -> None:
        client, _ = api
        response = await client.post(MONITORS, json={**VALID_PAYLOAD, "method": "FLY"})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


class TestListAndGet:
    async def test_list_returns_all_redacted(
        self, api: tuple[httpx.AsyncClient, InMemoryMonitorRepository]
    ) -> None:
        client, _ = api
        await client.post(MONITORS, json={**VALID_PAYLOAD, "name": "A"})
        await client.post(MONITORS, json={**VALID_PAYLOAD, "name": "B"})

        response = await client.get(MONITORS)
        assert response.status_code == 200
        items = response.json()
        assert {m["name"] for m in items} == {"A", "B"}
        assert all(m["headers"]["Authorization"] == f"Bearer {MASK}" for m in items)

    async def test_get_one_returns_redacted_monitor(
        self, api: tuple[httpx.AsyncClient, InMemoryMonitorRepository]
    ) -> None:
        client, _ = api
        created = (await client.post(MONITORS, json=VALID_PAYLOAD)).json()
        response = await client.get(f"{MONITORS}/{created['id']}")
        assert response.status_code == 200
        assert response.json()["headers"]["Authorization"] == f"Bearer {MASK}"

    async def test_get_unknown_returns_404_envelope(
        self, api: tuple[httpx.AsyncClient, InMemoryMonitorRepository]
    ) -> None:
        client, _ = api
        response = await client.get(f"{MONITORS}/{uuid4()}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


class TestUpdate:
    async def test_patch_updates_fields_and_persists(
        self, api: tuple[httpx.AsyncClient, InMemoryMonitorRepository]
    ) -> None:
        client, repo = api
        created = (await client.post(MONITORS, json=VALID_PAYLOAD)).json()

        response = await client.patch(
            f"{MONITORS}/{created['id']}",
            json={"name": "Renamed", "interval_seconds": 120, "enabled": False},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Renamed"
        assert body["interval_seconds"] == 120
        assert body["enabled"] is False
        # untouched secret header still redacted in the response
        assert body["headers"]["Authorization"] == f"Bearer {MASK}"

        stored = await repo.get(UUID(created["id"]))
        assert stored is not None
        assert stored.name == "Renamed"
        assert stored.interval_seconds == 120

    async def test_patch_invalid_value_returns_422(
        self, api: tuple[httpx.AsyncClient, InMemoryMonitorRepository]
    ) -> None:
        client, _ = api
        created = (await client.post(MONITORS, json=VALID_PAYLOAD)).json()
        response = await client.patch(f"{MONITORS}/{created['id']}", json={"interval_seconds": 5})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    async def test_patch_unknown_returns_404(
        self, api: tuple[httpx.AsyncClient, InMemoryMonitorRepository]
    ) -> None:
        client, _ = api
        response = await client.patch(f"{MONITORS}/{uuid4()}", json={"name": "x"})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


class TestDelete:
    async def test_delete_removes_monitor(
        self, api: tuple[httpx.AsyncClient, InMemoryMonitorRepository]
    ) -> None:
        client, _ = api
        created = (await client.post(MONITORS, json=VALID_PAYLOAD)).json()

        response = await client.delete(f"{MONITORS}/{created['id']}")
        assert response.status_code == 204

        assert (await client.get(f"{MONITORS}/{created['id']}")).status_code == 404

    async def test_delete_unknown_returns_404(
        self, api: tuple[httpx.AsyncClient, InMemoryMonitorRepository]
    ) -> None:
        client, _ = api
        response = await client.delete(f"{MONITORS}/{uuid4()}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
