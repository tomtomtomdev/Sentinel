"""Maps domain errors and request-validation failures to the SPEC §5 error
envelope: ``{"error": {"code", "message", "details"?}}``. Registered once on the
app so every route reports errors consistently."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from sentinel.domain.errors import NotFoundError, ValidationError
from sentinel.interface.api.auth import UnauthorizedError


def _envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


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
