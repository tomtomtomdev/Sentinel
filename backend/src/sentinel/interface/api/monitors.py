"""Monitor CRUD routes (SPEC §3.2, §5). Thin transport layer: parse DTO →
delegate to `MonitorService` → serialize a redacted response. Domain errors
raised here are turned into the SPEC §5 envelope by the registered handlers."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from sentinel.application.monitor_service import MonitorService
from sentinel.interface.api.deps import get_monitor_service
from sentinel.interface.api.schemas import MonitorCreate, MonitorResponse, MonitorUpdate

router = APIRouter(prefix="/monitors", tags=["monitors"])

ServiceDep = Annotated[MonitorService, Depends(get_monitor_service)]


@router.post("", response_model=MonitorResponse, status_code=201)
async def create_monitor(payload: MonitorCreate, service: ServiceDep) -> MonitorResponse:
    created = await service.create(payload.to_entity())
    return MonitorResponse.from_entity(created)


@router.get("", response_model=list[MonitorResponse])
async def list_monitors(service: ServiceDep) -> list[MonitorResponse]:
    monitors = await service.list()
    return [MonitorResponse.from_entity(m) for m in monitors]


@router.get("/{monitor_id}", response_model=MonitorResponse)
async def get_monitor(monitor_id: UUID, service: ServiceDep) -> MonitorResponse:
    return MonitorResponse.from_entity(await service.get(monitor_id))


@router.patch("/{monitor_id}", response_model=MonitorResponse)
async def update_monitor(
    monitor_id: UUID, payload: MonitorUpdate, service: ServiceDep
) -> MonitorResponse:
    existing = await service.get(monitor_id)
    updated = await service.update(payload.apply_to(existing))
    return MonitorResponse.from_entity(updated)


@router.delete("/{monitor_id}", status_code=204)
async def delete_monitor(monitor_id: UUID, service: ServiceDep) -> None:
    await service.delete(monitor_id)
