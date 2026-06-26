"""In-memory test doubles for the domain ports. Behaviour mirrors the real
adapters so the same contract test can run against either (PLAN D4)."""

from __future__ import annotations

import copy
from datetime import datetime
from uuid import UUID

from sentinel.domain.entities import Monitor
from sentinel.domain.ports import Clock


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
