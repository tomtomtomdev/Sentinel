"""The httpx-backed `HttpProbe` adapter — the only place outbound HTTP happens.
Issues one request with a per-request timeout, captures status / latency (measured
with a monotonic clock) / a bounded body sample / size, and on HTTPS reads the TLS
leaf certificate's notAfter. Transport failures are classified into an `ErrorKind`
and raised as `ProbeError` for the use case to record (SPEC §3.3) — they never
propagate as raw httpx errors. The SSRF guard (S10) will wrap this before sending."""

from __future__ import annotations

import socket
import ssl
import time
from datetime import UTC, datetime

import httpx

from sentinel.domain.errors import ProbeError
from sentinel.domain.value_objects import ErrorKind, ProbeRequest, ProbeResponse

# Cap the stored body sample — enough for assertions, never the full large body.
DEFAULT_MAX_BODY_BYTES = 64 * 1024

# OpenSSL/`getpeercert` notAfter format, e.g. 'Jun 26 12:00:00 2027 GMT'.
_OPENSSL_NOT_AFTER_FORMAT = "%b %d %H:%M:%S %Y %Z"


def parse_cert_not_after(value: str) -> datetime:
    """Parse a peer cert's `notAfter` string into a UTC datetime."""
    return datetime.strptime(value, _OPENSSL_NOT_AFTER_FORMAT).replace(tzinfo=UTC)


class HttpxProbe:
    """Holds one shared `AsyncClient` for connection pooling. `send` overrides the
    timeout and redirect policy per request from the monitor's config."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    ) -> None:
        self._client = client or httpx.AsyncClient()
        self._max_body_bytes = max_body_bytes

    async def aclose(self) -> None:
        await self._client.aclose()

    async def send(
        self,
        request: ProbeRequest,
        *,
        timeout_seconds: float,
        follow_redirects: bool,
    ) -> ProbeResponse:
        start = time.perf_counter()
        try:
            response = await self._client.request(
                request.method.value,
                request.url,
                headers=request.headers or None,
                params=request.query_params or None,
                content=request.body,
                timeout=timeout_seconds,
                follow_redirects=follow_redirects,
            )
        except httpx.HTTPError as exc:
            raise ProbeError(_classify(exc), str(exc) or type(exc).__name__) from exc
        latency_ms = int((time.perf_counter() - start) * 1000)

        content = response.content
        sample = content[: self._max_body_bytes].decode(
            response.encoding or "utf-8", errors="replace"
        )
        return ProbeResponse(
            status_code=response.status_code,
            latency_ms=latency_ms,
            headers=dict(response.headers),
            body_sample=sample,
            response_size_bytes=len(content),
            cert_expires_at=_capture_cert_expiry(response),
        )


def _classify(exc: Exception) -> ErrorKind:
    """Map an httpx transport error to an `ErrorKind`. Timeouts win first; a DNS
    failure shows up as a `socket.gaierror` cause, TLS as an `ssl.SSLError`."""
    if isinstance(exc, httpx.TimeoutException):
        return ErrorKind.TIMEOUT
    cause = exc.__cause__
    if isinstance(exc, ssl.SSLError) or isinstance(cause, ssl.SSLError):
        return ErrorKind.TLS
    if isinstance(cause, socket.gaierror):
        return ErrorKind.DNS
    if isinstance(exc, httpx.ConnectError):
        return ErrorKind.CONNECTION
    return ErrorKind.UNKNOWN


def _capture_cert_expiry(response: httpx.Response) -> datetime | None:
    """Read the TLS leaf certificate's notAfter from the response's network stream.
    Returns None for plain HTTP or if the cert can't be read — never raises."""
    if response.url.scheme != "https":
        return None
    try:
        stream = response.extensions.get("network_stream")
        ssl_object = stream.get_extra_info("ssl_object") if stream is not None else None
        cert = ssl_object.getpeercert() if ssl_object is not None else None
        not_after = cert.get("notAfter") if cert else None
        if not not_after:
            return None
        return parse_cert_not_after(not_after)
    except Exception:
        return None
