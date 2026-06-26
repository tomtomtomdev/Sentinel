"""Repository contract — runs against the in-memory fake and (when
TEST_DATABASE_URL is set) real Postgres. Both must behave identically."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from sentinel.domain.entities import Monitor
from sentinel.domain.ports import MonitorRepository
from sentinel.domain.value_objects import Assertion, Auth, AuthType, BodyKind, HttpMethod
from sentinel.infrastructure.db import models  # noqa: F401  -- register tables on metadata
from sentinel.infrastructure.db.engine import create_session_factory
from sentinel.infrastructure.db.models import MonitorRow
from sentinel.infrastructure.db.monitor_repository import SqlMonitorRepository
from sentinel.infrastructure.secrets import FernetSecretBox
from tests.support.fakes import FixedClock, InMemoryMonitorRepository

CLOCK_NOW = datetime(2026, 6, 26, 9, 0, tzinfo=UTC)
TEST_SECRET_KEY = Fernet.generate_key().decode()


def sample_monitor(**overrides: object) -> Monitor:
    params: dict[str, object] = {
        "name": "Prod health",
        "url": "https://api.example.com/health",
        "method": HttpMethod.POST,
        "headers": {"X-Api-Key": "k", "Authorization": "Bearer t"},
        "query_params": {"verbose": "1"},
        "body": '{"a":1}',
        "body_kind": BodyKind.JSON,
        "auth": Auth(type=AuthType.BEARER, secret_ref="ref-1"),
        "assertions": [Assertion(type="status_code", params={"equals": 200})],
        "interval_seconds": 60,
        "timeout_seconds": 5,
        "follow_redirects": False,
        "failure_threshold": 2,
        "recovery_threshold": 3,
        "tags": ["prod", "critical"],
    }
    params.update(overrides)
    return Monitor(**params)  # type: ignore[arg-type]


@pytest.fixture(params=["memory", "postgres"])
async def repo(request: pytest.FixtureRequest) -> AsyncIterator[MonitorRepository]:
    clock = FixedClock(CLOCK_NOW)
    if request.param == "memory":
        yield InMemoryMonitorRepository(clock=clock)
        return

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping Postgres repository contract")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    try:
        yield SqlMonitorRepository(
            create_session_factory(engine),
            clock=clock,
            secret_box=FernetSecretBox([TEST_SECRET_KEY]),
        )
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
        await engine.dispose()


async def test_add_then_get_round_trips_all_fields(repo: MonitorRepository) -> None:
    created = await repo.add(sample_monitor())
    fetched = await repo.get(created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.name == "Prod health"
    assert fetched.url == "https://api.example.com/health"
    assert fetched.method is HttpMethod.POST
    assert fetched.headers == {"X-Api-Key": "k", "Authorization": "Bearer t"}
    assert fetched.query_params == {"verbose": "1"}
    assert fetched.body == '{"a":1}'
    assert fetched.body_kind is BodyKind.JSON
    assert fetched.auth == Auth(type=AuthType.BEARER, secret_ref="ref-1")
    assert fetched.assertions == [Assertion(type="status_code", params={"equals": 200})]
    assert fetched.interval_seconds == 60
    assert fetched.timeout_seconds == 5
    assert fetched.follow_redirects is False
    assert fetched.failure_threshold == 2
    assert fetched.recovery_threshold == 3
    assert fetched.tags == ["prod", "critical"]


async def test_add_stamps_timestamps(repo: MonitorRepository) -> None:
    created = await repo.add(sample_monitor())
    assert created.created_at is not None
    assert created.updated_at is not None
    assert created.updated_at >= created.created_at


async def test_get_unknown_returns_none(repo: MonitorRepository) -> None:
    assert await repo.get(uuid4()) is None


async def test_list_returns_all_added(repo: MonitorRepository) -> None:
    a = await repo.add(sample_monitor(name="A"))
    b = await repo.add(sample_monitor(name="B"))
    listed = await repo.list()
    assert {m.id for m in listed} == {a.id, b.id}


async def test_update_persists_changes_and_preserves_created_at(repo: MonitorRepository) -> None:
    created = await repo.add(sample_monitor())
    created.name = "Renamed"
    created.enabled = False
    created.interval_seconds = 120

    updated = await repo.update(created)
    assert updated.name == "Renamed"
    assert updated.enabled is False
    assert updated.interval_seconds == 120
    assert updated.created_at == created.created_at

    refetched = await repo.get(created.id)
    assert refetched is not None
    assert refetched.name == "Renamed"
    assert refetched.enabled is False


async def test_delete_removes_and_reports(repo: MonitorRepository) -> None:
    created = await repo.add(sample_monitor())
    assert await repo.delete(created.id) is True
    assert await repo.get(created.id) is None
    assert await repo.delete(created.id) is False


async def test_secret_header_values_are_encrypted_at_rest() -> None:
    """SPEC §6 — secret-bearing header values persist as ciphertext, never
    plaintext; `get` transparently decrypts. Postgres-only (inspects the raw row)."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping at-rest encryption check")

    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    box = FernetSecretBox([TEST_SECRET_KEY])
    factory = create_session_factory(engine)
    repo = SqlMonitorRepository(factory, clock=FixedClock(CLOCK_NOW), secret_box=box)
    try:
        created = await repo.add(sample_monitor())

        async with factory() as session:
            row = await session.get(MonitorRow, created.id)
            assert row is not None
            # Stored ciphertext is not the plaintext...
            assert row.headers["Authorization"] != "Bearer t"
            assert row.headers["X-Api-Key"] != "k"
            # ...but decrypts back to it, and non-secret headers stay readable.
            assert box.decrypt(row.headers["Authorization"].encode("ascii")) == "Bearer t"
            assert box.decrypt(row.headers["X-Api-Key"].encode("ascii")) == "k"

        # The repository decrypts on read, so callers see plaintext.
        fetched = await repo.get(created.id)
        assert fetched is not None
        assert fetched.headers == {"X-Api-Key": "k", "Authorization": "Bearer t"}
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
        await engine.dispose()
