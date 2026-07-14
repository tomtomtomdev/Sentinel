"""MonitorState repository contract — runs against the in-memory fake and (when
TEST_DATABASE_URL is set) real Postgres. Both must behave identically (PLAN D11).
Proves the one-row-per-monitor upsert (SPEC §3.8, §4), the `MonitorStatus` enum
mapping, and the nullable `last_check_at`."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from sentinel.domain.entities import MonitorState
from sentinel.domain.ports import MonitorStateRepository
from sentinel.domain.value_objects import MonitorStatus
from sentinel.infrastructure.db import models  # noqa: F401  -- register tables on metadata
from sentinel.infrastructure.db.engine import create_session_factory
from sentinel.infrastructure.db.monitor_state_repository import SqlMonitorStateRepository
from tests.support.fakes import InMemoryMonitorStateRepository

SINCE = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
LAST_CHECK = SINCE + timedelta(minutes=5)
MONITOR_ID = uuid4()


def sample_state(**overrides: object) -> MonitorState:
    params: dict[str, object] = {
        "monitor_id": MONITOR_ID,
        "since": SINCE,
        "status": MonitorStatus.DOWN,
        "consecutive_failures": 3,
        "consecutive_successes": 0,
        "last_check_at": LAST_CHECK,
    }
    params.update(overrides)
    return MonitorState(**params)  # type: ignore[arg-type]


@pytest.fixture(params=["memory", "postgres"])
async def repo(request: pytest.FixtureRequest) -> AsyncIterator[MonitorStateRepository]:
    if request.param == "memory":
        yield InMemoryMonitorStateRepository()
        return

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping Postgres repository contract")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    try:
        yield SqlMonitorStateRepository(create_session_factory(engine))
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
        await engine.dispose()


async def test_get_missing_returns_none(repo: MonitorStateRepository) -> None:
    assert await repo.get(uuid4()) is None


async def test_save_then_get_round_trips_all_fields(repo: MonitorStateRepository) -> None:
    await repo.save(sample_state())
    fetched = await repo.get(MONITOR_ID)

    assert fetched is not None
    assert fetched.monitor_id == MONITOR_ID
    assert fetched.status is MonitorStatus.DOWN
    assert fetched.since == SINCE
    assert fetched.consecutive_failures == 3
    assert fetched.consecutive_successes == 0
    assert fetched.last_check_at == LAST_CHECK


async def test_save_is_upsert_one_row_per_monitor(repo: MonitorStateRepository) -> None:
    await repo.save(sample_state())
    later = SINCE + timedelta(hours=1)
    await repo.save(
        sample_state(
            status=MonitorStatus.UP,
            since=later,
            consecutive_failures=0,
            consecutive_successes=2,
            last_check_at=later,
        )
    )

    fetched = await repo.get(MONITOR_ID)
    assert fetched is not None
    assert fetched.status is MonitorStatus.UP
    assert fetched.since == later
    assert fetched.consecutive_failures == 0
    assert fetched.consecutive_successes == 2


async def test_unknown_state_with_null_last_check_round_trips(repo: MonitorStateRepository) -> None:
    await repo.save(
        sample_state(status=MonitorStatus.UNKNOWN, consecutive_failures=0, last_check_at=None)
    )
    fetched = await repo.get(MONITOR_ID)

    assert fetched is not None
    assert fetched.status is MonitorStatus.UNKNOWN
    assert fetched.last_check_at is None
