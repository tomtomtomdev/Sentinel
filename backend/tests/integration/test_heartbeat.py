"""The `HttpxHeartbeat` dead-man's switch adapter (SPEC §6, PLAN D8). A ping must
reach the watchdog URL and must never raise — a flaky watchdog can't be allowed to
crash the runner. `respx` mocks the outbound GET (no real network)."""

from __future__ import annotations

import httpx
import respx

from sentinel.infrastructure.heartbeat import HttpxHeartbeat, NullHeartbeat

URL = "https://hc-ping.example.com/abc-123"


@respx.mock
async def test_ping_issues_a_get_to_the_configured_url() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200))
    heartbeat = HttpxHeartbeat(URL)

    await heartbeat.ping()

    assert route.called
    await heartbeat.aclose()


@respx.mock
async def test_ping_swallows_transport_errors() -> None:
    respx.get(URL).mock(side_effect=httpx.ConnectError("watchdog unreachable"))
    heartbeat = HttpxHeartbeat(URL)

    # Must not raise — the runner stays alive even if the watchdog is down.
    await heartbeat.ping()
    await heartbeat.aclose()


async def test_null_heartbeat_is_inert() -> None:
    await NullHeartbeat().ping()  # no URL configured → no-op, no error
