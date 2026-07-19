"""Dependency wiring (composition root for the API). Concrete adapters are
constructed here and injected into use cases; routers depend only on the use
cases. Tests override `get_monitor_service` with a fake-backed service, so the
real engine is never created in the suite."""

from __future__ import annotations

from functools import lru_cache

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinel.application.alert_channel_service import AlertChannelService
from sentinel.application.alert_service import AlertService
from sentinel.application.auth_source_service import AuthSourceService
from sentinel.application.auth_token_service import AuthTokenService
from sentinel.application.check_service import CheckService
from sentinel.application.monitor_service import MonitorService
from sentinel.application.stats_service import StatsService
from sentinel.config import get_settings
from sentinel.domain.logic.rate_limit import RateLimitConfig
from sentinel.domain.ports import (
    AlertChannelRepository,
    AuthSourceRepository,
    Clock,
    EventBus,
    HttpProbe,
    NotificationLogRepository,
    Notifier,
    RateLimiter,
    ReadinessCheck,
    SecretBox,
    StateTransitionRepository,
    TokenStore,
)
from sentinel.domain.value_objects import AlertPolicy, ChannelType
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
from sentinel.infrastructure.db.readiness import DbReadinessCheck
from sentinel.infrastructure.db.state_transition_repository import SqlStateTransitionRepository
from sentinel.infrastructure.db.token_store import SqlTokenStore
from sentinel.infrastructure.events import InProcessEventBus
from sentinel.infrastructure.notifiers import EmailNotifier, TelegramNotifier, WebhookNotifier
from sentinel.infrastructure.probe import HttpxProbe
from sentinel.infrastructure.rate_limit import InProcessRateLimiter
from sentinel.infrastructure.secrets import FernetSecretBox
from sentinel.infrastructure.url_guard import GuardedHttpProbe, SsrfUrlGuard


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_engine(get_settings().database_url)
    return create_session_factory(engine)


def get_clock() -> Clock:
    return SystemClock()


def get_readiness_check() -> ReadinessCheck:
    """DB-backed readiness for `GET /api/v1/ready` (SPEC §6). Reuses the shared
    session factory so the probe hits the same engine the app serves from."""
    return DbReadinessCheck(get_session_factory())


def build_rate_limiter() -> RateLimiter:
    """Construct the auth-gate brute-force limiter (S14.4). Called once per app in
    `create_app`; the instance is kept on `app.state` so each running app has
    isolated per-IP bucket state (and each test app starts fresh)."""
    settings = get_settings()
    return InProcessRateLimiter(
        clock=get_clock(),
        config=RateLimitConfig.per_window(
            max_events=settings.rate_limit_max_failures,
            window_seconds=settings.rate_limit_window_seconds,
        ),
    )


def get_rate_limiter(request: Request) -> RateLimiter:
    """The app-scoped rate limiter, read from `app.state` (populated by
    `create_app`). This is the override seam for `require_auth`; a Redis-backed
    limiter would drop in behind the same `RateLimiter` port."""
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


@lru_cache
def get_secret_box() -> SecretBox:
    """The process-wide `SecretBox` for at-rest encryption. Built lazily from the
    `SECRET_KEY` key ring so importing the app needs no key; constructing it with an
    empty ring fails fast with a clear message (see `.env.example`)."""
    return FernetSecretBox(get_settings().secret_key_ring())


def get_auth_source_repository() -> AuthSourceRepository:
    return SqlAuthSourceRepository(
        get_session_factory(), clock=get_clock(), secret_box=get_secret_box()
    )


def get_token_store() -> TokenStore:
    return SqlTokenStore(get_session_factory(), secret_box=get_secret_box())


def get_monitor_service() -> MonitorService:
    repository = SqlMonitorRepository(
        get_session_factory(), clock=get_clock(), secret_box=get_secret_box()
    )
    return MonitorService(repository, auth_sources=get_auth_source_repository())


def get_auth_source_service() -> AuthSourceService:
    return AuthSourceService(get_auth_source_repository())


def get_alert_channel_repository() -> AlertChannelRepository:
    return SqlAlertChannelRepository(get_session_factory(), secret_box=get_secret_box())


def get_alert_channel_service() -> AlertChannelService:
    return AlertChannelService(get_alert_channel_repository())


def get_notification_log_repository() -> NotificationLogRepository:
    return SqlNotificationLogRepository(get_session_factory())


def get_state_transition_repository() -> StateTransitionRepository:
    return SqlStateTransitionRepository(get_session_factory())


@lru_cache
def get_url_guard() -> SsrfUrlGuard:
    """The process-wide SSRF guard (SPEC §6) applied to every outbound
    user-supplied URL: monitor probes, auth-source logins, webhook channels."""
    return SsrfUrlGuard(enabled=get_settings().ssrf_guard_enabled)


@lru_cache
def get_notifiers() -> dict[ChannelType, Notifier]:
    """The channel-type → `Notifier` map (SPEC §3.7). One instance per process; each
    notifier opens its own short-lived HTTP client per send. Email is a parked stub.
    The webhook's user-supplied URL is SSRF-guarded; Telegram's host is fixed."""
    return {
        ChannelType.WEBHOOK: WebhookNotifier(guard=get_url_guard()),
        ChannelType.TELEGRAM: TelegramNotifier(),
        ChannelType.EMAIL: EmailNotifier(),
    }


def get_alert_service() -> AlertService:
    settings = get_settings()
    return AlertService(
        channels=get_alert_channel_repository(),
        notifications=get_notification_log_repository(),
        transitions=get_state_transition_repository(),
        notifiers=get_notifiers(),
        clock=get_clock(),
        policy=AlertPolicy(
            flap_threshold=settings.alert_flap_threshold,
            flap_window_seconds=settings.alert_flap_window_seconds,
            renotify_after_seconds=settings.alert_renotify_after_seconds,
        ),
        deep_link_base=settings.dashboard_base_url,
    )


def get_auth_token_service() -> AuthTokenService:
    return AuthTokenService(
        sources=get_auth_source_repository(),
        tokens=get_token_store(),
        probe=get_http_probe(),
        clock=get_clock(),
    )


@lru_cache
def get_http_probe() -> HttpProbe:
    """One shared probe (and its pooled `AsyncClient`) for the process, wrapped in
    the SSRF guard so monitor probes and auth-source logins both validate their
    URL before sending (SPEC §6). Built lazily so importing the app opens no
    client; the event loop binds on first use."""
    return GuardedHttpProbe(HttpxProbe(), get_url_guard())


@lru_cache
def get_event_bus() -> EventBus:
    """The process-wide in-memory event bus for SSE live updates (SPEC §3.6). One
    instance so the API's check pipeline and every `GET /events` stream share
    subscribers. Cross-process delivery (worker → API) would swap in a Redis-backed
    adapter behind the same port (see PROGRESS)."""
    return InProcessEventBus()


def get_stats_service() -> StatsService:
    factory = get_session_factory()
    clock = get_clock()
    return StatsService(
        monitors=SqlMonitorRepository(factory, clock=clock, secret_box=get_secret_box()),
        results=SqlCheckResultRepository(factory),
        states=SqlMonitorStateRepository(factory),
        rollups=SqlCheckRollupRepository(factory, clock=clock),
        clock=clock,
    )


def get_check_service() -> CheckService:
    factory = get_session_factory()
    clock = get_clock()
    return CheckService(
        monitors=SqlMonitorRepository(factory, clock=clock, secret_box=get_secret_box()),
        results=SqlCheckResultRepository(factory),
        probe=get_http_probe(),
        clock=clock,
        states=SqlMonitorStateRepository(factory),
        rollups=SqlCheckRollupRepository(factory, clock=clock),
        events=get_event_bus(),
        alerts=get_alert_service(),
        auth_sources=get_auth_source_repository(),
        auth=get_auth_token_service(),
    )
