"""Pure state-transition decisions (SPEC §3.8). Folds a `CheckResult` into a
`MonitorState`: it bumps the consecutive-run counters and records `last_check_at`
every check, and flips `status` only after `failure_threshold` /
`recovery_threshold` consecutive outcomes. No I/O and no clock — every timestamp
comes from the result, so the flip timing is fully deterministic and exhaustively
unit-testable (PLAN D4).

`transition_between` reads two states to yield the confirmed `StateTransition`
that S8/S9 turn into a `status_changed` event and (once) an alert. Splitting the
fold (`advance_state`) from the transition read keeps each function
single-purpose and free of duplicated counter logic.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sentinel.domain.entities import CheckResult, MonitorState
from sentinel.domain.value_objects import MonitorStatus, StateTransition


def initial_state(monitor_id: UUID, at: datetime) -> MonitorState:
    """The starting state for a monitor with no checks yet: `unknown` since `at`,
    zero counters, no last check."""
    return MonitorState(monitor_id=monitor_id, since=at)


def advance_state(
    state: MonitorState,
    result: CheckResult,
    *,
    failure_threshold: int,
    recovery_threshold: int,
) -> MonitorState:
    """Return the next state after folding in `result` (SPEC §3.8).

    The consecutive counters and `last_check_at` always update; `status` and
    `since` move only when a threshold is crossed. `since` is set to the result's
    `finished_at` on a flip so it marks when the new status began.
    """
    if result.success:
        successes = state.consecutive_successes + 1
        failures = 0
    else:
        failures = state.consecutive_failures + 1
        successes = 0

    status = state.status
    since = state.since
    if not result.success and failures >= failure_threshold and status is not MonitorStatus.DOWN:
        status = MonitorStatus.DOWN
        since = result.finished_at
    elif result.success and successes >= recovery_threshold and status is not MonitorStatus.UP:
        status = MonitorStatus.UP
        since = result.finished_at

    return replace(
        state,
        status=status,
        since=since,
        consecutive_failures=failures,
        consecutive_successes=successes,
        last_check_at=result.finished_at,
    )


def transition_between(before: MonitorState, after: MonitorState) -> StateTransition | None:
    """The confirmed status change from `before` to `after`, or `None` when the
    status is unchanged. `at` is `after.since` — the moment the flip was confirmed."""
    if before.status is after.status:
        return None
    return StateTransition(
        monitor_id=after.monitor_id,
        from_status=before.status,
        to_status=after.status,
        at=after.since,
    )
