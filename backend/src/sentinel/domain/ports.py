from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from sentinel.domain.entities import CheckResult, Monitor
from sentinel.domain.value_objects import ProbeRequest, ProbeResponse


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
    monitor's checks newest-first (S7 extends it with from/to windows)."""

    async def add(self, result: CheckResult) -> CheckResult: ...

    async def list_for_monitor(
        self, monitor_id: UUID, *, limit: int = 100
    ) -> list[CheckResult]: ...


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
