"""S9.1 — pure notify decision (SPEC §3.7, §7 "Transition/alert" + "Flap
damping"). No I/O; `now` is injected so the cooldown/flap windows are
deterministic (PLAN D4). The decision is a pure function over a confirmed
`StateTransition` plus the monitor's recent prior transitions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sentinel.domain.logic.notify import should_notify
from sentinel.domain.value_objects import (
    AlertPolicy,
    MonitorStatus,
    NotifyKind,
    StateTransition,
)

MID = uuid4()
T0 = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def _t(*, to: MonitorStatus, at: datetime) -> StateTransition:
    """A confirmed transition into `to` (the from-status is the opposite, which is
    all `should_notify` cares about)."""
    frm = MonitorStatus.UP if to is MonitorStatus.DOWN else MonitorStatus.DOWN
    return StateTransition(monitor_id=MID, from_status=frm, to_status=to, at=at)


# --- Transition/alert (SPEC §7) --------------------------------------------


def test_single_confirmed_transition_notifies() -> None:
    # §7 "Transition/alert": a confirmed flip fires exactly one alert. That a
    # *single failure* does NOT flip is a state-machine concern (test_state);
    # should_notify is only reached once a transition is already confirmed.
    decision = should_notify(_t(to=MonitorStatus.DOWN, at=T0), [], AlertPolicy(), T0)
    assert decision.notify is True
    assert decision.kind is NotifyKind.TRANSITION


def test_recovery_transition_notifies() -> None:
    decision = should_notify(_t(to=MonitorStatus.UP, at=T0), [], AlertPolicy(), T0)
    assert decision.notify is True
    assert decision.kind is NotifyKind.TRANSITION


# --- Flap damping (SPEC §3.7, §7) ------------------------------------------


def test_below_flap_threshold_notifies_per_transition() -> None:
    policy = AlertPolicy(flap_threshold=3, flap_window_seconds=300)
    prior = [_t(to=MonitorStatus.DOWN, at=T0)]
    current = _t(to=MonitorStatus.UP, at=T0 + timedelta(seconds=30))
    decision = should_notify(current, prior, policy, current.at)
    assert decision.notify is True
    assert decision.kind is NotifyKind.TRANSITION  # count == 2 < 3


def test_crossing_flap_threshold_sends_one_flapping_summary() -> None:
    policy = AlertPolicy(flap_threshold=3, flap_window_seconds=300)
    prior = [
        _t(to=MonitorStatus.DOWN, at=T0),
        _t(to=MonitorStatus.UP, at=T0 + timedelta(seconds=30)),
    ]
    current = _t(to=MonitorStatus.DOWN, at=T0 + timedelta(seconds=60))
    decision = should_notify(current, prior, policy, current.at)
    assert decision.notify is True
    assert decision.kind is NotifyKind.FLAPPING  # count == 3


def test_above_flap_threshold_is_suppressed() -> None:
    policy = AlertPolicy(flap_threshold=3, flap_window_seconds=300)
    prior = [
        _t(to=MonitorStatus.DOWN, at=T0),
        _t(to=MonitorStatus.UP, at=T0 + timedelta(seconds=30)),
        _t(to=MonitorStatus.DOWN, at=T0 + timedelta(seconds=60)),
    ]
    current = _t(to=MonitorStatus.UP, at=T0 + timedelta(seconds=90))
    decision = should_notify(current, prior, policy, current.at)
    assert decision.notify is False
    assert decision.kind is NotifyKind.SUPPRESSED  # count == 4


def test_resumes_normal_alerts_after_window_clears() -> None:
    policy = AlertPolicy(flap_threshold=3, flap_window_seconds=300)
    prior = [
        _t(to=MonitorStatus.DOWN, at=T0),
        _t(to=MonitorStatus.UP, at=T0 + timedelta(seconds=30)),
        _t(to=MonitorStatus.DOWN, at=T0 + timedelta(seconds=60)),
    ]
    # The monitor stabilizes: the next flip lands long after the window cleared.
    current = _t(to=MonitorStatus.UP, at=T0 + timedelta(seconds=1000))
    decision = should_notify(current, prior, policy, current.at)
    assert decision.notify is True
    assert decision.kind is NotifyKind.TRANSITION  # prior flips aged out → count 1


def test_flap_window_boundary_is_exclusive() -> None:
    policy = AlertPolicy(flap_threshold=2, flap_window_seconds=300)
    # The one prior flip is exactly `flap_window_seconds` before `now` → outside.
    prior = [_t(to=MonitorStatus.DOWN, at=T0)]
    current = _t(to=MonitorStatus.UP, at=T0 + timedelta(seconds=300))
    decision = should_notify(current, prior, policy, current.at)
    assert decision.kind is NotifyKind.TRANSITION  # count 1, not flapping


def test_flap_damping_disabled_when_threshold_below_two() -> None:
    policy = AlertPolicy(flap_threshold=1, flap_window_seconds=300)
    prior = [
        _t(to=MonitorStatus.DOWN if i % 2 == 0 else MonitorStatus.UP, at=T0 + timedelta(seconds=i))
        for i in range(10)
    ]
    current = _t(to=MonitorStatus.DOWN, at=T0 + timedelta(seconds=20))
    decision = should_notify(current, prior, policy, current.at)
    assert decision.notify is True
    assert decision.kind is NotifyKind.TRANSITION  # never flapping when disabled


def test_flapping_takes_precedence_over_cooldown() -> None:
    policy = AlertPolicy(flap_threshold=2, flap_window_seconds=300, renotify_after_seconds=300)
    prior = [_t(to=MonitorStatus.DOWN, at=T0)]
    # A same-status flip inside the cooldown would be suppressed, but the flap
    # threshold is reached first and wins.
    current = _t(to=MonitorStatus.DOWN, at=T0 + timedelta(seconds=50))
    decision = should_notify(current, prior, policy, current.at)
    assert decision.notify is True
    assert decision.kind is NotifyKind.FLAPPING


# --- Re-notify cooldown (SPEC §3.7) ----------------------------------------


def test_cooldown_off_by_default_every_transition_notifies() -> None:
    # renotify_after_seconds defaults to 0 (off) → one alert per transition.
    policy = AlertPolicy(flap_threshold=0)
    prior = [
        _t(to=MonitorStatus.DOWN, at=T0),
        _t(to=MonitorStatus.UP, at=T0 + timedelta(seconds=5)),
    ]
    current = _t(to=MonitorStatus.DOWN, at=T0 + timedelta(seconds=10))
    decision = should_notify(current, prior, policy, current.at)
    assert decision.notify is True
    assert decision.kind is NotifyKind.TRANSITION


def test_cooldown_suppresses_repeat_same_status_alert() -> None:
    policy = AlertPolicy(flap_threshold=0, renotify_after_seconds=300)
    prior = [
        _t(to=MonitorStatus.DOWN, at=T0),
        _t(to=MonitorStatus.UP, at=T0 + timedelta(seconds=30)),
    ]
    # A second down within the cooldown of the prior down is a repeat → suppress.
    current = _t(to=MonitorStatus.DOWN, at=T0 + timedelta(seconds=100))
    decision = should_notify(current, prior, policy, current.at)
    assert decision.notify is False
    assert decision.kind is NotifyKind.SUPPRESSED


def test_cooldown_elapsed_allows_alert() -> None:
    policy = AlertPolicy(flap_threshold=0, renotify_after_seconds=300)
    prior = [_t(to=MonitorStatus.DOWN, at=T0)]
    current = _t(to=MonitorStatus.DOWN, at=T0 + timedelta(seconds=400))
    decision = should_notify(current, prior, policy, current.at)
    assert decision.notify is True
    assert decision.kind is NotifyKind.TRANSITION


def test_cooldown_is_per_status_other_status_still_notifies() -> None:
    policy = AlertPolicy(flap_threshold=0, renotify_after_seconds=300)
    prior = [_t(to=MonitorStatus.DOWN, at=T0)]
    # Recovery is a *different* status than the recent down → not in cooldown.
    current = _t(to=MonitorStatus.UP, at=T0 + timedelta(seconds=100))
    decision = should_notify(current, prior, policy, current.at)
    assert decision.notify is True
    assert decision.kind is NotifyKind.TRANSITION
