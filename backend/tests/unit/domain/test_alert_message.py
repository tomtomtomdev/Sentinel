"""Pure alert-message rendering (SPEC §3.7). `format_alert_message` turns an
`AlertNotification` into the human-readable text used by the telegram/email
notifiers. No I/O; deterministic given its input."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sentinel.domain.logic.notify import format_alert_message
from sentinel.domain.value_objects import (
    AlertNotification,
    ErrorKind,
    MonitorStatus,
    NotifyKind,
)

AT = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


def _notification(**overrides: object) -> AlertNotification:
    params: dict[str, object] = {
        "monitor_id": uuid4(),
        "monitor_name": "Prod API",
        "status": MonitorStatus.DOWN,
        "since": AT,
        "kind": NotifyKind.TRANSITION,
        "last_error": ErrorKind.TIMEOUT,
        "deep_link": "https://sentinel.example.com/monitors/x",
    }
    params.update(overrides)
    return AlertNotification(**params)  # type: ignore[arg-type]


def test_down_transition_message_has_name_status_error_and_link() -> None:
    text = format_alert_message(_notification())
    assert "Prod API" in text
    assert "down" in text.lower()
    assert "timeout" in text
    assert "https://sentinel.example.com/monitors/x" in text


def test_recovery_message_reads_as_up() -> None:
    text = format_alert_message(_notification(status=MonitorStatus.UP, last_error=None))
    assert "up" in text.lower()
    assert "Prod API" in text


def test_flapping_message_is_worded_as_a_summary() -> None:
    text = format_alert_message(_notification(kind=NotifyKind.FLAPPING))
    assert "flapping" in text.lower()


def test_message_omits_error_and_link_when_absent() -> None:
    text = format_alert_message(_notification(last_error=None, deep_link=None))
    assert "Prod API" in text
    assert "http" not in text.lower()
