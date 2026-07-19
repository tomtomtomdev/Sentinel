"""S14.2 — structured request logging (SPEC §6). `RequestContextMiddleware`
assigns each request a correlation id (honouring an inbound `X-Request-ID`,
otherwise a fresh one), echoes it on the response, and emits exactly one
structured JSON access record per request. Secret values (e.g. the bearer token
in the `Authorization` header) never appear in any log line; an unhandled 500
still produces an access record plus the S14.1 catch-all error record, both
carrying the request id, and the error record includes the server-side
traceback."""

from __future__ import annotations

import json
import logging

import httpx
from fastapi import FastAPI

from sentinel.infrastructure.logging_config import JsonLogFormatter
from sentinel.interface.api.errors import register_exception_handlers
from sentinel.interface.api.middleware import RequestContextMiddleware
from sentinel.interface.main import app

SECRET_TOKEN = "super-secret-bearer-token-value"  # noqa: S105 (test fixture)


class _CapturingHandler(logging.Handler):
    """Captures records and their JSON-formatted lines for assertions."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.setFormatter(JsonLogFormatter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))

    def payloads(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.lines]


class _CaptureLogs:
    """Attach a capturing JSON handler to the `sentinel` logger for a test."""

    def __init__(self) -> None:
        self.handler = _CapturingHandler()
        self._logger = logging.getLogger("sentinel")
        self._saved_level = self._logger.level

    def __enter__(self) -> _CapturingHandler:
        self._logger.addHandler(self.handler)
        self._logger.setLevel(logging.INFO)
        return self.handler

    def __exit__(self, *exc: object) -> None:
        self._logger.removeHandler(self.handler)
        self._logger.setLevel(self._saved_level)


def _raising_app() -> FastAPI:
    test_app = FastAPI()
    test_app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(test_app)

    @test_app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("boom-internal-detail")

    return test_app


async def test_request_emits_one_json_access_record() -> None:
    with _CaptureLogs() as logs:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health")

    assert response.status_code == 200
    access = [p for p in logs.payloads() if p.get("event") == "http_request"]
    assert len(access) == 1
    record = access[0]
    assert record["method"] == "GET"
    assert record["path"] == "/api/v1/health"
    assert record["status"] == 200
    assert record["logger"] == "sentinel.access"
    assert "duration_ms" in record
    assert "request_id" in record


async def test_request_id_is_echoed_and_honoured() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # A generated id is returned when none is supplied.
        generated = await client.get("/api/v1/health")
        assert generated.headers.get("x-request-id")

        # An inbound id is honoured and echoed back verbatim.
        with _CaptureLogs() as logs:
            supplied = await client.get("/api/v1/health", headers={"X-Request-ID": "trace-xyz-1"})

    assert supplied.headers["x-request-id"] == "trace-xyz-1"
    access = [p for p in logs.payloads() if p.get("event") == "http_request"]
    assert access[0]["request_id"] == "trace-xyz-1"


async def test_secret_header_value_never_appears_in_logs() -> None:
    with _CaptureLogs() as logs:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/api/v1/health", headers={"Authorization": f"Bearer {SECRET_TOKEN}"})

    assert logs.lines  # something was logged
    assert all(SECRET_TOKEN not in line for line in logs.lines)


async def test_unhandled_error_logs_access_and_traceback_with_request_id() -> None:
    with _CaptureLogs() as logs:
        transport = httpx.ASGITransport(app=_raising_app(), raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/boom", headers={"X-Request-ID": "trace-boom"})

    assert response.status_code == 500
    payloads = logs.payloads()

    access = [p for p in payloads if p.get("event") == "http_request"]
    assert access and access[0]["status"] == 500
    assert access[0]["request_id"] == "trace-boom"

    errors = [p for p in payloads if "exc_info" in p]
    assert errors, "the catch-all handler must log the traceback server-side"
    assert "RuntimeError: boom-internal-detail" in str(errors[0]["exc_info"])
    assert errors[0]["request_id"] == "trace-boom"
