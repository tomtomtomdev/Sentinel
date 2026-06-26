"""POST /api/v1/imports/curl (SPEC §3.1, §5). Returns reviewable drafts; nothing
is persisted. Draft headers are echoed unredacted so the client can review and
save them — the import response is a parse echo of the user's own input."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from sentinel.interface.main import create_app

IMPORT_CURL = "/api/v1/imports/curl"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_spec_example_shape(client: httpx.AsyncClient) -> None:
    response = await client.post(
        IMPORT_CURL, json={"command": "curl -H 'X-Api-Key: k' https://x/y"}
    )
    assert response.status_code == 200
    drafts = response.json()["drafts"]
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft["name"] == "GET /y"
    assert draft["method"] == "GET"
    assert draft["url"] == "https://x/y"
    assert draft["headers"] == {"X-Api-Key": "k"}
    assert draft["assertions"] == []
    assert draft["warnings"] == []


async def test_secret_headers_are_not_redacted_in_drafts(client: httpx.AsyncClient) -> None:
    command = "curl -H 'Authorization: Bearer supersecret' https://x/y"
    response = await client.post(IMPORT_CURL, json={"command": command})
    draft = response.json()["drafts"][0]
    assert draft["headers"]["Authorization"] == "Bearer supersecret"


async def test_post_with_json_body(client: httpx.AsyncClient) -> None:
    command = (
        "curl -X POST https://api.example.com/users "
        "-H 'Content-Type: application/json' -d '{\"name\":\"x\"}'"
    )
    response = await client.post(IMPORT_CURL, json={"command": command})
    draft = response.json()["drafts"][0]
    assert draft["method"] == "POST"
    assert draft["body"] == '{"name":"x"}'
    assert draft["body_kind"] == "json"


async def test_unknown_flag_surfaces_warning(client: httpx.AsyncClient) -> None:
    response = await client.post(IMPORT_CURL, json={"command": "curl --insecure https://x/y"})
    draft = response.json()["drafts"][0]
    assert any("--insecure" in w for w in draft["warnings"])


async def test_missing_command_is_422(client: httpx.AsyncClient) -> None:
    response = await client.post(IMPORT_CURL, json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
