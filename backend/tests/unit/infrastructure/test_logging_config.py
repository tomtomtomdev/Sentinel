"""S14.2 — structured JSON logging (SPEC §6). The `JsonLogFormatter` serialises
each `LogRecord` as one line of JSON with a stable field set, merges structured
context passed via `extra=`, serialises exception info as a traceback string (no
frame locals, so no secret bound to a variable can leak), and stamps the
request-scoped correlation id from the contextvar. `configure_logging` installs
it on the root logger once (idempotent)."""

from __future__ import annotations

import json
import logging

from sentinel.infrastructure.logging_config import (
    JsonLogFormatter,
    configure_logging,
    request_id_var,
)


def _record(**kwargs: object) -> logging.LogRecord:
    factory = logging.getLogRecordFactory()
    defaults: dict[str, object] = {
        "name": "sentinel.test",
        "level": logging.INFO,
        "pathname": __file__,
        "lineno": 1,
        "msg": "hello",
        "args": (),
        "exc_info": None,
    }
    defaults.update(kwargs)
    return factory(**defaults)  # type: ignore[arg-type]


def test_format_emits_valid_json_with_core_fields() -> None:
    line = JsonLogFormatter().format(_record())
    payload = json.loads(line)  # must be a single valid JSON object

    assert payload["level"] == "INFO"
    assert payload["logger"] == "sentinel.test"
    assert payload["message"] == "hello"
    assert isinstance(payload["timestamp"], str)


def test_format_merges_extra_structured_fields() -> None:
    record = _record(msg="request completed")
    record.event = "http_request"  # what `extra={...}` attaches to the record
    record.method = "GET"
    record.status = 200

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["event"] == "http_request"
    assert payload["method"] == "GET"
    assert payload["status"] == 200


def test_format_includes_request_id_from_contextvar() -> None:
    token = request_id_var.set("req-abc-123")
    try:
        payload = json.loads(JsonLogFormatter().format(_record()))
    finally:
        request_id_var.reset(token)

    assert payload["request_id"] == "req-abc-123"


def test_format_omits_request_id_when_unset() -> None:
    payload = json.loads(JsonLogFormatter().format(_record()))
    assert "request_id" not in payload


def test_format_serialises_exception_as_traceback_string() -> None:
    try:
        raise RuntimeError("kaboom")
    except RuntimeError:
        import sys

        record = _record(msg="unhandled error", level=logging.ERROR, exc_info=sys.exc_info())

    payload = json.loads(JsonLogFormatter().format(record))

    assert "exc_info" in payload
    assert "RuntimeError: kaboom" in payload["exc_info"]
    assert "Traceback" in payload["exc_info"]


def test_configure_logging_is_idempotent() -> None:
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        root.handlers.clear()
        configure_logging()
        configure_logging()  # second call must not add a duplicate JSON handler
        json_handlers = [h for h in root.handlers if isinstance(h.formatter, JsonLogFormatter)]
        assert len(json_handlers) == 1
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
