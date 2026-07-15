"""The SSE frame serializer renders a domain `Event` to the exact `event:`/`data:`
wire shapes in SPEC §5. Pure function, no I/O."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sentinel.domain.value_objects import CheckCompleted, ErrorKind, MonitorStatus, StateTransition
from sentinel.interface.api.events import to_sse_frame

AT = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def _parse(frame: str) -> tuple[str, dict]:
    """Split an SSE frame into (event-name, parsed-data)."""
    assert frame.endswith("\n\n")  # blank line terminates the event
    name = ""
    data: dict = {}
    for line in frame.rstrip("\n").splitlines():
        field, _, value = line.partition(":")
        if field == "event":
            name = value.strip()
        elif field == "data":
            data = json.loads(value.strip())
    return name, data


def test_status_changed_frame_matches_spec_shape() -> None:
    monitor_id = uuid4()
    event = StateTransition(
        monitor_id=monitor_id,
        from_status=MonitorStatus.UP,
        to_status=MonitorStatus.DOWN,
        at=AT,
    )

    name, data = _parse(to_sse_frame(event))

    assert name == "status_changed"
    assert data == {
        "monitor_id": str(monitor_id),
        "from": "up",
        "to": "down",
        "at": "2026-07-14T12:00:00Z",
    }


def test_check_completed_frame_carries_a_secret_free_summary() -> None:
    monitor_id = uuid4()
    event = CheckCompleted(
        monitor_id=monitor_id,
        at=AT,
        success=True,
        status_code=200,
        latency_ms=42,
        error=None,
    )

    name, data = _parse(to_sse_frame(event))

    assert name == "check_completed"
    assert data == {
        "monitor_id": str(monitor_id),
        "success": True,
        "status_code": 200,
        "latency_ms": 42,
        "error": None,
        "at": "2026-07-14T12:00:00Z",
    }


def test_check_completed_frame_renders_transport_failure() -> None:
    event = CheckCompleted(
        monitor_id=uuid4(),
        at=AT,
        success=False,
        status_code=None,
        latency_ms=None,
        error=ErrorKind.TIMEOUT,
    )

    name, data = _parse(to_sse_frame(event))

    assert name == "check_completed"
    assert data["success"] is False
    assert data["status_code"] is None
    assert data["latency_ms"] is None
    assert data["error"] == "timeout"
