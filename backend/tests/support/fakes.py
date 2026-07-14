"""In-memory test doubles for the domain ports. Behaviour mirrors the real
adapters so the same contract test can run against either (PLAN D4)."""

from __future__ import annotations

import copy
from datetime import datetime
from uuid import UUID

from sentinel.domain.entities import AuthSource, CheckResult, Monitor, MonitorState, TokenState
from sentinel.domain.ports import Clock
from sentinel.domain.value_objects import ProbeRequest, ProbeResponse


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

    async def list_for_monitor(self, monitor_id: UUID, *, limit: int = 100) -> list[CheckResult]:
        matches = [r for r in self._store if r.monitor_id == monitor_id]
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


class FakeHeartbeat:
    """A `Heartbeat` that counts pings instead of hitting the network, so a
    scheduler cycle can assert the dead-man's switch fired (SPEC §6)."""

    def __init__(self) -> None:
        self.pings = 0

    async def ping(self) -> None:
        self.pings += 1


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
