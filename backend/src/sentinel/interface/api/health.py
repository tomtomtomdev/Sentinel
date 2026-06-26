from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe (SPEC §6). Deepened in S14."""
    return {"status": "ok"}
