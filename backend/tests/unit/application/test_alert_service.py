"""`AlertService` — the S9.3 use case that turns a confirmed `StateTransition` into
alerts (SPEC §3.7). Exercised with in-memory fakes + `FakeNotifier` (PLAN D4), no
network. Proves: fan-out to enabled channels exactly once, idempotency via the
`NotificationLog`, disabled/suppressed/below-threshold fire nothing, flap damping,
and that a failing channel is recorded `ok=False` without crashing the fan-out.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sentinel.application.alert_service import AlertService
from sentinel.domain.entities import AlertChannel, Monitor
from sentinel.domain.value_objects import (
    AlertPolicy,
    ChannelType,
    ErrorKind,
    MonitorStatus,
    NotifyKind,
    NotifyResult,
    StateTransition,
)
from tests.support.fakes import (
    FakeNotifier,
    FixedClock,
    InMemoryAlertChannelRepository,
    InMemoryNotificationLogRepository,
    InMemoryStateTransitionRepository,
)

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


class Harness:
    def __init__(
        self,
        *,
        policy: AlertPolicy | None = None,
        deep_link_base: str = "",
        webhook: FakeNotifier | None = None,
        telegram: FakeNotifier | None = None,
        register_telegram: bool = True,
    ) -> None:
        self.clock = FixedClock(NOW)
        self.channels = InMemoryAlertChannelRepository()
        self.notifications = InMemoryNotificationLogRepository()
        self.transitions = InMemoryStateTransitionRepository()
        self.webhook = webhook or FakeNotifier()
        self.telegram = telegram or FakeNotifier()
        notifiers = {ChannelType.WEBHOOK: self.webhook}
        if register_telegram:
            notifiers[ChannelType.TELEGRAM] = self.telegram
        self.service = AlertService(
            channels=self.channels,
            notifications=self.notifications,
            transitions=self.transitions,
            notifiers=notifiers,
            clock=self.clock,
            policy=policy,
            deep_link_base=deep_link_base,
        )
        self.monitor = Monitor(name="Prod API", url="https://api.example.com/health")

    async def add_channel(self, **overrides: object) -> AlertChannel:
        params: dict[str, object] = {
            "name": "ops",
            "type": ChannelType.WEBHOOK,
            "config": {"url": "https://hooks.example.com/x"},
            "enabled": True,
        }
        params.update(overrides)
        return await self.channels.add(AlertChannel(**params))  # type: ignore[arg-type]

    def down_transition(self, at: datetime | None = None) -> StateTransition:
        return StateTransition(
            monitor_id=self.monitor.id,
            from_status=MonitorStatus.UP,
            to_status=MonitorStatus.DOWN,
            at=at or NOW,
        )


async def test_confirmed_transition_notifies_each_enabled_channel_exactly_once() -> None:
    h = Harness()
    await h.add_channel(name="wh", type=ChannelType.WEBHOOK, enabled=True)
    await h.add_channel(name="tg", type=ChannelType.TELEGRAM, enabled=True)
    await h.add_channel(name="off", type=ChannelType.WEBHOOK, enabled=False)

    decision = await h.service.on_transition(
        h.monitor, h.down_transition(), last_error=ErrorKind.TIMEOUT
    )

    assert decision.notify is True
    assert decision.kind is NotifyKind.TRANSITION
    assert len(h.webhook.calls) == 1  # only the enabled webhook; the disabled one is skipped
    assert len(h.telegram.calls) == 1
    logs = await h.notifications.list_for_monitor(h.monitor.id)
    assert len(logs) == 2
    assert all(log.ok for log in logs)
    assert {log.transition_to for log in logs} == {MonitorStatus.DOWN}
    assert {log.transition_at for log in logs} == {NOW}


async def test_reinvoking_the_same_transition_does_not_double_fire() -> None:
    h = Harness()
    await h.add_channel(type=ChannelType.WEBHOOK, enabled=True)
    transition = h.down_transition()

    await h.service.on_transition(h.monitor, transition, last_error=ErrorKind.TIMEOUT)
    await h.service.on_transition(h.monitor, transition, last_error=ErrorKind.TIMEOUT)

    assert len(h.webhook.calls) == 1  # exists() guard skips the second attempt
    assert len(await h.notifications.list_for_monitor(h.monitor.id)) == 1


async def test_below_threshold_no_transition_is_a_noop() -> None:
    # AlertService is only ever called with a confirmed transition; guard is in
    # CheckService, but a defensive check keeps a stray None from firing.
    h = Harness()
    await h.add_channel(enabled=True)

    decision = await h.service.maybe_notify(h.monitor, None, last_error=None)

    assert decision is None
    assert h.webhook.calls == []
    assert await h.notifications.list_for_monitor(h.monitor.id) == []


async def test_cooldown_suppresses_a_repeat_alert_and_fires_nothing() -> None:
    h = Harness(policy=AlertPolicy(renotify_after_seconds=3600))
    await h.add_channel(enabled=True)
    # A prior DOWN alert landed 100s ago — inside the 1h cooldown.
    await h.transitions.add(h.down_transition(at=NOW - timedelta(seconds=100)))

    decision = await h.service.on_transition(
        h.monitor, h.down_transition(), last_error=ErrorKind.DNS
    )

    assert decision.notify is False
    assert decision.kind is NotifyKind.SUPPRESSED
    assert h.webhook.calls == []
    assert await h.notifications.list_for_monitor(h.monitor.id) == []


async def test_flap_threshold_crossing_sends_a_single_summary() -> None:
    h = Harness(policy=AlertPolicy(flap_threshold=3, flap_window_seconds=600))
    await h.add_channel(enabled=True)
    # Two prior flips inside the window; this one is the 3rd → flapping summary.
    await h.transitions.add(h.down_transition(at=NOW - timedelta(seconds=30)))
    await h.transitions.add(h.down_transition(at=NOW - timedelta(seconds=15)))

    decision = await h.service.on_transition(
        h.monitor, h.down_transition(), last_error=ErrorKind.CONNECTION
    )

    assert decision.notify is True
    assert decision.kind is NotifyKind.FLAPPING
    assert len(h.webhook.calls) == 1
    assert h.webhook.calls[0][1].kind is NotifyKind.FLAPPING


async def test_above_flap_threshold_suppresses() -> None:
    h = Harness(policy=AlertPolicy(flap_threshold=3, flap_window_seconds=600))
    await h.add_channel(enabled=True)
    for offset in (45, 30, 15):
        await h.transitions.add(h.down_transition(at=NOW - timedelta(seconds=offset)))

    decision = await h.service.on_transition(h.monitor, h.down_transition())

    assert decision.notify is False
    assert decision.kind is NotifyKind.SUPPRESSED
    assert h.webhook.calls == []


async def test_failing_notifier_is_recorded_ok_false_without_stopping_fan_out() -> None:
    h = Harness(
        webhook=FakeNotifier(NotifyResult(ok=False, detail="HTTP 500")),
        telegram=FakeNotifier(NotifyResult(ok=True, detail="HTTP 200")),
    )
    await h.add_channel(name="wh", type=ChannelType.WEBHOOK, enabled=True)
    await h.add_channel(name="tg", type=ChannelType.TELEGRAM, enabled=True)

    await h.service.on_transition(h.monitor, h.down_transition(), last_error=ErrorKind.TLS)

    logs = {
        (log.transition_to, log.ok, log.detail)
        for log in await h.notifications.list_for_monitor(h.monitor.id)
    }
    assert (MonitorStatus.DOWN, False, "HTTP 500") in logs
    assert (MonitorStatus.DOWN, True, "HTTP 200") in logs
    assert len(h.telegram.calls) == 1  # the failing webhook didn't abort the telegram send


async def test_unregistered_channel_type_records_ok_false() -> None:
    h = Harness(register_telegram=False)
    await h.add_channel(name="tg", type=ChannelType.TELEGRAM, enabled=True)

    await h.service.on_transition(h.monitor, h.down_transition())

    logs = await h.notifications.list_for_monitor(h.monitor.id)
    assert len(logs) == 1
    assert logs[0].ok is False
    assert "telegram" in (logs[0].detail or "")


async def test_notification_payload_carries_name_status_since_error_and_deep_link() -> None:
    h = Harness(deep_link_base="https://sentinel.example.com/")
    await h.add_channel(enabled=True)
    transition = h.down_transition()

    await h.service.on_transition(h.monitor, transition, last_error=ErrorKind.TIMEOUT)

    _, notification = h.webhook.calls[0]
    assert notification.monitor_name == "Prod API"
    assert notification.status is MonitorStatus.DOWN
    assert notification.since == transition.at
    assert notification.last_error is ErrorKind.TIMEOUT
    assert notification.deep_link == f"https://sentinel.example.com/monitors/{h.monitor.id}"


async def test_deep_link_is_none_without_a_configured_base() -> None:
    h = Harness(deep_link_base="")
    await h.add_channel(enabled=True)

    await h.service.on_transition(h.monitor, h.down_transition())

    assert h.webhook.calls[0][1].deep_link is None


async def test_every_confirmed_transition_is_recorded_for_flap_history() -> None:
    # Even a suppressed transition must be recorded so it counts toward future flap
    # windows (that's why NotificationLog can't be the flap-history source).
    h = Harness(policy=AlertPolicy(renotify_after_seconds=3600))
    await h.add_channel(enabled=True)
    await h.transitions.add(h.down_transition(at=NOW - timedelta(seconds=100)))

    await h.service.on_transition(h.monitor, h.down_transition(), last_error=ErrorKind.DNS)

    recorded = await h.transitions.list_since(h.monitor.id, since=NOW - timedelta(hours=1))
    assert len(recorded) == 2  # the seeded prior + this (suppressed) one
