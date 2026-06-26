from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from sentinel.domain.entities import Monitor


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
