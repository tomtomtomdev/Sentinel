"""Alert-channel CRUD routes (SPEC §3.7, §5). Thin transport layer: parse DTO →
delegate to the use case → serialize a config-redacted response. Channel secrets
are write-only — accepted on create/update, never returned. Domain errors raised
here become the SPEC §5 envelope via the registered handlers."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from sentinel.application.alert_channel_service import AlertChannelService
from sentinel.interface.api.deps import get_alert_channel_service
from sentinel.interface.api.schemas import (
    AlertChannelCreate,
    AlertChannelResponse,
    AlertChannelUpdate,
)

router = APIRouter(prefix="/channels", tags=["channels"])

ServiceDep = Annotated[AlertChannelService, Depends(get_alert_channel_service)]


@router.post("", response_model=AlertChannelResponse, status_code=201)
async def create_channel(payload: AlertChannelCreate, service: ServiceDep) -> AlertChannelResponse:
    created = await service.create(payload.to_entity())
    return AlertChannelResponse.from_entity(created)


@router.get("", response_model=list[AlertChannelResponse])
async def list_channels(service: ServiceDep) -> list[AlertChannelResponse]:
    channels = await service.list()
    return [AlertChannelResponse.from_entity(c) for c in channels]


@router.get("/{channel_id}", response_model=AlertChannelResponse)
async def get_channel(channel_id: UUID, service: ServiceDep) -> AlertChannelResponse:
    return AlertChannelResponse.from_entity(await service.get(channel_id))


@router.patch("/{channel_id}", response_model=AlertChannelResponse)
async def update_channel(
    channel_id: UUID, payload: AlertChannelUpdate, service: ServiceDep
) -> AlertChannelResponse:
    existing = await service.get(channel_id)
    updated = await service.update(payload.apply_to(existing))
    return AlertChannelResponse.from_entity(updated)


@router.delete("/{channel_id}", status_code=204)
async def delete_channel(channel_id: UUID, service: ServiceDep) -> None:
    await service.delete(channel_id)
