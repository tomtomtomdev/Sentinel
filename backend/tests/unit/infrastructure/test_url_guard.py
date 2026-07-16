"""The resolve-then-validate `SsrfUrlGuard` and the `GuardedHttpProbe` decorator
(SPEC §6, sentinel-security §3). The resolver is injected so DNS-rebinding — a
public-looking name resolving to a private IP — is tested deterministically with
no network. The decorator turns a blocked URL into `ProbeError(ErrorKind.BLOCKED)`
*before* the inner probe ever sends, so both the monitor probe and the
auth-source login (which share the probe) refuse it."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sentinel.domain.errors import ProbeError
from sentinel.domain.value_objects import ErrorKind, HttpMethod, ProbeRequest, ProbeResponse
from sentinel.infrastructure.url_guard import GuardedHttpProbe, SsrfUrlGuard
from tests.support.fakes import FakeHttpProbe


class RecordingResolver:
    """Scriptable resolver: host → list of IP strings (or an exception)."""

    def __init__(self, answers: dict[str, list[str] | Exception] | None = None) -> None:
        self.answers = answers or {}
        self.calls: list[str] = []

    async def __call__(self, host: str) -> list[str]:
        self.calls.append(host)
        answer = self.answers.get(host, [])
        if isinstance(answer, Exception):
            raise answer
        return answer


class TestSsrfUrlGuard:
    async def test_public_host_passes(self) -> None:
        resolver = RecordingResolver({"api.example.com": ["93.184.216.34"]})
        guard = SsrfUrlGuard(resolver=resolver)
        assert await guard.check("https://api.example.com/health") is None
        assert resolver.calls == ["api.example.com"]

    async def test_dns_rebinding_public_name_to_private_ip_is_blocked(self) -> None:
        resolver = RecordingResolver({"innocent.example.com": ["10.0.0.5"]})
        guard = SsrfUrlGuard(resolver=resolver)
        reason = await guard.check("https://innocent.example.com/")
        assert reason is not None
        assert "private" in reason

    async def test_any_private_ip_among_public_ones_blocks(self) -> None:
        resolver = RecordingResolver({"multi.example.com": ["93.184.216.34", "192.168.0.9"]})
        guard = SsrfUrlGuard(resolver=resolver)
        assert await guard.check("http://multi.example.com/") is not None

    async def test_literal_blocked_ip_needs_no_resolution(self) -> None:
        resolver = RecordingResolver()
        guard = SsrfUrlGuard(resolver=resolver)
        reason = await guard.check("http://169.254.169.254/latest/meta-data/")
        assert reason is not None
        assert "link-local" in reason
        assert resolver.calls == []

    async def test_non_http_scheme_blocks_before_resolution(self) -> None:
        resolver = RecordingResolver()
        guard = SsrfUrlGuard(resolver=resolver)
        assert await guard.check("ftp://example.com/x") is not None
        assert resolver.calls == []

    async def test_disabled_guard_passes_everything_without_resolving(self) -> None:
        resolver = RecordingResolver()
        guard = SsrfUrlGuard(enabled=False, resolver=resolver)
        assert await guard.check("http://127.0.0.1/admin") is None
        assert await guard.check("ftp://example.com/x") is None
        assert resolver.calls == []

    async def test_resolution_failure_passes_so_the_real_send_classifies_dns(self) -> None:
        resolver = RecordingResolver({"gone.example.com": OSError("NXDOMAIN")})
        guard = SsrfUrlGuard(resolver=resolver)
        assert await guard.check("https://gone.example.com/") is None


class TestGuardedHttpProbe:
    def _request(self, url: str) -> ProbeRequest:
        return ProbeRequest(method=HttpMethod.GET, url=url)

    def _response(self) -> ProbeResponse:
        return ProbeResponse(
            status_code=200,
            latency_ms=12,
            headers={},
            body_sample="ok",
            response_size_bytes=2,
            cert_expires_at=datetime(2027, 1, 1, tzinfo=UTC),
        )

    async def test_blocked_url_raises_probe_error_and_never_sends(self) -> None:
        inner = FakeHttpProbe()
        probe = GuardedHttpProbe(inner, SsrfUrlGuard(resolver=RecordingResolver()))

        with pytest.raises(ProbeError) as exc_info:
            await probe.send(
                self._request("http://127.0.0.1/admin"),
                timeout_seconds=5.0,
                follow_redirects=False,
            )

        assert exc_info.value.kind is ErrorKind.BLOCKED
        assert inner.requests == []

    async def test_allowed_url_delegates_to_the_inner_probe(self) -> None:
        inner = FakeHttpProbe(responses=[self._response()])
        resolver = RecordingResolver({"api.example.com": ["93.184.216.34"]})
        probe = GuardedHttpProbe(inner, SsrfUrlGuard(resolver=resolver))

        response = await probe.send(
            self._request("https://api.example.com/health"),
            timeout_seconds=5.0,
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert len(inner.requests) == 1
