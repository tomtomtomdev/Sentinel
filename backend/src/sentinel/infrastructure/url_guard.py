"""The resolve-then-validate SSRF guard (SPEC §6, S10) and the `HttpProbe`
decorator that applies it. `SsrfUrlGuard.check` first rejects syntactically
forbidden URLs (pure `invalid_url_reason`), then resolves the host and rejects
the URL if **any** resolved IP is in a blocked range (pure `blocked_ip_reason`)
— resolving first is what defeats DNS rebinding, where an innocent-looking name
answers with `127.0.0.1`. The resolver is injectable so tests script it; the
default uses the event loop's `getaddrinfo` (never blocking).

`GuardedHttpProbe` wraps the shared probe, so the monitor probe *and* the
auth-source login are both guarded by one check; the webhook notifier takes the
guard directly. A guard's own resolution failure passes the URL through — the
real send then fails and is classified as `ErrorKind.DNS`, keeping error kinds
honest (a dead name is `dns`, not `blocked`)."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Sequence
from urllib.parse import urlsplit

from sentinel.domain.errors import ProbeError
from sentinel.domain.logic.url_guard import blocked_ip_reason, invalid_url_reason
from sentinel.domain.ports import HttpProbe
from sentinel.domain.value_objects import ErrorKind, ProbeRequest, ProbeResponse

Resolver = Callable[[str], Awaitable[Sequence[str]]]


async def _getaddrinfo_resolver(host: str) -> Sequence[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


class SsrfUrlGuard:
    """Validates one outbound user-supplied URL. `check` returns the block
    reason (secret-free, never the URL/host/IP) or `None` when it may be sent.
    `enabled=False` (`SSRF_GUARD_ENABLED`) turns every check into a pass —
    trusted single-host self-hosting only (SPEC §6)."""

    def __init__(self, *, enabled: bool = True, resolver: Resolver | None = None) -> None:
        self._enabled = enabled
        self._resolver: Resolver = resolver or _getaddrinfo_resolver

    async def check(self, url: str) -> str | None:
        if not self._enabled:
            return None
        reason = invalid_url_reason(url)
        if reason is not None:
            return reason
        host = urlsplit(url).hostname or ""
        if _is_ip_literal(host):
            return blocked_ip_reason(host)
        try:
            ips = await self._resolver(host)
        except OSError:
            return None  # the real send will fail the same way → ErrorKind.DNS
        for ip in ips:
            reason = blocked_ip_reason(ip)
            if reason is not None:
                return reason
        return None


class GuardedHttpProbe:
    """`HttpProbe` decorator: refuse a blocked URL with `ProbeError(BLOCKED)`
    *before* the inner probe opens a connection. The check service records that
    as a failed `CheckResult` and the auth refresh as `last_refresh_error` —
    both callers already treat `ProbeError` as data, never a crash."""

    def __init__(self, inner: HttpProbe, guard: SsrfUrlGuard) -> None:
        self._inner = inner
        self._guard = guard

    async def send(
        self,
        request: ProbeRequest,
        *,
        timeout_seconds: float,
        follow_redirects: bool,
    ) -> ProbeResponse:
        reason = await self._guard.check(request.url)
        if reason is not None:
            raise ProbeError(ErrorKind.BLOCKED, reason)
        return await self._inner.send(
            request, timeout_seconds=timeout_seconds, follow_redirects=follow_redirects
        )
