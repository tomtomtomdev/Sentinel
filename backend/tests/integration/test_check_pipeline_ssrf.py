"""The SSRF guard in the check pipeline (SPEC §6, S10). `CheckService` +
`AuthTokenService` share one guarded probe, so a blocked monitor URL is recorded
as a failed `CheckResult` with `error=blocked` (never an API error / crash) and a
blocked auth-source login lands in `TokenState.last_refresh_error` — while the
toggle (`SSRF_GUARD_ENABLED=false`) restores the old trusting behaviour.
In-memory repos + `FakeHttpProbe` behind `GuardedHttpProbe`; no network (the
blocked URLs are literal IPs, so the guard never needs a resolver)."""

from __future__ import annotations

from datetime import UTC, datetime

from sentinel.application.auth_token_service import AuthTokenService
from sentinel.application.check_service import CheckService
from sentinel.domain.entities import AuthSource, Monitor
from sentinel.domain.value_objects import (
    AuthSourceMode,
    ErrorKind,
    ExtractorKind,
    HttpMethod,
    Injection,
    InjectionTarget,
    ProbeRequest,
    ProbeResponse,
    TokenExtractor,
)
from sentinel.infrastructure.url_guard import GuardedHttpProbe, SsrfUrlGuard
from tests.support.fakes import (
    FakeHttpProbe,
    FixedClock,
    InMemoryAuthSourceRepository,
    InMemoryCheckResultRepository,
    InMemoryMonitorRepository,
    InMemoryTokenStore,
)

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)

METADATA_URL = "http://169.254.169.254/latest/meta-data/"


class Harness:
    def __init__(self, *, guard_enabled: bool = True) -> None:
        self.clock = FixedClock(NOW)
        self.monitors = InMemoryMonitorRepository(clock=self.clock)
        self.results = InMemoryCheckResultRepository()
        self.sources = InMemoryAuthSourceRepository(clock=self.clock)
        self.tokens = InMemoryTokenStore()
        self.inner_probe = FakeHttpProbe()

        async def public_resolver(host: str) -> list[str]:
            return ["93.184.216.34"]

        self.probe = GuardedHttpProbe(
            self.inner_probe, SsrfUrlGuard(enabled=guard_enabled, resolver=public_resolver)
        )
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

    async def add_monitor(self, **overrides: object) -> Monitor:
        params: dict[str, object] = {
            "name": "Metadata snoop",
            "url": METADATA_URL,
            "interval_seconds": 60,
            "timeout_seconds": 5,
        }
        params.update(overrides)
        return await self.monitors.add(Monitor(**params))  # type: ignore[arg-type]

    def ok_response(self) -> ProbeResponse:
        return ProbeResponse(
            status_code=200,
            latency_ms=10,
            headers={},
            body_sample="ok",
            response_size_bytes=2,
            cert_expires_at=None,
        )


async def test_blocked_monitor_url_records_a_failed_check_with_error_blocked() -> None:
    h = Harness()
    monitor = await h.add_monitor()

    result = await h.service.run_check(monitor.id)

    assert result.success is False
    assert result.error is ErrorKind.BLOCKED
    assert result.status_code is None
    assert h.inner_probe.requests == []  # nothing was ever sent
    assert len(await h.results.list_for_monitor(monitor.id)) == 1  # recorded, not raised


async def test_guard_disabled_sends_the_request_unchanged() -> None:
    h = Harness(guard_enabled=False)
    h.inner_probe.queue(h.ok_response())
    monitor = await h.add_monitor()

    result = await h.service.run_check(monitor.id)

    assert result.success is True
    assert result.error is None
    assert len(h.inner_probe.requests) == 1


async def test_blocked_auth_source_login_records_a_refresh_error_not_a_crash() -> None:
    h = Harness()
    source = await h.sources.add(
        AuthSource(
            name="Sneaky IdP",
            mode=AuthSourceMode.CUSTOM,
            request=ProbeRequest(method=HttpMethod.POST, url="http://192.168.0.10/login"),
            extractor=TokenExtractor(kind=ExtractorKind.JSON_PATH, expr="$.access_token"),
            injection=Injection(target=InjectionTarget.HEADER, name="Authorization"),
        )
    )

    state = await h.auth.refresh(source.id)

    assert state.token == ""  # no token was ever obtained
    assert state.last_refresh_error is not None
    assert "blocked" in state.last_refresh_error
    assert h.inner_probe.requests == []
