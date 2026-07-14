"""S7.1 — pure state-transition logic (SPEC §3.8). No I/O; every timestamp comes
from the `CheckResult`, so the flip timing is deterministic (PLAN D4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sentinel.domain.entities import CheckResult, MonitorState
from sentinel.domain.logic.state import advance_state, initial_state, transition_between
from sentinel.domain.value_objects import MonitorStatus

MID = uuid4()
T0 = datetime(2026, 6, 27, 12, 0, tzinfo=UTC)


def _result(*, success: bool, at: datetime) -> CheckResult:
    return CheckResult(
        monitor_id=MID,
        started_at=at - timedelta(milliseconds=50),
        finished_at=at,
        success=success,
        status_code=200 if success else 500,
        latency_ms=50,
    )


def test_initial_state_is_unknown_with_zero_counters() -> None:
    state = initial_state(MID, T0)
    assert state.monitor_id == MID
    assert state.status is MonitorStatus.UNKNOWN
    assert state.since == T0
    assert state.consecutive_failures == 0
    assert state.consecutive_successes == 0
    assert state.last_check_at is None


def test_first_failure_with_threshold_1_flips_to_down() -> None:
    before = initial_state(MID, T0)
    result = _result(success=False, at=T0 + timedelta(seconds=1))
    after = advance_state(before, result, failure_threshold=1, recovery_threshold=1)

    assert after.status is MonitorStatus.DOWN
    assert after.consecutive_failures == 1
    assert after.consecutive_successes == 0
    assert after.since == result.finished_at
    assert after.last_check_at == result.finished_at

    transition = transition_between(before, after)
    assert transition is not None
    assert transition.monitor_id == MID
    assert transition.from_status is MonitorStatus.UNKNOWN
    assert transition.to_status is MonitorStatus.DOWN
    assert transition.at == result.finished_at


def test_first_success_with_threshold_1_flips_to_up() -> None:
    before = initial_state(MID, T0)
    result = _result(success=True, at=T0 + timedelta(seconds=1))
    after = advance_state(before, result, failure_threshold=1, recovery_threshold=1)

    assert after.status is MonitorStatus.UP
    transition = transition_between(before, after)
    assert transition is not None
    assert transition.to_status is MonitorStatus.UP


def test_failure_threshold_2_requires_two_consecutive_failures() -> None:
    up = MonitorState(
        monitor_id=MID,
        since=T0,
        status=MonitorStatus.UP,
        consecutive_successes=1,
        last_check_at=T0,
    )
    first = _result(success=False, at=T0 + timedelta(seconds=1))
    after_one = advance_state(up, first, failure_threshold=2, recovery_threshold=1)
    assert after_one.status is MonitorStatus.UP  # not confirmed yet
    assert after_one.consecutive_failures == 1
    assert after_one.since == up.since  # since does not move without a flip
    assert transition_between(up, after_one) is None

    second = _result(success=False, at=T0 + timedelta(seconds=2))
    after_two = advance_state(after_one, second, failure_threshold=2, recovery_threshold=1)
    assert after_two.status is MonitorStatus.DOWN
    assert after_two.consecutive_failures == 2
    transition = transition_between(after_one, after_two)
    assert transition is not None
    assert transition.to_status is MonitorStatus.DOWN
    assert transition.at == second.finished_at


def test_recovery_threshold_2_requires_two_consecutive_successes() -> None:
    down = MonitorState(
        monitor_id=MID,
        since=T0,
        status=MonitorStatus.DOWN,
        consecutive_failures=3,
        last_check_at=T0,
    )
    first = _result(success=True, at=T0 + timedelta(seconds=1))
    after_one = advance_state(down, first, failure_threshold=1, recovery_threshold=2)
    assert after_one.status is MonitorStatus.DOWN
    assert after_one.consecutive_successes == 1
    assert after_one.consecutive_failures == 0
    assert transition_between(down, after_one) is None

    second = _result(success=True, at=T0 + timedelta(seconds=2))
    after_two = advance_state(after_one, second, failure_threshold=1, recovery_threshold=2)
    assert after_two.status is MonitorStatus.UP
    transition = transition_between(after_one, after_two)
    assert transition is not None
    assert transition.to_status is MonitorStatus.UP


def test_success_resets_failure_run_and_failure_resets_success_run() -> None:
    up = MonitorState(
        monitor_id=MID,
        since=T0,
        status=MonitorStatus.UP,
        consecutive_successes=5,
        last_check_at=T0,
    )
    failed = _result(success=False, at=T0 + timedelta(seconds=1))
    after_fail = advance_state(up, failed, failure_threshold=3, recovery_threshold=1)
    assert after_fail.consecutive_successes == 0
    assert after_fail.consecutive_failures == 1

    ok = _result(success=True, at=T0 + timedelta(seconds=2))
    after_ok = advance_state(after_fail, ok, failure_threshold=3, recovery_threshold=1)
    assert after_ok.consecutive_failures == 0
    assert after_ok.consecutive_successes == 1


def test_staying_up_does_not_move_since_or_emit_transition() -> None:
    up = MonitorState(
        monitor_id=MID,
        since=T0,
        status=MonitorStatus.UP,
        consecutive_successes=1,
        last_check_at=T0,
    )
    result = _result(success=True, at=T0 + timedelta(seconds=60))
    after = advance_state(up, result, failure_threshold=1, recovery_threshold=1)
    assert after.status is MonitorStatus.UP
    assert after.since == T0  # unchanged
    assert after.consecutive_successes == 2
    assert after.last_check_at == result.finished_at
    assert transition_between(up, after) is None


def test_transition_between_is_none_when_status_unchanged() -> None:
    state = MonitorState(
        monitor_id=MID,
        since=T0,
        status=MonitorStatus.DOWN,
        consecutive_failures=1,
        last_check_at=T0,
    )
    assert transition_between(state, state) is None
