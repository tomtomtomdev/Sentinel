"""Integration probe matrix (SPEC §7 "Probe + assertions", sentinel-probe-and-
assertions skill). Drives the REAL `HttpxProbe` through the `CheckService` with
httpx routes mocked by `respx`, and asserts the persisted `CheckResult` — not
internal calls. Covers the required matrix: 200 pass · 200 with a failing
assertion · 500 · slow→timeout · malformed JSON."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from sentinel.application.check_service import CheckService
from sentinel.domain.entities import CheckResult, Monitor
from sentinel.domain.value_objects import Assertion, ErrorKind
from sentinel.infrastructure.probe import HttpxProbe
from tests.support.fakes import FixedClock, InMemoryCheckResultRepository, InMemoryMonitorRepository

NOW = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)
URL = "https://api.example.com/health"


async def probe_once(assertions: list[Assertion]) -> CheckResult:
    """Build a one-monitor pipeline around the real httpx probe and run one check,
    returning the persisted result. The caller registers respx routes first."""
    clock = FixedClock(NOW)
    monitors = InMemoryMonitorRepository(clock=clock)
    results = InMemoryCheckResultRepository()
    probe = HttpxProbe()
    monitor = await monitors.add(
        Monitor(name="t", url=URL, assertions=assertions, interval_seconds=60, timeout_seconds=5)
    )
    service = CheckService(monitors=monitors, results=results, probe=probe, clock=clock)
    try:
        return await service.run_check(monitor.id)
    finally:
        await probe.aclose()


@respx.mock
async def test_200_with_passing_assertions() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json={"status": "ok"}))

    result = await probe_once(
        [
            Assertion(type="status_code", params={"equals": 200}),
            Assertion(type="json_path_equals", params={"path": "$.status", "value": "ok"}),
        ]
    )

    assert result.success is True
    assert result.status_code == 200
    assert result.error is None
    assert result.latency_ms is not None and result.latency_ms >= 0
    assert result.response_size_bytes is not None and result.response_size_bytes > 0
    assert result.cert_expires_at is None  # respx has no real TLS cert
    assert all(r.passed for r in result.assertion_results)


@respx.mock
async def test_200_with_a_failing_assertion() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json={"status": "ok"}))

    result = await probe_once(
        [Assertion(type="json_path_equals", params={"path": "$.status", "value": "WRONG"})]
    )

    assert result.success is False
    assert result.status_code == 200
    assert result.error is ErrorKind.ASSERTION
    assert result.assertion_results[0].passed is False


@respx.mock
async def test_500_fails_the_default_2xx_assertion() -> None:
    respx.get(URL).mock(return_value=httpx.Response(500, text="boom"))

    result = await probe_once([])  # no assertions → default status_code in 200–299

    assert result.success is False
    assert result.status_code == 500
    assert result.error is ErrorKind.ASSERTION


@respx.mock
async def test_timeout_is_recorded_not_raised() -> None:
    respx.get(URL).mock(side_effect=httpx.ReadTimeout("read timed out"))

    result = await probe_once([Assertion(type="status_code", params={"equals": 200})])

    assert result.success is False
    assert result.error is ErrorKind.TIMEOUT
    assert result.status_code is None
    assert result.latency_ms is None
    assert result.assertion_results == []


@respx.mock
async def test_malformed_json_fails_cleanly() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, text="<html>not json</html>"))

    result = await probe_once([Assertion(type="json_path_exists", params={"path": "$.status"})])

    assert result.success is False
    assert result.status_code == 200
    assert result.error is ErrorKind.ASSERTION
    assert result.assertion_results[0].passed is False


@respx.mock
async def test_connection_error_classified() -> None:
    respx.get(URL).mock(side_effect=httpx.ConnectError("refused"))

    result = await probe_once([])

    assert result.success is False
    assert result.error is ErrorKind.CONNECTION


@pytest.mark.parametrize(
    ("value", "expected_size"),
    [("12345", 5), ("", 0)],
)
@respx.mock
async def test_response_size_bytes_recorded(value: str, expected_size: int) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, text=value))
    result = await probe_once([])
    assert result.response_size_bytes == expected_size
