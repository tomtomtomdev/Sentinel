"""`POST /api/v1/monitors/{id}/check` (SPEC §3.2, §7 "Probe + assertions").
Exercised via httpx.ASGITransport with the in-memory repos and a fake `HttpProbe`
injected (PLAN D13) — no DB, no network. Proves the use case assembles + persists
a `CheckResult` whose `success`/`error` reflect the probe outcome, and that a
transport failure is a recorded result, NOT an API error (SPEC §3.3)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from sentinel.application.check_service import CheckService
from sentinel.domain.entities import Monitor
from sentinel.domain.errors import ProbeError
from sentinel.domain.value_objects import Assertion, ErrorKind, HttpMethod, ProbeResponse
from sentinel.interface.api.deps import get_check_service
from sentinel.interface.main import create_app
from tests.support.fakes import (
    FakeHttpProbe,
    FixedClock,
    InMemoryCheckResultRepository,
    InMemoryMonitorRepository,
)

CLOCK_NOW = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)


@dataclass
class Harness:
    client: httpx.AsyncClient
    monitors: InMemoryMonitorRepository
    results: InMemoryCheckResultRepository
    probe: FakeHttpProbe

    async def add_monitor(self, **overrides: object) -> Monitor:
        params: dict[str, object] = {
            "name": "Prod health",
            "url": "https://api.example.com/health",
            "interval_seconds": 60,
            "timeout_seconds": 5,
        }
        params.update(overrides)
        return await self.monitors.add(Monitor(**params))  # type: ignore[arg-type]

    def check_url(self, monitor_id: object) -> str:
        return f"/api/v1/monitors/{monitor_id}/check"


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    clock = FixedClock(CLOCK_NOW)
    monitors = InMemoryMonitorRepository(clock=clock)
    results = InMemoryCheckResultRepository()
    probe = FakeHttpProbe()
    app = create_app()
    app.dependency_overrides[get_check_service] = lambda: CheckService(
        monitors=monitors, results=results, probe=probe, clock=clock
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Harness(client=client, monitors=monitors, results=results, probe=probe)
    app.dependency_overrides.clear()


async def test_passing_check_records_success(harness: Harness) -> None:
    monitor = await harness.add_monitor(
        assertions=[Assertion(type="status_code", params={"equals": 200})]
    )
    harness.probe.queue(
        ProbeResponse(
            status_code=200, latency_ms=42, body_sample='{"status":"ok"}', response_size_bytes=15
        )
    )

    response = await harness.client.post(harness.check_url(monitor.id))

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["status_code"] == 200
    assert body["latency_ms"] == 42
    assert body["response_size_bytes"] == 15
    assert body["error"] is None
    assert body["monitor_id"] == str(monitor.id)
    assert [a["type"] for a in body["assertion_results"]] == ["status_code"]
    assert body["assertion_results"][0]["passed"] is True

    persisted = await harness.results.list_for_monitor(monitor.id)
    assert len(persisted) == 1
    assert persisted[0].success is True


async def test_failing_assertion_records_assertion_error(harness: Harness) -> None:
    monitor = await harness.add_monitor(
        assertions=[Assertion(type="max_latency_ms", params={"value": 10})]
    )
    harness.probe.queue(ProbeResponse(status_code=200, latency_ms=500))

    body = (await harness.client.post(harness.check_url(monitor.id))).json()

    assert body["success"] is False
    assert body["status_code"] == 200
    assert body["error"] == ErrorKind.ASSERTION.value
    assert body["assertion_results"][0]["passed"] is False


async def test_transport_failure_is_recorded_result_not_api_error(harness: Harness) -> None:
    monitor = await harness.add_monitor()
    harness.probe.queue(ProbeError(ErrorKind.TIMEOUT, "read timed out"))

    response = await harness.client.post(harness.check_url(monitor.id))

    # A transport failure is a recorded CheckResult, never a 4xx/5xx (SPEC §3.3).
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["error"] == ErrorKind.TIMEOUT.value
    assert body["status_code"] is None
    assert body["latency_ms"] is None
    assert body["assertion_results"] == []

    persisted = await harness.results.list_for_monitor(monitor.id)
    assert len(persisted) == 1
    assert persisted[0].error is ErrorKind.TIMEOUT


async def test_request_is_built_from_the_monitor(harness: Harness) -> None:
    monitor = await harness.add_monitor(
        method=HttpMethod.POST,
        headers={"X-Api-Key": "k"},
        body='{"ping":1}',
    )
    harness.probe.queue(ProbeResponse(status_code=200, latency_ms=5))

    await harness.client.post(harness.check_url(monitor.id))

    assert len(harness.probe.requests) == 1
    sent = harness.probe.requests[0]
    assert sent.method is HttpMethod.POST
    assert sent.url == "https://api.example.com/health"
    assert sent.headers == {"X-Api-Key": "k"}
    assert sent.body == '{"ping":1}'


async def test_unknown_monitor_returns_404(harness: Harness) -> None:
    response = await harness.client.post(harness.check_url(uuid4()))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
