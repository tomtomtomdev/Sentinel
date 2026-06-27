"""Pure scheduling decisions (SPEC §3.3, §7 "Scheduling"). No I/O, no real clock —
`now` and `last_run` are passed in so selection/jitter are deterministic (PLAN D4).
Acceptance: a monitor is due when ≥ interval has elapsed and **not before**;
disabled monitors are never selected; per-monitor jitter spreads the herd; a gap
(worker down) yields one due check, not a backfilled burst."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sentinel.domain.entities import Monitor
from sentinel.domain.logic.scheduling import (
    jitter_seconds,
    next_run_at,
    select_due_monitors,
)

NOW = datetime(2026, 6, 27, 12, 0, tzinfo=UTC)

# Deterministic ids: int.from_bytes(bytes) == the int, so jitter == int % window.
ID_NO_JITTER = UUID(int=0)  # 0 % window == 0 for any window
ID_JITTER_5 = UUID(int=5)  # 5 % 6 == 5 at interval 60 (window 6)


def make_monitor(
    *, monitor_id: UUID = ID_NO_JITTER, interval: int = 60, enabled: bool = True, name: str = "m"
) -> Monitor:
    return Monitor(
        name=name,
        url="https://api.example.com",
        interval_seconds=interval,
        enabled=enabled,
        id=monitor_id,
    )


# --- jitter ---------------------------------------------------------------


def test_jitter_is_deterministic_for_a_monitor() -> None:
    assert jitter_seconds(ID_JITTER_5, 60) == jitter_seconds(ID_JITTER_5, 60) == 5


def test_jitter_is_within_window_and_non_negative() -> None:
    window = 6  # int(60 * 0.1)
    for i in range(200):
        j = jitter_seconds(UUID(int=i), 60)
        assert 0 <= j < window


def test_jitter_spreads_distinct_monitors() -> None:
    jitters = {jitter_seconds(UUID(int=i), 60) for i in range(50)}
    assert len(jitters) > 1  # not all monitors fire on the same offset


# --- next_run_at ----------------------------------------------------------


def test_next_run_is_last_run_plus_interval_plus_jitter() -> None:
    monitor = make_monitor(monitor_id=ID_JITTER_5, interval=60)
    assert next_run_at(monitor, NOW) == NOW + timedelta(seconds=65)


def test_next_run_with_zero_jitter_is_exactly_one_interval() -> None:
    monitor = make_monitor(monitor_id=ID_NO_JITTER, interval=60)
    assert next_run_at(monitor, NOW) == NOW + timedelta(seconds=60)


# --- select_due_monitors --------------------------------------------------


def test_due_exactly_at_interval_boundary_inclusive() -> None:
    monitor = make_monitor(monitor_id=ID_NO_JITTER, interval=60)
    last_run = {monitor.id: NOW - timedelta(seconds=60)}
    assert select_due_monitors([monitor], NOW, last_run) == [monitor]


def test_not_due_one_second_before_interval() -> None:
    monitor = make_monitor(monitor_id=ID_NO_JITTER, interval=60)
    last_run = {monitor.id: NOW - timedelta(seconds=59)}
    assert select_due_monitors([monitor], NOW, last_run) == []


def test_never_run_monitor_is_due() -> None:
    monitor = make_monitor()
    assert select_due_monitors([monitor], NOW, {}) == [monitor]


def test_disabled_monitor_is_never_selected_even_when_overdue() -> None:
    monitor = make_monitor(enabled=False)
    last_run = {monitor.id: NOW - timedelta(hours=1)}
    assert select_due_monitors([monitor], NOW, last_run) == []


def test_jitter_delays_due_time() -> None:
    monitor = make_monitor(monitor_id=ID_JITTER_5, interval=60)  # +5s jitter
    last_run = {monitor.id: NOW - timedelta(seconds=60)}
    # At NOW (60s elapsed) the +5s jitter means it is not yet due...
    assert select_due_monitors([monitor], NOW, last_run) == []
    # ...but it is due 5s later.
    assert select_due_monitors([monitor], NOW + timedelta(seconds=5), last_run) == [monitor]


def test_gap_yields_a_single_due_check_not_a_backfill() -> None:
    monitor = make_monitor(monitor_id=ID_NO_JITTER, interval=60)
    last_run = {monitor.id: NOW - timedelta(minutes=10)}  # 10 missed ticks
    due = select_due_monitors([monitor], NOW, last_run)
    assert due == [monitor]  # exactly one, not ten


def test_selection_preserves_order_and_filters_mixed_set() -> None:
    due_now = make_monitor(monitor_id=UUID(int=1), name="due", interval=60)
    not_due = make_monitor(monitor_id=UUID(int=2), name="recent", interval=60)
    disabled = make_monitor(monitor_id=UUID(int=3), name="off", enabled=False)
    last_run = {
        due_now.id: NOW - timedelta(seconds=300),
        not_due.id: NOW - timedelta(seconds=1),
        disabled.id: NOW - timedelta(seconds=300),
    }
    assert select_due_monitors([due_now, not_due, disabled], NOW, last_run) == [due_now]
