"""Maps domain errors and request-validation failures to the SPEC §5 error
envelope: ``{"error": {"code", "message", "details"?}}``. Registered once on the
app so every route reports errors consistently."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from sentinel.domain.errors import NotFoundError, ValidationError
from sentinel.interface.api.auth import RateLimitedError, UnauthorizedError

logger = logging.getLogger("sentinel.interface")

# Framework-raised HTTP errors (unknown route, wrong method, …) mapped to a stable
# SPEC §5 error code. Anything unmapped falls back to a generic slug.
_HTTP_ERROR_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    415: "unsupported_media_type",
    429: "rate_limited",
}


def _envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def _log_context(request: Request) -> dict[str, str]:
    # The request-context middleware (S14.2) stashes the correlation id on the
    # scope; by the time this handler runs the logging contextvar is already reset,
    # so read it back here to keep the error log correlated with the access log.
    request_id = getattr(request.state, "request_id", None)
    return {"request_id": request_id} if isinstance(request_id, str) else {}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ValidationError)
    async def _on_validation(_request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content=_envelope("validation_error", str(exc)))

    @app.exception_handler(NotFoundError)
    async def _on_not_found(_request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content=_envelope("not_found", str(exc)))

    @app.exception_handler(UnauthorizedError)
    async def _on_unauthorized(_request: Request, exc: UnauthorizedError) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content=_envelope("unauthorized", str(exc)),
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(RateLimitedError)
    async def _on_rate_limited(_request: Request, exc: RateLimitedError) -> JSONResponse:
        # Brute-force damping on the auth gate (S14.4): too many failed attempts →
        # 429 in the same envelope, with a Retry-After hint when known.
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        return JSONResponse(
            status_code=429,
            content=_envelope("rate_limited", str(exc)),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _on_request_validation(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope(
                "validation_error",
                "request validation failed",
                {"errors": jsonable_encoder(exc.errors())},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _on_http_exception(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Framework-raised errors (unknown route, wrong method, explicit aborts)
        # go through the envelope too — replaces FastAPI's default {"detail": ...}.
        code = _HTTP_ERROR_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code, message),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def _on_unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Last-resort catch-all: never let an unhandled error escape as a raw 500
        # with an internal detail. Log the full exception server-side; return an
        # opaque envelope so no stack trace / message leaks to the client (SPEC §6).
        logger.exception("unhandled error processing request", extra=_log_context(request))
        return JSONResponse(
            status_code=500,
            content=_envelope("internal_error", "an internal error occurred"),
        )
