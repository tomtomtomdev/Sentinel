"""`CheckService.run_check` fires alerts on a confirmed transition (SPEC §3.7, §3.8,
S9.3). Exercised with the in-memory repos + `FakeHttpProbe` + `FakeNotifier` (PLAN
D13) — no DB, no network. Proves alerts fire exactly once per confirmed flip, that a
replayed check (no new transition) doesn't re-alert, that a below-threshold check
fires nothing, and that the pipeline still runs when no alert service is wired."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sentinel.application.alert_service import AlertService
from sentinel.application.check_service import CheckService
from sentinel.domain.entities import AlertChannel, Monitor
from sentinel.domain.value_objects import ChannelType, MonitorStatus, ProbeResponse
from tests.support.fakes import (
    FakeHttpProbe,
    FakeNotifier,
    FixedClock,
    InMemoryAlertChannelRepository,
    InMemoryCheckResultRepository,
    InMemoryMonitorRepository,
    InMemoryMonitorStateRepository,
    InMemoryNotificationLogRepository,
    InMemoryStateTransitionRepository,
)

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


class Harness:
    def __init__(self, *, with_alerts: bool = True) -> None:
        self.clock = FixedClock(NOW)
        self.monitors = InMemoryMonitorRepository(clock=self.clock)
        self.results = InMemoryCheckResultRepository()
        self.states = InMemoryMonitorStateRepository()
        self.channels = InMemoryAlertChannelRepository()
        self.notifications = InMemoryNotificationLogRepository()
        self.transitions = InMemoryStateTransitionRepository()
        self.webhook = FakeNotifier()
        self.probe = FakeHttpProbe()
        alerts = None
        if with_alerts:
            alerts = AlertService(
                channels=self.channels,
                notifications=self.notifications,
                transitions=self.transitions,
                notifiers={ChannelType.WEBHOOK: self.webhook},
                clock=self.clock,
            )
        self.service = CheckService(
            monitors=self.monitors,
            results=self.results,
            probe=self.probe,
            clock=self.clock,
            states=self.states,
            alerts=alerts,
        )

    async def add_monitor(self, **overrides: object) -> Monitor:
        params: dict[str, object] = {
            "name": "Prod health",
            "url": "https://api.example.com/health",
            "interval_seconds": 60,
            "timeout_seconds": 5,
        }
        params.update(overrides)
        return await self.monitors.add(Monitor(**params))  # type: ignore[arg-type]

    async def add_webhook(self) -> AlertChannel:
        return await self.channels.add(
            AlertChannel(
                name="ops", type=ChannelType.WEBHOOK, config={"url": "https://hooks.example.com/x"}
            )
        )


async def test_confirmed_down_then_recovery_each_fire_one_alert() -> None:
    h = Harness()
    await h.add_webhook()
    monitor = await h.add_monitor(failure_threshold=1, recovery_threshold=1)

    h.probe.queue(ProbeResponse(status_code=500, latency_ms=5))
    await h.service.run_check(monitor.id)

    h.clock.set(NOW + timedelta(seconds=60))
    h.probe.queue(ProbeResponse(status_code=200, latency_ms=5))
    await h.service.run_check(monitor.id)

    assert len(h.webhook.calls) == 2
    logs = await h.notifications.list_for_monitor(monitor.id)
    assert {log.transition_to for log in logs} == {MonitorStatus.DOWN, MonitorStatus.UP}
    assert all(log.ok for log in logs)


async def test_replayed_check_without_a_new_transition_does_not_realert() -> None:
    h = Harness()
    await h.add_webhook()
    monitor = await h.add_monitor(failure_threshold=1)

    h.probe.queue(ProbeResponse(status_code=500, latency_ms=5))
    await h.service.run_check(monitor.id)  # confirmed DOWN → 1 alert

    h.clock.set(NOW + timedelta(seconds=60))
    h.probe.queue(ProbeResponse(status_code=500, latency_ms=5))
    await h.service.run_check(monitor.id)  # still DOWN → no transition → no alert

    assert len(h.webhook.calls) == 1
    assert len(await h.notifications.list_for_monitor(monitor.id)) == 1


async def test_below_threshold_check_fires_no_alert() -> None:
    h = Harness()
    await h.add_webhook()
    monitor = await h.add_monitor(failure_threshold=2)

    h.probe.queue(ProbeResponse(status_code=500, latency_ms=5))
    await h.service.run_check(monitor.id)  # 1 failure < threshold → no transition

    assert h.webhook.calls == []
    assert await h.notifications.list_for_monitor(monitor.id) == []


async def test_pipeline_runs_without_an_alert_service() -> None:
    h = Harness(with_alerts=False)
    await h.add_webhook()
    monitor = await h.add_monitor(failure_threshold=1)
    h.probe.queue(ProbeResponse(status_code=500, latency_ms=5))

    result = await h.service.run_check(monitor.id)

    assert result.success is False
    state = await h.states.get(monitor.id)
    assert state is not None and state.status is MonitorStatus.DOWN
    assert await h.notifications.list_for_monitor(monitor.id) == []
