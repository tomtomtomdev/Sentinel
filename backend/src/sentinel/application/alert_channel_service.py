"""Alert-channel CRUD use case (SPEC §3.7). Orchestrates the
`AlertChannelRepository` port; it wires flow only — entity invariants live on
`AlertChannel`, and at-rest encryption is the repository's concern. Missing
channels surface as a typed `NotFoundError` the API maps to 404. Firing alerts is
a separate use case (`AlertService`, S9.3)."""

from __future__ import annotations

from uuid import UUID

from sentinel.domain.entities import AlertChannel
from sentinel.domain.errors import NotFoundError
from sentinel.domain.ports import AlertChannelRepository


class AlertChannelService:
    def __init__(self, repository: AlertChannelRepository) -> None:
        self._repository = repository

    async def create(self, channel: AlertChannel) -> AlertChannel:
        return await self._repository.add(channel)

    async def list(self) -> list[AlertChannel]:
        return await self._repository.list()

    async def get(self, channel_id: UUID) -> AlertChannel:
        channel = await self._repository.get(channel_id)
        if channel is None:
            raise NotFoundError(f"alert channel {channel_id} not found")
        return channel

    async def update(self, channel: AlertChannel) -> AlertChannel:
        try:
            return await self._repository.update(channel)
        except LookupError as exc:
            raise NotFoundError(f"alert channel {channel.id} not found") from exc

    async def delete(self, channel_id: UUID) -> None:
        if not await self._repository.delete(channel_id):
            raise NotFoundError(f"alert channel {channel_id} not found")
