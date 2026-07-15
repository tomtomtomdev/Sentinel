"""Alert-channel CRUD API (SPEC §3.7, §5). Exercised via httpx.ASGITransport with
an in-memory repo (PLAN D13). Proves channel `config` secrets are write-only:
stored in full but redacted in every response, and never echoed in the body."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx
import pytest

from sentinel.application.alert_channel_service import AlertChannelService
from sentinel.interface.api.deps import get_alert_channel_service
from sentinel.interface.main import create_app
from tests.support.fakes import InMemoryAlertChannelRepository


def create_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "ops-telegram",
        "type": "telegram",
        "config": {"bot_token": "12345:secret-token", "chat_id": "42"},
    }
    payload.update(overrides)
    return payload


@dataclass
class Harness:
    client: httpx.AsyncClient
    channels: InMemoryAlertChannelRepository


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    channels = InMemoryAlertChannelRepository()
    app = create_app()
    app.dependency_overrides[get_alert_channel_service] = lambda: AlertChannelService(channels)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Harness(client=client, channels=channels)
    app.dependency_overrides.clear()


async def test_create_redacts_config_secret_but_stores_full(harness: Harness) -> None:
    response = await harness.client.post("/api/v1/channels", json=create_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["config"]["bot_token"] == "••••"
    assert body["config"]["chat_id"] == "42"
    assert "secret-token" not in response.text
    # ...but the repository holds the real secret for the notifier to use.
    stored = await harness.channels.get(UUID(body["id"]))
    assert stored is not None
    assert stored.config["bot_token"] == "12345:secret-token"


async def test_list_redacts_every_channel(harness: Harness) -> None:
    await harness.client.post("/api/v1/channels", json=create_payload(name="a"))
    await harness.client.post(
        "/api/v1/channels",
        json=create_payload(
            name="b", type="webhook", config={"url": "https://x/y", "secret": "sign-me"}
        ),
    )
    response = await harness.client.get("/api/v1/channels")

    assert response.status_code == 200
    assert "secret-token" not in response.text
    assert "sign-me" not in response.text
    assert len(response.json()) == 2


async def test_get_returns_redacted_channel(harness: Harness) -> None:
    created = (await harness.client.post("/api/v1/channels", json=create_payload())).json()
    response = await harness.client.get(f"/api/v1/channels/{created['id']}")

    assert response.status_code == 200
    assert response.json()["config"]["bot_token"] == "••••"


async def test_get_unknown_is_404(harness: Harness) -> None:
    response = await harness.client.get(f"/api/v1/channels/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_patch_updates_and_redacts(harness: Harness) -> None:
    created = (await harness.client.post("/api/v1/channels", json=create_payload())).json()
    response = await harness.client.patch(
        f"/api/v1/channels/{created['id']}", json={"enabled": False}
    )

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["config"]["bot_token"] == "••••"


async def test_patch_replaces_config(harness: Harness) -> None:
    created = (await harness.client.post("/api/v1/channels", json=create_payload())).json()
    await harness.client.patch(
        f"/api/v1/channels/{created['id']}",
        json={"config": {"bot_token": "99999:new", "chat_id": "7"}},
    )
    stored = await harness.channels.get(UUID(created["id"]))
    assert stored is not None
    assert stored.config == {"bot_token": "99999:new", "chat_id": "7"}


async def test_delete_removes(harness: Harness) -> None:
    created = (await harness.client.post("/api/v1/channels", json=create_payload())).json()
    assert (await harness.client.delete(f"/api/v1/channels/{created['id']}")).status_code == 204
    assert (await harness.client.get(f"/api/v1/channels/{created['id']}")).status_code == 404


async def test_blank_name_is_422(harness: Harness) -> None:
    response = await harness.client.post("/api/v1/channels", json=create_payload(name="  "))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
