from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sentinel.domain.entities import (
    AlertChannel,
    AuthSource,
    CheckResult,
    CheckRollup,
    Monitor,
    MonitorState,
    NotificationLog,
    TokenState,
)
from sentinel.domain.value_objects import (
    AlertNotification,
    Event,
    NotifyResult,
    ProbeRequest,
    ProbeResponse,
    StateTransition,
)


class Clock(Protocol):
    """Source of the current time. Injected so time-dependent behaviour is
    deterministic in tests (PLAN D4)."""

    def now(self) -> datetime: ...


class MonitorRepository(Protocol):
    """Persistence boundary for `Monitor` entities. Implemented in-memory for
    tests and against Postgres in `infrastructure/`."""

    async def add(self, monitor: Monitor) -> Monitor: ...

    async def get(self, monitor_id: UUID) -> Monitor | None: ...

    async def list(self) -> list[Monitor]: ...

    async def update(self, monitor: Monitor) -> Monitor: ...

    async def delete(self, monitor_id: UUID) -> bool: ...


class CheckResultRepository(Protocol):
    """Persistence boundary for `CheckResult`s. `list_for_monitor` returns a
    monitor's checks newest-first, optionally bounded to a `[since, until]`
    window on `finished_at` (both inclusive, both optional) and capped by `limit`
    (`None` = no cap, used to scan a full stats window)."""

    async def add(self, result: CheckResult) -> CheckResult: ...

    async def list_for_monitor(
        self,
        monitor_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = 100,
    ) -> list[CheckResult]: ...

    async def prune_before(self, cutoff: datetime) -> int: ...


class CheckRollupRepository(Protocol):
    """Persistence boundary for hourly `CheckRollup`s (SPEC §3.5, §4, §6). `save` is
    an upsert keyed by `(monitor_id, bucket_start)` — one row per hour — so a
    bucket is recomputed in place as checks land, stamping `updated_at` via the
    injected `Clock`. `list_for_window` returns the monitor's rollups whose
    `bucket_start` falls in `[since, until]` (both inclusive), oldest-first, for
    long-window aggregation."""

    async def get(self, monitor_id: UUID, bucket_start: datetime) -> CheckRollup | None: ...

    async def save(self, rollup: CheckRollup) -> CheckRollup: ...

    async def list_for_window(
        self, monitor_id: UUID, *, since: datetime, until: datetime
    ) -> list[CheckRollup]: ...

    async def prune_before(self, cutoff: datetime) -> int: ...


class MonitorStateRepository(Protocol):
    """Persistence boundary for the per-monitor `MonitorState` rollup (SPEC §3.8,
    §4). `save` is an upsert — one row per monitor — so the state is advanced in
    place as each check lands. `get` returns `None` before a monitor's first check."""

    async def get(self, monitor_id: UUID) -> MonitorState | None: ...

    async def save(self, state: MonitorState) -> MonitorState: ...


class AuthSourceRepository(Protocol):
    """Persistence boundary for `AuthSource` entities (SPEC §3.9). The SQL adapter
    encrypts the request-body credentials, secret request headers, and oauth
    secrets at rest via `SecretBox`; the entity always carries plaintext."""

    async def add(self, auth_source: AuthSource) -> AuthSource: ...

    async def get(self, auth_source_id: UUID) -> AuthSource | None: ...

    async def list(self) -> list[AuthSource]: ...

    async def update(self, auth_source: AuthSource) -> AuthSource: ...

    async def delete(self, auth_source_id: UUID) -> bool: ...


class TokenStore(Protocol):
    """The single cached `TokenState` per auth source (SPEC §3.9). `save` is an
    upsert — one row per source, shared by all linked monitors. The SQL adapter
    encrypts `token`/`refresh_token` at rest via `SecretBox`."""

    async def load(self, auth_source_id: UUID) -> TokenState | None: ...

    async def save(self, token_state: TokenState) -> TokenState: ...


class AlertChannelRepository(Protocol):
    """Persistence boundary for `AlertChannel`s (SPEC §3.7). The SQL adapter
    encrypts secret `config` values at rest via `SecretBox`; the entity always
    carries plaintext. `update` raises `LookupError` on an unknown id (the service
    maps it to `NotFoundError`)."""

    async def add(self, channel: AlertChannel) -> AlertChannel: ...

    async def get(self, channel_id: UUID) -> AlertChannel | None: ...

    async def list(self) -> list[AlertChannel]: ...

    async def update(self, channel: AlertChannel) -> AlertChannel: ...

    async def delete(self, channel_id: UUID) -> bool: ...


class NotificationLogRepository(Protocol):
    """Append-only audit trail + idempotency ledger for fired alerts (SPEC §3.7,
    §4). `exists` answers "has this channel already been notified about this
    transition?" keyed by `(channel_id, monitor_id, transition_at)`, so a confirmed
    transition fires exactly once per channel. `list_for_monitor` returns a
    monitor's log newest-first for audit."""

    async def add(self, entry: NotificationLog) -> NotificationLog: ...

    async def exists(
        self, *, channel_id: UUID, monitor_id: UUID, transition_at: datetime
    ) -> bool: ...

    async def list_for_monitor(
        self, monitor_id: UUID, *, limit: int | None = 100
    ) -> list[NotificationLog]: ...


class StateTransitionRepository(Protocol):
    """Append-only history of confirmed up↔down transitions (SPEC §3.8), the source
    of `recent_transitions` for flap damping (SPEC §3.7). Unlike `NotificationLog`
    (which records only *fired* alerts), this records **every** confirmed flip —
    including ones whose alert was suppressed — so the flap window is accurate.
    `add` appends the just-confirmed transition; `list_since` returns a monitor's
    transitions with `at >= since` (the flap window), oldest-first."""

    async def add(self, transition: StateTransition) -> StateTransition: ...

    async def list_since(self, monitor_id: UUID, *, since: datetime) -> list[StateTransition]: ...

    async def prune_before(self, cutoff: datetime) -> int: ...


class Notifier(Protocol):
    """Delivers one alert to one channel (SPEC §3.7). The `AlertService` selects the
    notifier by `channel.type`, then hands it the channel (whose `config` is already
    decrypted) and the `AlertNotification`. A notifier reads `config` to know where to
    send, classifies the outcome as a `NotifyResult`, and **never raises** — a channel
    outage is recorded as a `NotificationLog` with `ok=False`, it cannot crash the
    check pipeline. Secret `config` values are used only to send and never appear in
    the result detail or any log (SPEC §6)."""

    async def send(
        self, channel: AlertChannel, notification: AlertNotification
    ) -> NotifyResult: ...


class SecretBox(Protocol):
    """Encrypts secret values for storage and decrypts them at the point of use
    (SPEC §6). Key-ring aware so keys rotate without re-encrypting existing
    ciphertext (the `MultiFernet` adapter encrypts with the first key in the ring
    and decrypts with any). The domain only depends on this behaviour, never on
    the crypto library."""

    def encrypt(self, plaintext: str) -> bytes: ...

    def decrypt(self, token: bytes) -> str: ...


class Heartbeat(Protocol):
    """A dead-man's switch: the scheduler pings an external watchdog once per cycle
    (SPEC §6). If the worker dies silently the watchdog stops hearing it and alerts,
    so a crashed runner is never mistaken for "all green". A ping must never raise —
    a watchdog hiccup can't be allowed to crash the runner — and is a no-op when no
    `HEARTBEAT_URL` is configured."""

    async def ping(self) -> None: ...


class EventBus(Protocol):
    """In-process publish/subscribe for live updates (SPEC §3.6). `publish` fans an
    `Event` out to every current subscriber and must never block the caller or raise
    — a slow or vanished SSE client can't be allowed to stall the check pipeline.
    `subscribe` returns an async context manager whose iterator yields events until
    the subscriber's stream closes, then deregisters it. The in-process adapter only
    delivers within one process; cross-process delivery (worker → API clients) is a
    later Redis-backed drop-in behind this port."""

    async def publish(self, event: Event) -> None: ...

    def subscribe(self) -> AbstractAsyncContextManager[AsyncIterator[Event]]: ...


class ReadinessCheck(Protocol):
    """Answers whether the process can serve traffic — i.e. its backing store is
    reachable (SPEC §6). Backs `GET /api/v1/ready`. `check` returns True when the
    dependency responds, False on any failure, and **never raises**: a readiness
    probe that crashes is worse than one that reports "not ready"."""

    async def check(self) -> bool: ...


class HttpProbe(Protocol):
    """Executes one outbound HTTP request and returns a `ProbeResponse`, capturing
    status, latency, a bounded body sample, size, and (on HTTPS) the TLS leaf
    cert's notAfter. The httpx adapter classifies transport failures (DNS,
    connect, TLS, timeout) and raises `ProbeError`; the probe use case records
    those as failed `CheckResult`s — they are never surfaced as API errors
    (SPEC §3.3). The SSRF guard (S10) wraps this before sending."""

    async def send(
        self,
        request: ProbeRequest,
        *,
        timeout_seconds: float,
        follow_redirects: bool,
    ) -> ProbeResponse: ...
