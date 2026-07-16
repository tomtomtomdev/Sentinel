"""Minimal static-token auth gate (S9a; sentinel-security §4, PLAN D9).

One FastAPI dependency applied router-wide in `main.py` guards the whole
`/api/v1` surface (the `/health` liveness probe excepted): requests must carry
`Authorization: Bearer <AUTH_TOKEN>`. An empty `AUTH_TOKEN` disables the gate —
a dev-only mode; never expose the API without a token (PLAN §6 warning). S14
layers rate limiting / richer auth on top of this same dependency seam.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Request

from sentinel.config import Settings, get_settings


class UnauthorizedError(Exception):
    """Missing or invalid API credentials — mapped to a 401 envelope in errors.py."""


async def require_auth(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    expected = settings.auth_token
    if not expected:
        return  # gate disabled (AUTH_TOKEN unset — dev mode)
    scheme, _, credential = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(
        credential.strip().encode(), expected.encode()
    ):
        raise UnauthorizedError("missing or invalid API credentials")
