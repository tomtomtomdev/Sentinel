import httpx

from sentinel.interface.main import app


async def test_health_returns_ok() -> None:
    """SPEC §6 / §3: GET /api/v1/health is a liveness endpoint returning 200 OK."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
