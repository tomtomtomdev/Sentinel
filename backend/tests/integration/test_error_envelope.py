"""S14.1 — error-envelope consistency pass (SPEC §5). Every error the API can
emit flows through the envelope `{"error": {"code", "message", "details"?}}`:
an unhandled exception becomes a generic `internal_error` 500 that never leaks
its internal detail, an unknown route is `not_found`, and a wrong method is
`method_not_allowed`. The domain-error handlers (S2/S9a) are unaffected."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from sentinel.interface.api.errors import register_exception_handlers
from sentinel.interface.main import app

SECRET_DETAIL = "boom-internal-stacktrace-detail"


def _app_with_raising_route() -> FastAPI:
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/boom")
    async def boom() -> None:
        raise RuntimeError(SECRET_DETAIL)

    return test_app


async def test_unhandled_exception_is_internal_error_envelope_without_leak() -> None:
    # raise_app_exceptions=False so ServerErrorMiddleware's re-raise (for the ASGI
    # server's own logging) doesn't propagate into the test client; we assert on the
    # response the handler produced.
    transport = httpx.ASGITransport(app=_app_with_raising_route(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert isinstance(body["error"]["message"], str)
    # No internal leak: the exception's message must never reach the client.
    assert SECRET_DETAIL not in response.text
    assert "details" not in body["error"]


async def test_unknown_route_is_not_found_envelope() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_method_not_allowed_is_envelope() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete("/api/v1/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
