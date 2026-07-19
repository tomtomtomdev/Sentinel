"""The async scheduler runner (SPEC §3.3, §6) — `python -m sentinel.infrastructure
.scheduler` (or `just worker`).

A thin loop over the pure `select_due_monitors` decision: each cycle it lists
monitors, selects the enabled ones that are due, probes them via the existing
`CheckService` (so auth injection, assertions, and result persistence are all
reused), records each run time as the new last-run, and pings the `Heartbeat`
dead-man's switch. Probes run under a bounded-concurrency semaphore so one hung
endpoint can't starve the rest, and a single failing check is logged and skipped
rather than crashing the cycle.

Schedule state is the per-monitor last-run time. It is held in memory across
cycles and **seeded on startup from the most recent persisted `CheckResult`**, so a
restart resumes the schedule instead of re-probing everything at once (SPEC §6
reliability). Missed ticks are skipped, not backfilled — selection is boolean and
the next run is computed from the actual run time (see `domain.logic.scheduling`).

This module is a second composition root (the worker process); it wires concrete
adapters directly rather than importing the API's `interface` deps, keeping the
dependency rule intact (infrastructure never imports interface)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from datetime import datetime, timedelta
from uuid import UUID

from sentinel.application.alert_service import AlertService
from sentinel.application.auth_token_service import AuthTokenService
from sentinel.application.check_service import CheckService
from sentinel.application.retention_service import RetentionService
from sentinel.config import Settings, get_settings
from sentinel.domain.logic.scheduling import select_due_monitors
from sentinel.domain.ports import (
    CheckResultRepository,
    Clock,
    Heartbeat,
    MonitorRepository,
)
from sentinel.domain.value_objects import AlertPolicy, ChannelType, RetentionPolicy
from sentinel.infrastructure.clock import SystemClock
from sentinel.infrastructure.db.alert_channel_repository import (
    SqlAlertChannelRepository,
    SqlNotificationLogRepository,
)
from sentinel.infrastructure.db.auth_source_repository import SqlAuthSourceRepository
from sentinel.infrastructure.db.check_result_repository import SqlCheckResultRepository
from sentinel.infrastructure.db.check_rollup_repository import SqlCheckRollupRepository
from sentinel.infrastructure.db.engine import create_engine, create_session_factory
from sentinel.infrastructure.db.monitor_repository import SqlMonitorRepository
from sentinel.infrastructure.db.monitor_state_repository import SqlMonitorStateRepository
from sentinel.infrastructure.db.state_transition_repository import SqlStateTransitionRepository
from sentinel.infrastructure.db.token_store import SqlTokenStore
from sentinel.infrastructure.heartbeat import HttpxHeartbeat, NullHeartbeat
from sentinel.infrastructure.logging_config import configure_logging
from sentinel.infrastructure.notifiers import EmailNotifier, TelegramNotifier, WebhookNotifier
from sentinel.infrastructure.probe import HttpxProbe
from sentinel.infrastructure.secrets import FernetSecretBox
from sentinel.infrastructure.url_guard import GuardedHttpProbe, SsrfUrlGuard

logger = logging.getLogger(__name__)

DEFAULT_POLL_SECONDS = 5.0
DEFAULT_MAX_CONCURRENCY = 50
DEFAULT_RETENTION_INTERVAL_SECONDS = 3600.0


class SchedulerRunner:
    def __init__(
        self,
        *,
        monitors: MonitorRepository,
        checks: CheckService,
        results: CheckResultRepository,
        clock: Clock,
        heartbeat: Heartbeat,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        retention: RetentionService | None = None,
        retention_interval_seconds: float = DEFAULT_RETENTION_INTERVAL_SECONDS,
    ) -> None:
        self._monitors = monitors
        self._checks = checks
        self._results = results
        self._clock = clock
        self._heartbeat = heartbeat
        self._max_concurrency = max_concurrency
        self._poll_seconds = poll_seconds
        self._retention = retention
        self._retention_interval = timedelta(seconds=retention_interval_seconds)
        self._last_prune: datetime | None = None
        self._last_run: dict[UUID, datetime] = {}

    async def seed_schedule(self) -> None:
        """Resume the schedule from persisted results so a restart doesn't re-probe
        every monitor at once (SPEC §6). Each monitor's last run is its most recent
        `CheckResult.finished_at`; monitors with no history stay due immediately."""
        for monitor in await self._monitors.list():
            recent = await self._results.list_for_monitor(monitor.id, limit=1)
            if recent:
                self._last_run[monitor.id] = recent[0].finished_at

    async def run_cycle(self) -> int:
        """Probe everything due right now, then beat the heart. Returns how many
        monitors were selected this cycle."""
        now = self._clock.now()
        monitors = await self._monitors.list()
        due = select_due_monitors(monitors, now, self._last_run)
        if due:
            semaphore = asyncio.Semaphore(self._max_concurrency)
            await asyncio.gather(*(self._probe_one(m.id, semaphore) for m in due))
        await self._maybe_prune(now)
        await self._heartbeat.ping()
        return len(due)

    async def _maybe_prune(self, now: datetime) -> None:
        """Run retention pruning at most once per interval (SPEC §6: idempotent
        and scheduled) — cheap no-op on every other cycle. A pruning failure
        (e.g. a DB blip) is logged and retried next interval, never a crashed
        cycle."""
        if self._retention is None:
            return
        if self._last_prune is not None and now - self._last_prune < self._retention_interval:
            return
        self._last_prune = now
        try:
            report = await self._retention.prune()
        except Exception:
            logger.exception("retention pruning failed; retrying next interval")
            return
        logger.info(
            "retention pruned %s results, %s transitions, %s rollups",
            report.results_deleted,
            report.transitions_deleted,
            report.rollups_deleted,
        )

    async def run_forever(self, *, stop: asyncio.Event | None = None) -> None:
        """Seed, then loop `run_cycle` every `poll_seconds` until `stop` is set."""
        stop = stop or asyncio.Event()
        await self.seed_schedule()
        logger.info(
            "scheduler started (poll=%ss, concurrency=%s)",
            self._poll_seconds,
            self._max_concurrency,
        )
        while not stop.is_set():
            await self.run_cycle()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._poll_seconds)
        logger.info("scheduler stopped")

    async def _probe_one(self, monitor_id: UUID, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            try:
                result = await self._checks.run_check(monitor_id)
            except Exception:
                # A single monitor's failure (e.g. deleted mid-cycle) must not abort
                # the cycle; record the attempt time so we don't hot-loop on it.
                logger.exception("scheduled check failed for monitor %s", monitor_id)
                self._last_run[monitor_id] = self._clock.now()
                return
            self._last_run[monitor_id] = result.finished_at


def build_heartbeat(settings: Settings) -> Heartbeat:
    if settings.heartbeat_url:
        return HttpxHeartbeat(settings.heartbeat_url)
    return NullHeartbeat()


def build_runner(settings: Settings) -> SchedulerRunner:
    """Wire the production adapters for the worker process. Mirrors the API
    composition root (`interface/api/deps.py`) but lives in infrastructure so the
    dependency rule holds; keep the two in step if either changes."""
    factory = create_session_factory(create_engine(settings.database_url))
    clock = SystemClock()
    secret_box = FernetSecretBox(settings.secret_key_ring())
    monitors = SqlMonitorRepository(factory, clock=clock, secret_box=secret_box)
    results = SqlCheckResultRepository(factory)
    states = SqlMonitorStateRepository(factory)
    rollups = SqlCheckRollupRepository(factory, clock=clock)
    sources = SqlAuthSourceRepository(factory, clock=clock, secret_box=secret_box)
    tokens = SqlTokenStore(factory, secret_box=secret_box)
    url_guard = SsrfUrlGuard(enabled=settings.ssrf_guard_enabled)
    probe = GuardedHttpProbe(HttpxProbe(), url_guard)
    auth = AuthTokenService(sources=sources, tokens=tokens, probe=probe, clock=clock)
    alerts = AlertService(
        channels=SqlAlertChannelRepository(factory, secret_box=secret_box),
        notifications=SqlNotificationLogRepository(factory),
        transitions=SqlStateTransitionRepository(factory),
        notifiers={
            ChannelType.WEBHOOK: WebhookNotifier(guard=url_guard),
            ChannelType.TELEGRAM: TelegramNotifier(),
            ChannelType.EMAIL: EmailNotifier(),
        },
        clock=clock,
        policy=AlertPolicy(
            flap_threshold=settings.alert_flap_threshold,
            flap_window_seconds=settings.alert_flap_window_seconds,
            renotify_after_seconds=settings.alert_renotify_after_seconds,
        ),
        deep_link_base=settings.dashboard_base_url,
    )
    checks = CheckService(
        monitors=monitors,
        results=results,
        probe=probe,
        clock=clock,
        states=states,
        rollups=rollups,
        alerts=alerts,
        auth_sources=sources,
        auth=auth,
    )
    retention = RetentionService(
        results=results,
        transitions=SqlStateTransitionRepository(factory),
        rollups=rollups,
        clock=clock,
        policy=RetentionPolicy(
            raw_days=settings.retention_raw_days,
            rollup_days=settings.retention_rollup_days,
        ),
    )
    return SchedulerRunner(
        monitors=monitors,
        checks=checks,
        results=results,
        clock=clock,
        heartbeat=build_heartbeat(settings),
        max_concurrency=settings.scheduler_max_concurrency,
        poll_seconds=settings.scheduler_poll_seconds,
        retention=retention,
        retention_interval_seconds=settings.retention_prune_interval_seconds,
    )


async def _serve() -> None:
    runner = build_runner(get_settings())
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # not all platforms support this
            loop.add_signal_handler(sig, stop.set)
    await runner.run_forever(stop=stop)


def main() -> None:
    configure_logging()
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
