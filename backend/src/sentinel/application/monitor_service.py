"""Monitor CRUD use case (SPEC §3.2). Orchestrates the `MonitorRepository` port;
it wires flow only — entity invariants live on `Monitor`, timestamps are stamped
by the repository's injected `Clock` (PLAN D10). Missing entities surface as a
typed `NotFoundError` the API maps to 404."""

from __future__ import annotations

from uuid import UUID

from sentinel.domain.entities import Monitor
from sentinel.domain.errors import NotFoundError, ValidationError
from sentinel.domain.ports import AuthSourceRepository, MonitorRepository


class MonitorService:
    def __init__(
        self, repository: MonitorRepository, auth_sources: AuthSourceRepository | None = None
    ) -> None:
        self._repository = repository
        self._auth_sources = auth_sources

    async def create(self, monitor: Monitor) -> Monitor:
        await self._validate_auth_source(monitor)
        return await self._repository.add(monitor)

    async def _validate_auth_source(self, monitor: Monitor) -> None:
        """A monitor may only link to an existing auth source (SPEC §3.9). When no
        auth-source repo is wired (e.g. some unit tests), validation is skipped."""
        if monitor.auth_source_id is None or self._auth_sources is None:
            return
        if await self._auth_sources.get(monitor.auth_source_id) is None:
            raise ValidationError(f"auth_source_id {monitor.auth_source_id} does not exist")

    async def list(self) -> list[Monitor]:
        return await self._repository.list()

    async def get(self, monitor_id: UUID) -> Monitor:
        monitor = await self._repository.get(monitor_id)
        if monitor is None:
            raise NotFoundError(f"monitor {monitor_id} not found")
        return monitor

    async def update(self, monitor: Monitor) -> Monitor:
        await self._validate_auth_source(monitor)
        try:
            return await self._repository.update(monitor)
        except LookupError as exc:
            raise NotFoundError(f"monitor {monitor.id} not found") from exc

    async def delete(self, monitor_id: UUID) -> None:
        if not await self._repository.delete(monitor_id):
            raise NotFoundError(f"monitor {monitor_id} not found")
