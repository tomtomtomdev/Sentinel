"""POST /api/v1/imports/postman (SPEC §3.1, §5, §7). Multipart upload of a v2.1
collection → reviewable drafts; nothing is persisted. Folders flatten, `{{var}}`
resolves against the collection's variable block, unresolved vars warn (never
fail). Draft headers are echoed unredacted (the import is a parse echo, D14)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from sentinel.interface.main import create_app

IMPORT_POSTMAN = "/api/v1/imports/postman"
_FIXTURE = Path(__file__).parent.parent / "support" / "fixtures" / "postman_v21.json"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _upload(content: bytes, filename: str = "collection.json") -> dict[str, object]:
    return {"file": (filename, content, "application/json")}


async def test_acceptance_three_request_collection(client: httpx.AsyncClient) -> None:
    response = await client.post(IMPORT_POSTMAN, files=_upload(_FIXTURE.read_bytes()))
    assert response.status_code == 200
    drafts = response.json()["drafts"]
    assert len(drafts) == 3
    assert [d["name"] for d in drafts] == ["Health check", "Create user", "Get item"]
    assert drafts[0]["url"] == "https://api.example.com/health"
    assert drafts[1]["url"] == "https://api.example.com/users"
    assert drafts[1]["body_kind"] == "json"
    assert drafts[0]["warnings"] == []
    assert drafts[2]["url"] == "https://api.example.com/items/{{itemId}}"
    assert any("itemId" in w for w in drafts[2]["warnings"])


async def test_secret_header_value_is_not_redacted(client: httpx.AsyncClient) -> None:
    response = await client.post(IMPORT_POSTMAN, files=_upload(_FIXTURE.read_bytes()))
    create_user = response.json()["drafts"][1]
    assert create_user["headers"]["Authorization"] == "Bearer tok-123"


async def test_malformed_json_is_422_envelope(client: httpx.AsyncClient) -> None:
    response = await client.post(IMPORT_POSTMAN, files=_upload(b"{not valid json"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_non_object_json_is_422_envelope(client: httpx.AsyncClient) -> None:
    response = await client.post(IMPORT_POSTMAN, files=_upload(json.dumps([1, 2, 3]).encode()))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_missing_file_is_422(client: httpx.AsyncClient) -> None:
    response = await client.post(IMPORT_POSTMAN)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
