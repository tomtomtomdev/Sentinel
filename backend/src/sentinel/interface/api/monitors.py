"""Monitor CRUD routes (SPEC §3.2, §5). Thin transport layer: parse DTO →
delegate to `MonitorService` → serialize a redacted response. Domain errors
raised here are turned into the SPEC §5 envelope by the registered handlers."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from sentinel.application.check_service import CheckService
from sentinel.application.monitor_service import MonitorService
from sentinel.application.stats_service import StatsService
from sentinel.domain.value_objects import StatsWindow
from sentinel.interface.api.deps import (
    get_check_service,
    get_monitor_service,
    get_stats_service,
)
from sentinel.interface.api.schemas import (
    CheckResultResponse,
    MonitorCreate,
    MonitorResponse,
    MonitorSummaryDTO,
    MonitorUpdate,
    StatsResponse,
)

router = APIRouter(prefix="/monitors", tags=["monitors"])

ServiceDep = Annotated[MonitorService, Depends(get_monitor_service)]
CheckServiceDep = Annotated[CheckService, Depends(get_check_service)]
StatsServiceDep = Annotated[StatsService, Depends(get_stats_service)]


@router.post("", response_model=MonitorResponse, status_code=201)
async def create_monitor(payload: MonitorCreate, service: ServiceDep) -> MonitorResponse:
    created = await service.create(payload.to_entity())
    return MonitorResponse.from_entity(created)


@router.get("", response_model=list[MonitorResponse])
async def list_monitors(
    service: ServiceDep, stats: StatsServiceDep, include: str | None = None
) -> list[MonitorResponse]:
    """List monitors. `?include=summary` attaches each monitor's current status +
    24h rollup (SPEC §3.5); without it the `summary` field is `None`."""
    monitors = await service.list()
    if include != "summary":
        return [MonitorResponse.from_entity(m) for m in monitors]
    summaries = await stats.summaries(monitors)
    return [
        MonitorResponse.from_entity(m, summary=MonitorSummaryDTO.from_summary(summaries[m.id]))
        for m in monitors
    ]


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


@router.post("/{monitor_id}/check", response_model=CheckResultResponse)
async def check_monitor(monitor_id: UUID, service: CheckServiceDep) -> CheckResultResponse:
    """Run one probe immediately (SPEC §3.2). A transport failure is recorded and
    returned as a failed `CheckResult`, not raised as an API error (SPEC §3.3)."""
    return CheckResultResponse.from_entity(await service.run_check(monitor_id))


@router.get("/{monitor_id}/results", response_model=list[CheckResultResponse])
async def list_results(
    monitor_id: UUID,
    stats: StatsServiceDep,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[CheckResultResponse]:
    """Windowed, newest-first check history (SPEC §3.5). `from`/`to` bound
    `finished_at` inclusively; unknown monitor → 404."""
    results = await stats.history(monitor_id, since=from_, until=to, limit=limit)
    return [CheckResultResponse.from_entity(r) for r in results]


@router.get("/{monitor_id}/stats", response_model=StatsResponse)
async def get_stats(
    monitor_id: UUID, stats: StatsServiceDep, window: StatsWindow = StatsWindow.H24
) -> StatsResponse:
    """Uptime %, counts, and p50/p95/p99 latency over `window`, plus the monitor's
    current status/since (SPEC §3.5, §5). An unknown `window` → 422; unknown
    monitor → 404."""
    return StatsResponse.from_view(await stats.stats(monitor_id, window))
