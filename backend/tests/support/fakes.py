"""In-memory test doubles for the domain ports. Behaviour mirrors the real
adapters so the same contract test can run against either (PLAN D4)."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime
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
from sentinel.domain.ports import Clock
from sentinel.domain.value_objects import (
    AlertNotification,
    Event,
    NotifyResult,
    ProbeRequest,
    ProbeResponse,
    StateTransition,
)


class FixedClock:
    """A `Clock` that returns a controllable, non-advancing time."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now


class InMemoryMonitorRepository:
    """`MonitorRepository` backed by a dict. Stamps timestamps via the injected
    clock, exactly as the SQL adapter does."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._store: dict[UUID, Monitor] = {}

    async def add(self, monitor: Monitor) -> Monitor:
        now = self._clock.now()
        stored = copy.deepcopy(monitor)
        stored.created_at = monitor.created_at or now
        stored.updated_at = now
        self._store[stored.id] = stored
        return copy.deepcopy(stored)

    async def get(self, monitor_id: UUID) -> Monitor | None:
        found = self._store.get(monitor_id)
        return copy.deepcopy(found) if found is not None else None

    async def list(self) -> list[Monitor]:
        return [copy.deepcopy(m) for m in self._store.values()]

    async def update(self, monitor: Monitor) -> Monitor:
        existing = self._store.get(monitor.id)
        if existing is None:
            raise LookupError(monitor.id)
        stored = copy.deepcopy(monitor)
        stored.created_at = existing.created_at
        stored.updated_at = self._clock.now()
        self._store[monitor.id] = stored
        return copy.deepcopy(stored)

    async def delete(self, monitor_id: UUID) -> bool:
        return self._store.pop(monitor_id, None) is not None


class InMemoryCheckResultRepository:
    """`CheckResultRepository` backed by a list. `list_for_monitor` returns the
    monitor's results newest-first, mirroring the SQL adapter."""

    def __init__(self) -> None:
        self._store: list[CheckResult] = []

    async def add(self, result: CheckResult) -> CheckResult:
        stored = copy.deepcopy(result)
        self._store.append(stored)
        return copy.deepcopy(stored)

    async def list_for_monitor(
        self,
        monitor_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = 100,
    ) -> list[CheckResult]:
        matches = [
            r
            for r in self._store
            if r.monitor_id == monitor_id
            and (since is None or r.finished_at >= since)
            and (until is None or r.finished_at <= until)
        ]
        matches.sort(key=lambda r: r.finished_at, reverse=True)
        return [copy.deepcopy(r) for r in matches[:limit]]


class InMemoryMonitorStateRepository:
    """`MonitorStateRepository` backed by a dict — one `MonitorState` per monitor.
    `save` upserts, mirroring the SQL adapter."""

    def __init__(self) -> None:
        self._store: dict[UUID, MonitorState] = {}

    async def get(self, monitor_id: UUID) -> MonitorState | None:
        found = self._store.get(monitor_id)
        return copy.deepcopy(found) if found is not None else None

    async def save(self, state: MonitorState) -> MonitorState:
        self._store[state.monitor_id] = copy.deepcopy(state)
        return copy.deepcopy(state)


class InMemoryCheckRollupRepository:
    """`CheckRollupRepository` backed by a dict keyed by `(monitor_id,
    bucket_start)`. `save` upserts and stamps `updated_at` via the injected clock,
    mirroring the SQL adapter (D10)."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._store: dict[tuple[UUID, datetime], CheckRollup] = {}

    async def get(self, monitor_id: UUID, bucket_start: datetime) -> CheckRollup | None:
        found = self._store.get((monitor_id, bucket_start))
        return copy.deepcopy(found) if found is not None else None

    async def save(self, rollup: CheckRollup) -> CheckRollup:
        stamped = replace(rollup, updated_at=self._clock.now())
        self._store[(rollup.monitor_id, rollup.bucket_start)] = copy.deepcopy(stamped)
        return copy.deepcopy(stamped)

    async def list_for_window(
        self, monitor_id: UUID, *, since: datetime, until: datetime
    ) -> list[CheckRollup]:
        matches = [
            r
            for (mid, bucket), r in self._store.items()
            if mid == monitor_id and since <= bucket <= until
        ]
        matches.sort(key=lambda r: r.bucket_start)
        return [copy.deepcopy(r) for r in matches]


class InMemoryAuthSourceRepository:
    """`AuthSourceRepository` backed by a dict. Stamps timestamps via the injected
    clock, exactly as the SQL adapter does. Stores plaintext (the SQL adapter's
    at-rest encryption is an infrastructure concern, transparent to callers)."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._store: dict[UUID, AuthSource] = {}

    async def add(self, auth_source: AuthSource) -> AuthSource:
        now = self._clock.now()
        stored = copy.deepcopy(auth_source)
        stored.created_at = auth_source.created_at or now
        stored.updated_at = now
        self._store[stored.id] = stored
        return copy.deepcopy(stored)

    async def get(self, auth_source_id: UUID) -> AuthSource | None:
        found = self._store.get(auth_source_id)
        return copy.deepcopy(found) if found is not None else None

    async def list(self) -> list[AuthSource]:
        return [copy.deepcopy(s) for s in self._store.values()]

    async def update(self, auth_source: AuthSource) -> AuthSource:
        existing = self._store.get(auth_source.id)
        if existing is None:
            raise LookupError(auth_source.id)
        stored = copy.deepcopy(auth_source)
        stored.created_at = existing.created_at
        stored.updated_at = self._clock.now()
        self._store[auth_source.id] = stored
        return copy.deepcopy(stored)

    async def delete(self, auth_source_id: UUID) -> bool:
        return self._store.pop(auth_source_id, None) is not None


class InMemoryTokenStore:
    """`TokenStore` backed by a dict — one cached `TokenState` per auth source.
    `save` upserts, mirroring the SQL adapter."""

    def __init__(self) -> None:
        self._store: dict[UUID, TokenState] = {}

    async def load(self, auth_source_id: UUID) -> TokenState | None:
        found = self._store.get(auth_source_id)
        return copy.deepcopy(found) if found is not None else None

    async def save(self, token_state: TokenState) -> TokenState:
        self._store[token_state.auth_source_id] = copy.deepcopy(token_state)
        return copy.deepcopy(token_state)


class InMemoryAlertChannelRepository:
    """`AlertChannelRepository` backed by a dict. Stores plaintext (the SQL
    adapter's at-rest encryption is an infrastructure concern, transparent to
    callers)."""

    def __init__(self) -> None:
        self._store: dict[UUID, AlertChannel] = {}

    async def add(self, channel: AlertChannel) -> AlertChannel:
        stored = copy.deepcopy(channel)
        self._store[stored.id] = stored
        return copy.deepcopy(stored)

    async def get(self, channel_id: UUID) -> AlertChannel | None:
        found = self._store.get(channel_id)
        return copy.deepcopy(found) if found is not None else None

    async def list(self) -> list[AlertChannel]:
        return [copy.deepcopy(c) for c in self._store.values()]

    async def update(self, channel: AlertChannel) -> AlertChannel:
        if channel.id not in self._store:
            raise LookupError(channel.id)
        stored = copy.deepcopy(channel)
        self._store[channel.id] = stored
        return copy.deepcopy(stored)

    async def delete(self, channel_id: UUID) -> bool:
        return self._store.pop(channel_id, None) is not None


class InMemoryNotificationLogRepository:
    """`NotificationLogRepository` backed by a list. `exists` keys on
    `(channel_id, monitor_id, transition_at)`, mirroring the SQL adapter's
    uniqueness so idempotency behaves identically under the contract test."""

    def __init__(self) -> None:
        self._store: list[NotificationLog] = []

    async def add(self, entry: NotificationLog) -> NotificationLog:
        stored = copy.deepcopy(entry)
        self._store.append(stored)
        return copy.deepcopy(stored)

    async def exists(self, *, channel_id: UUID, monitor_id: UUID, transition_at: datetime) -> bool:
        return any(
            e.channel_id == channel_id
            and e.monitor_id == monitor_id
            and e.transition_at == transition_at
            for e in self._store
        )

    async def list_for_monitor(
        self, monitor_id: UUID, *, limit: int | None = 100
    ) -> list[NotificationLog]:
        matches = [e for e in self._store if e.monitor_id == monitor_id]
        matches.sort(key=lambda e: e.fired_at, reverse=True)
        return [copy.deepcopy(e) for e in matches[:limit]]


class InMemoryStateTransitionRepository:
    """`StateTransitionRepository` backed by a list. `list_since` filters by
    `at >= since` and returns oldest-first, mirroring the SQL adapter so flap
    damping behaves identically under the contract test."""

    def __init__(self) -> None:
        self._store: list[StateTransition] = []

    async def add(self, transition: StateTransition) -> StateTransition:
        self._store.append(transition)
        return transition

    async def list_since(self, monitor_id: UUID, *, since: datetime) -> list[StateTransition]:
        matches = [t for t in self._store if t.monitor_id == monitor_id and t.at >= since]
        matches.sort(key=lambda t: t.at)
        return list(matches)


class FakeNotifier:
    """A scriptable `Notifier` that records the (channel, notification) pairs it was
    asked to send and returns a canned `NotifyResult`, so `AlertService` can be tested
    without any network (PLAN D4 — fakes over mocks). Contract-compliant: it returns a
    result and never raises, including for the failure case (`ok=False`)."""

    def __init__(self, result: NotifyResult | None = None) -> None:
        self.result = result or NotifyResult(ok=True, detail="HTTP 200")
        self.calls: list[tuple[AlertChannel, AlertNotification]] = []

    async def send(self, channel: AlertChannel, notification: AlertNotification) -> NotifyResult:
        self.calls.append((channel, notification))
        return self.result


class FakeHeartbeat:
    """A `Heartbeat` that counts pings instead of hitting the network, so a
    scheduler cycle can assert the dead-man's switch fired (SPEC §6)."""

    def __init__(self) -> None:
        self.pings = 0

    async def ping(self) -> None:
        self.pings += 1


class FakeEventBus:
    """An `EventBus` that records every published event in `.published` (for
    assertions) and also fans out to live subscribers with unbounded queues, so it
    doubles as a working bus. Mirrors `InProcessEventBus` behaviour minus the
    drop-oldest back-pressure (tests publish only a handful of events)."""

    def __init__(self) -> None:
        self.published: list[Event] = []
        self._subscribers: set[asyncio.Queue[Event]] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def publish(self, event: Event) -> None:
        self.published.append(event)
        for queue in list(self._subscribers):
            queue.put_nowait(event)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[AsyncIterator[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.add(queue)

        async def drain() -> AsyncIterator[Event]:
            while True:
                yield await queue.get()

        try:
            yield drain()
        finally:
            self._subscribers.discard(queue)


class FakeHttpProbe:
    """A scriptable `HttpProbe`. Returns a queued `ProbeResponse` (or raises a
    queued exception) per call, recording the requests it received. Lets the
    probe use case be tested without any network (PLAN D4 — fakes over mocks)."""

    def __init__(self, *, responses: list[ProbeResponse | Exception] | None = None) -> None:
        self._queue: list[ProbeResponse | Exception] = list(responses or [])
        self.requests: list[ProbeRequest] = []

    def queue(self, item: ProbeResponse | Exception) -> None:
        self._queue.append(item)

    async def send(
        self,
        request: ProbeRequest,
        *,
        timeout_seconds: float,
        follow_redirects: bool,
    ) -> ProbeResponse:
        self.requests.append(request)
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
