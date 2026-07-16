"""Pure notify decision (SPEC §3.7). Given a confirmed `StateTransition`, the
monitor's recent prior transitions, an `AlertPolicy`, and `now`, decide whether to
alert and with which message — flap damping and re-notify cooldown, with no I/O and
no clock (PLAN D4). The application layer (S9.3) owns loading the history, fanning
the decision out to enabled channels, and idempotent logging.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from sentinel.domain.value_objects import (
    AlertNotification,
    AlertPolicy,
    MonitorStatus,
    NotifyDecision,
    NotifyKind,
    StateTransition,
)

MIN_FLAP_THRESHOLD = 2


def should_notify(
    transition: StateTransition,
    recent_transitions: Sequence[StateTransition],
    policy: AlertPolicy,
    now: datetime,
) -> NotifyDecision:
    """Decide whether `transition` should raise an alert (SPEC §3.7).

    `recent_transitions` are the monitor's *prior* confirmed transitions (this one
    is not included). Flap damping wins over cooldown. Counting `transition` plus
    the prior transitions still inside `flap_window_seconds`: the flip that first
    reaches `flap_threshold` sends one `flapping` summary, and any further flip
    while the count stays above the threshold is suppressed — so a thrashing monitor
    produces a single summary, not a storm. Once old transitions age out of the
    window the count drops and normal `transition` alerts resume.

    Re-notify cooldown (when `renotify_after_seconds > 0`) then suppresses a repeat
    alert for the *same* `to_status` if a prior transition to that status landed
    within the cooldown; with the default (0) every confirmed transition alerts
    exactly once.
    """
    if policy.flap_threshold >= MIN_FLAP_THRESHOLD:
        window_start = now - timedelta(seconds=policy.flap_window_seconds)
        count = sum(1 for t in recent_transitions if t.at > window_start) + 1
        if count == policy.flap_threshold:
            return NotifyDecision(
                notify=True,
                kind=NotifyKind.FLAPPING,
                reason=f"{count} transitions within {policy.flap_window_seconds}s — flapping",
            )
        if count > policy.flap_threshold:
            return NotifyDecision(
                notify=False,
                kind=NotifyKind.SUPPRESSED,
                reason="flapping; per-transition alerts suppressed",
            )

    if policy.renotify_after_seconds > 0:
        cutoff = now - timedelta(seconds=policy.renotify_after_seconds)
        if any(t.to_status is transition.to_status and t.at > cutoff for t in recent_transitions):
            return NotifyDecision(
                notify=False,
                kind=NotifyKind.SUPPRESSED,
                reason=f"within {policy.renotify_after_seconds}s re-notify cooldown",
            )

    return NotifyDecision(notify=True, kind=NotifyKind.TRANSITION, reason="confirmed transition")


def format_alert_message(notification: AlertNotification) -> str:
    """Render an `AlertNotification` as human-readable text for the telegram/email
    notifiers (SPEC §3.7). Pure — the webhook notifier instead sends the structured
    fields as JSON. Carries only the secret-free payload fields, never a config value."""
    n = notification
    if n.kind is NotifyKind.FLAPPING:
        headline = f"⚠️ {n.monitor_name} is flapping"
    elif n.status is MonitorStatus.UP:
        headline = f"✅ {n.monitor_name} recovered (up)"
    else:
        headline = f"🔴 {n.monitor_name} is {n.status.value}"
    lines = [headline, f"since {n.since.isoformat()}"]
    if n.last_error is not None:
        lines.append(f"error: {n.last_error.value}")
    if n.deep_link:
        lines.append(n.deep_link)
    return "\n".join(lines)
