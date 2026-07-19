"""Minimal static-token auth gate (S9a; sentinel-security §4, PLAN D9) with
brute-force damping (S14.4, PLAN D35).

One FastAPI dependency applied router-wide in `main.py` guards the whole
`/api/v1` surface (the `/health` liveness probe excepted): requests must carry
`Authorization: Bearer <AUTH_TOKEN>`. An empty `AUTH_TOKEN` disables the gate —
a dev-only mode; never expose the API without a token (PLAN §6 warning).

Repeated *failed* attempts from one client IP are throttled to `429` via the
`RateLimiter` seam so a brute-force scan can't hammer the token check; valid
credentials are never throttled (a legitimate user behind a shared IP still gets
through). This same dependency is where richer auth would layer on later.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Request

from sentinel.config import Settings, get_settings
from sentinel.domain.ports import RateLimiter
from sentinel.interface.api.deps import get_rate_limiter


class UnauthorizedError(Exception):
    """Missing or invalid API credentials — mapped to a 401 envelope in errors.py."""


class RateLimitedError(Exception):
    """Too many failed auth attempts from one client — mapped to a 429 envelope."""

    def __init__(self, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _client_key(request: Request) -> str:
    """The rate-limit bucket key: the client's IP. Behind a reverse proxy this is
    the proxy's address unless uvicorn is run with proxy-header support at a
    trusted edge (a deploy concern) — see PROGRESS."""
    client = request.client
    return client.host if client is not None else "unknown"


async def require_auth(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    expected = settings.auth_token
    if not expected:
        return  # gate disabled (AUTH_TOKEN unset — dev mode)
    scheme, _, credential = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() == "bearer" and secrets.compare_digest(
        credential.strip().encode(), expected.encode()
    ):
        return  # valid credentials — never throttled
    # Failed attempt: damp brute force before reporting the 401 (SPEC §6).
    if settings.rate_limit_enabled and not await limiter.allow(_client_key(request)):
        raise RateLimitedError(
            "too many authentication attempts",
            retry_after=settings.rate_limit_window_seconds,
        )
    raise UnauthorizedError("missing or invalid API credentials")
