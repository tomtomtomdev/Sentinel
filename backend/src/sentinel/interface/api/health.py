from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from sentinel.domain.ports import ReadinessCheck
from sentinel.interface.api.deps import get_readiness_check

router = APIRouter(tags=["health"])

ReadinessDep = Annotated[ReadinessCheck, Depends(get_readiness_check)]


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe (SPEC §6): the process is up. Deliberately checks no
    dependencies, so a transient DB outage never restarts a healthy web process."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(readiness: ReadinessDep) -> JSONResponse:
    """Readiness probe (SPEC §6): can the process serve traffic — i.e. is the
    database reachable (a cheap `SELECT 1`)? Returns 503 when it isn't, so a load
    balancer drains this instance during a DB outage without the process being
    killed. Stays outside the S9a auth gate (orchestrators probe without creds)."""
    ok = await readiness.check()
    payload = {
        "status": "ready" if ok else "not_ready",
        "checks": {"database": "ok" if ok else "error"},
    }
    return JSONResponse(payload, status_code=200 if ok else 503)
