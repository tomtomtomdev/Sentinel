"""SSE live-events endpoint (SPEC §3.6, §5). Streams `check_completed` and
`status_changed` events to connected dashboards over `text/event-stream` so they
update without polling. Pure transport: subscribe to the `EventBus`, render each
domain `Event` to an SSE frame. These events carry no secrets by construction
(`CheckCompleted` is a scalar summary; `StateTransition` is status metadata)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from sentinel.domain.ports import EventBus
from sentinel.domain.value_objects import CheckCompleted, Event
from sentinel.interface.api.deps import get_event_bus

router = APIRouter(tags=["events"])

EventBusDep = Annotated[EventBus, Depends(get_event_bus)]


def _iso(dt: datetime) -> str:
    """Match the API's datetime rendering — UTC as `...Z`, not `+00:00`."""
    return dt.isoformat().replace("+00:00", "Z")


def to_sse_frame(event: Event) -> str:
    """Render one domain `Event` as an SSE frame: an `event:` name line, a compact
    JSON `data:` line, and the blank line that terminates the event (SPEC §5)."""
    if isinstance(event, CheckCompleted):
        name = "check_completed"
        data: dict[str, object] = {
            "monitor_id": str(event.monitor_id),
            "success": event.success,
            "status_code": event.status_code,
            "latency_ms": event.latency_ms,
            "error": event.error.value if event.error is not None else None,
            "at": _iso(event.at),
        }
    else:  # StateTransition → status_changed
        name = "status_changed"
        data = {
            "monitor_id": str(event.monitor_id),
            "from": event.from_status.value,
            "to": event.to_status.value,
            "at": _iso(event.at),
        }
    return f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


@router.get("/events")
async def stream_events(bus: EventBusDep) -> StreamingResponse:
    """Open a Server-Sent Events stream. Stays open until the client disconnects,
    at which point the subscription is released."""

    async def source() -> AsyncIterator[str]:
        async with bus.subscribe() as events:
            async for event in events:
                yield to_sse_frame(event)

    return StreamingResponse(source(), media_type="text/event-stream")
