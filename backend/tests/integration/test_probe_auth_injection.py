"""Auth-source injection in the probe pipeline (SPEC §3.9). Exercises
`CheckService.run_check` with a monitor linked to an auth source, using the
in-memory repos/store and a scriptable `FakeHttpProbe` (PLAN D13) — no network.
Covers: the cached token is injected; a missing/expired token is refreshed
proactively before the probe; a 401 triggers exactly one reactive refresh + one
retry; a persistent 401 is one recorded failed check (no loop); and oauth2
refresh-token reuse with fallback to a full login."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

from sentinel.application.auth_token_service import AuthTokenService
from sentinel.application.check_service import CheckService
from sentinel.domain.entities import AuthSource, Monitor, TokenState
from sentinel.domain.value_objects import (
    AuthSourceMode,
    ClientAuth,
    ExpiryKind,
    ExpirySpec,
    ExtractorKind,
    HttpMethod,
    Injection,
    InjectionTarget,
    OAuthConfig,
    ProbeRequest,
    ProbeResponse,
    TokenExtractor,
)
from tests.support.fakes import (
    FakeHttpProbe,
    FixedClock,
    InMemoryAuthSourceRepository,
    InMemoryCheckResultRepository,
    InMemoryMonitorRepository,
    InMemoryTokenStore,
)

NOW = datetime(2026, 6, 27, 12, 0, tzinfo=UTC)


class Harness:
    def __init__(self) -> None:
        self.clock = FixedClock(NOW)
        self.monitors = InMemoryMonitorRepository(clock=self.clock)
        self.results = InMemoryCheckResultRepository()
        self.sources = InMemoryAuthSourceRepository(clock=self.clock)
        self.tokens = InMemoryTokenStore()
        self.probe = FakeHttpProbe()
        self.auth = AuthTokenService(
            sources=self.sources, tokens=self.tokens, probe=self.probe, clock=self.clock
        )
        self.service = CheckService(
            monitors=self.monitors,
            results=self.results,
            probe=self.probe,
            clock=self.clock,
            auth_sources=self.sources,
            auth=self.auth,
        )

    async def custom_source(self, **overrides: object) -> AuthSource:
        params: dict[str, object] = {
            "name": "Login",
            "mode": AuthSourceMode.CUSTOM,
            "request": ProbeRequest(method=HttpMethod.POST, url="https://id.example.com/login"),
            "extractor": TokenExtractor(kind=ExtractorKind.JSON_PATH, expr="$.access_token"),
            "expiry": ExpirySpec(kind=ExpiryKind.JSON_PATH_SECONDS, value="$.expires_in"),
            "injection": Injection(target=InjectionTarget.HEADER, name="Authorization"),
        }
        params.update(overrides)
        return await self.sources.add(AuthSource(**params))  # type: ignore[arg-type]

    async def oauth_source(self) -> AuthSource:
        return await self.sources.add(
            AuthSource(
                name="OAuth",
                mode=AuthSourceMode.OAUTH2_CLIENT_CREDENTIALS,
                request=ProbeRequest(method=HttpMethod.POST, url="https://id.example.com/token"),
                oauth=OAuthConfig(
                    token_url="https://id.example.com/token",
                    client_id="cid",
                    client_secret="sec",
                    client_auth=ClientAuth.BODY,
                ),
                extractor=TokenExtractor(kind=ExtractorKind.JSON_PATH, expr="$.access_token"),
                expiry=ExpirySpec(kind=ExpiryKind.JSON_PATH_SECONDS, value="$.expires_in"),
                injection=Injection(target=InjectionTarget.HEADER, name="Authorization"),
            )
        )

    async def monitor_for(self, source: AuthSource) -> Monitor:
        return await self.monitors.add(
            Monitor(
                name="Prod",
                url="https://api.example.com/health",
                interval_seconds=60,
                timeout_seconds=5,
                auth_source_id=source.id,
            )
        )

    def cache_token(self, source: AuthSource, **overrides: object) -> None:
        params: dict[str, object] = {
            "auth_source_id": source.id,
            "token": "cached-tok",
            "token_type": "Bearer",
            "obtained_at": NOW,
            "expires_at": NOW + timedelta(hours=1),
        }
        params.update(overrides)
        self.tokens._store[source.id] = TokenState(**params)  # type: ignore[arg-type]


def login(body: str) -> ProbeResponse:
    return ProbeResponse(status_code=200, latency_ms=3, body_sample=body)


async def test_cached_token_is_injected() -> None:
    h = Harness()
    source = await h.custom_source()
    monitor = await h.monitor_for(source)
    h.cache_token(source, token="cached-tok")
    h.probe.queue(ProbeResponse(status_code=200, latency_ms=5))

    result = await h.service.run_check(monitor.id)

    assert result.success is True
    assert len(h.probe.requests) == 1  # no login needed
    assert h.probe.requests[0].headers["Authorization"] == "Bearer cached-tok"


async def test_missing_token_is_refreshed_proactively_then_injected() -> None:
    h = Harness()
    source = await h.custom_source()
    monitor = await h.monitor_for(source)
    # No cached token → a login probe runs first, then the monitor probe.
    h.probe.queue(login('{"access_token":"fresh-tok","expires_in":3600}'))
    h.probe.queue(ProbeResponse(status_code=200, latency_ms=5))

    result = await h.service.run_check(monitor.id)

    assert result.success is True
    assert len(h.probe.requests) == 2
    assert h.probe.requests[0].url == "https://id.example.com/login"
    assert h.probe.requests[1].headers["Authorization"] == "Bearer fresh-tok"


async def test_401_triggers_one_refresh_and_one_retry() -> None:
    h = Harness()
    source = await h.custom_source()
    monitor = await h.monitor_for(source)
    h.cache_token(source, token="old-tok")
    h.probe.queue(ProbeResponse(status_code=401, latency_ms=5))  # monitor rejects old token
    h.probe.queue(login('{"access_token":"new-tok","expires_in":3600}'))  # reactive refresh
    h.probe.queue(ProbeResponse(status_code=200, latency_ms=5))  # retry succeeds

    result = await h.service.run_check(monitor.id)

    assert result.success is True
    assert result.status_code == 200
    assert len(h.probe.requests) == 3
    assert h.probe.requests[0].headers["Authorization"] == "Bearer old-tok"
    assert h.probe.requests[1].url == "https://id.example.com/login"
    assert h.probe.requests[2].headers["Authorization"] == "Bearer new-tok"


async def test_persistent_401_is_one_failed_check_no_loop() -> None:
    h = Harness()
    source = await h.custom_source()
    monitor = await h.monitor_for(source)
    h.cache_token(source, token="old-tok")
    h.probe.queue(ProbeResponse(status_code=401, latency_ms=5))
    h.probe.queue(login('{"access_token":"new-tok","expires_in":3600}'))
    h.probe.queue(ProbeResponse(status_code=401, latency_ms=5))  # still 401 after refresh

    result = await h.service.run_check(monitor.id)

    assert result.success is False
    assert result.status_code == 401
    # Exactly one refresh + one retry — no further attempts.
    assert len(h.probe.requests) == 3
    persisted = await h.results.list_for_monitor(monitor.id)
    assert len(persisted) == 1


async def test_oauth_refresh_token_is_reused_before_full_login() -> None:
    h = Harness()
    source = await h.oauth_source()
    monitor = await h.monitor_for(source)
    # Expired access token but a usable refresh token → proactive refresh-token grant.
    h.cache_token(
        source, token="expired", expires_at=NOW - timedelta(minutes=1), refresh_token="r-1"
    )
    h.probe.queue(login('{"access_token":"rt-tok","expires_in":3600}'))
    h.probe.queue(ProbeResponse(status_code=200, latency_ms=5))

    result = await h.service.run_check(monitor.id)

    assert result.success is True
    assert len(h.probe.requests) == 2
    refresh_form = parse_qs(h.probe.requests[0].body or "")
    assert refresh_form["grant_type"] == ["refresh_token"]
    assert refresh_form["refresh_token"] == ["r-1"]
    assert h.probe.requests[1].headers["Authorization"] == "Bearer rt-tok"


async def test_oauth_refresh_token_failure_falls_back_to_full_login() -> None:
    h = Harness()
    source = await h.oauth_source()
    monitor = await h.monitor_for(source)
    h.cache_token(
        source, token="expired", expires_at=NOW - timedelta(minutes=1), refresh_token="stale"
    )
    h.probe.queue(login('{"error":"invalid_grant"}'))  # refresh-token grant fails extraction
    h.probe.queue(login('{"access_token":"cc-tok","expires_in":3600}'))  # client_credentials login
    h.probe.queue(ProbeResponse(status_code=200, latency_ms=5))

    result = await h.service.run_check(monitor.id)

    assert result.success is True
    assert len(h.probe.requests) == 3
    assert parse_qs(h.probe.requests[0].body or "")["grant_type"] == ["refresh_token"]
    assert parse_qs(h.probe.requests[1].body or "")["grant_type"] == ["client_credentials"]
    assert h.probe.requests[2].headers["Authorization"] == "Bearer cc-tok"
