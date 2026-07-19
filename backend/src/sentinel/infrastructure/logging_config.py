"""Structured JSON logging (SPEC §6). One formatter serialises every stdlib
`LogRecord` as a single JSON line with a stable field set; `configure_logging`
installs it on the root logger for the real process entrypoints (the API app
and the scheduler worker). A `request_id_var` contextvar carries the request-
scoped correlation id so any log emitted while handling a request — including
the S14.1 catch-all error log — is stamped with it.

Secret safety (SPEC §6 hard rule): the formatter never renders frame locals.
Exception info is serialised via stdlib `traceback` (source lines + the
exception's own message only), so a secret bound to a local variable cannot leak
through a traceback. Callers are still responsible for never passing a secret
value as a log message or `extra` field."""

from __future__ import annotations

import datetime as dt
import json
import logging
from contextvars import ContextVar
from typing import Any

# Bound by the API request middleware; read by the formatter. Default None so
# logs outside a request (worker cycles, startup) simply omit the field.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes present on a vanilla LogRecord. Anything else on a record's __dict__
# arrived via `logger.log(..., extra={...})` and is treated as structured context.
_RESERVED: frozenset[str] = frozenset(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
}


class JsonLogFormatter(logging.Formatter):
    """Render a `LogRecord` as one line of JSON (see module docstring)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": dt.datetime.fromtimestamp(record.created, tz=dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = request_id_var.get()
        if request_id is not None:
            payload["request_id"] = request_id

        # Merge structured context supplied via `extra=` (skips private keys).
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    """Install the JSON formatter on the root logger. Idempotent: safe to call
    from both process entrypoints and safe if some other handler (e.g. pytest's
    log capture) is already attached — it adds our handler only once and leaves
    any others in place."""
    root = logging.getLogger()
    if any(isinstance(handler.formatter, JsonLogFormatter) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root.addHandler(handler)
    root.setLevel(level)
