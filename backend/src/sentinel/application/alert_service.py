"""Alerting use case (SPEC §3.7). Consumes a confirmed `StateTransition` — read
**directly** from the check pipeline, not via the S8 `EventBus` — decides whether to
alert with the pure `should_notify`, and, when it says so, fans the alert out to every
**enabled** channel **exactly once**, sending via the right `Notifier` per
`channel.type` and recording a `NotificationLog` per attempt.

This service holds flow only; the notify/flap/cooldown rules live in the pure
`domain.logic.notify`. It owns the monitor's persisted transition history (SPEC §3.8):
it reads the recent flips inside the flap window to feed `should_notify` and appends
the current one, so flap damping sees **every** confirmed transition — including the
suppressed ones a `NotificationLog` (fired-only) could never provide.

Secrets: channel `config` reaches this layer already decrypted (the repository's
concern); it is used only to send and never lands in a `NotificationLog.detail` or a
log line (SPEC §6)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

from sentinel.domain.entities import AlertChannel, Monitor, NotificationLog
from sentinel.domain.logic.notify import should_notify
from sentinel.domain.ports import (
    AlertChannelRepository,
    Clock,
    NotificationLogRepository,
    Notifier,
    StateTransitionRepository,
)
from sentinel.domain.value_objects import (
    AlertNotification,
    AlertPolicy,
    ChannelType,
    ErrorKind,
    NotifyDecision,
    NotifyResult,
    StateTransition,
)


class AlertService:
    def __init__(
        self,
        *,
        channels: AlertChannelRepository,
        notifications: NotificationLogRepository,
        transitions: StateTransitionRepository,
        notifiers: Mapping[ChannelType, Notifier],
        clock: Clock,
        policy: AlertPolicy | None = None,
        deep_link_base: str = "",
    ) -> None:
        self._channels = channels
        self._notifications = notifications
        self._transitions = transitions
        self._notifiers = notifiers
        self._clock = clock
        self._policy = policy or AlertPolicy()
        self._deep_link_base = deep_link_base

    async def maybe_notify(
        self,
        monitor: Monitor,
        transition: StateTransition | None,
        *,
        last_error: ErrorKind | None = None,
    ) -> NotifyDecision | None:
        """Entry point for the check pipeline: a no-op (returns `None`) when the check
        confirmed no transition, otherwise delegates to `on_transition`."""
        if transition is None:
            return None
        return await self.on_transition(monitor, transition, last_error=last_error)

    async def on_transition(
        self,
        monitor: Monitor,
        transition: StateTransition,
        *,
        last_error: ErrorKind | None = None,
    ) -> NotifyDecision:
        """Record the flip in the transition history, decide via `should_notify`, and
        fan out to enabled channels when it says notify. History is recorded for
        **every** confirmed transition (suppressed included) so future flap windows
        are accurate."""
        now = self._clock.now()
        window_start = now - timedelta(seconds=self._policy.flap_window_seconds)
        prior = await self._transitions.list_since(monitor.id, since=window_start)
        await self._transitions.add(transition)

        decision = should_notify(transition, prior, self._policy, now)
        if not decision.notify:
            return decision

        notification = self._build_notification(monitor, transition, decision, last_error)
        for channel in await self._channels.list():
            if channel.enabled:
                await self._notify_channel(channel, monitor, transition, notification)
        return decision

    async def _notify_channel(
        self,
        channel: AlertChannel,
        monitor: Monitor,
        transition: StateTransition,
        notification: AlertNotification,
    ) -> None:
        """Send to one channel exactly once. Skip if this transition already notified
        this channel (the idempotency guard); otherwise pick the notifier by type,
        send, and record the outcome. An unregistered type is logged `ok=False` rather
        than raising, so a misconfigured channel is auditable, not fatal."""
        if await self._notifications.exists(
            channel_id=channel.id, monitor_id=monitor.id, transition_at=transition.at
        ):
            return
        notifier = self._notifiers.get(channel.type)
        if notifier is None:
            result = NotifyResult(
                ok=False, detail=f"no notifier for channel type {channel.type.value}"
            )
        else:
            result = await notifier.send(channel, notification)
        await self._notifications.add(
            NotificationLog(
                channel_id=channel.id,
                monitor_id=monitor.id,
                transition_to=transition.to_status,
                transition_at=transition.at,
                fired_at=self._clock.now(),
                ok=result.ok,
                detail=result.detail,
            )
        )

    def _build_notification(
        self,
        monitor: Monitor,
        transition: StateTransition,
        decision: NotifyDecision,
        last_error: ErrorKind | None,
    ) -> AlertNotification:
        return AlertNotification(
            monitor_id=monitor.id,
            monitor_name=monitor.name,
            status=transition.to_status,
            since=transition.at,
            kind=decision.kind,
            last_error=last_error,
            deep_link=self._deep_link(monitor),
        )

    def _deep_link(self, monitor: Monitor) -> str | None:
        base = self._deep_link_base.rstrip("/")
        return f"{base}/monitors/{monitor.id}" if base else None
