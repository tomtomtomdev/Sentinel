"""Request-context middleware (S14.2, SPEC §6). Pure ASGI — it never buffers the
response body, so the S8 SSE stream (`GET /events`) keeps streaming (unlike
Starlette's `BaseHTTPMiddleware`). Per request it: assigns a correlation id
(honouring an inbound `X-Request-ID`, else a fresh one), binds it to the logging
contextvar and stashes it on `scope['state']` so the S14.1 catch-all error
handler can read it after the contextvar is reset, echoes it on the response,
and emits one structured access-log record."""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sentinel.infrastructure.logging_config import request_id_var

_access_logger = logging.getLogger("sentinel.access")

_REQUEST_ID_HEADER = "x-request-id"


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = Headers(scope=scope).get(_REQUEST_ID_HEADER) or uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        seen = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                seen["status"] = message["status"]
                MutableHeaders(scope=message)[_REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # An unhandled error escapes to Starlette's ServerErrorMiddleware; log
            # the access record here (contextvar still bound) then re-raise so the
            # S14.1 catch-all handler still runs.
            _log_access(scope, 500, start)
            raise
        else:
            _log_access(scope, seen["status"], start)
        finally:
            request_id_var.reset(token)


def _log_access(scope: Scope, status: int, start: float) -> None:
    _access_logger.info(
        "request",
        extra={
            "event": "http_request",
            "method": scope.get("method", ""),
            "path": scope.get("path", ""),  # path only — never the query string
            "status": status,
            "duration_ms": round((time.perf_counter() - start) * 1000, 2),
        },
    )
