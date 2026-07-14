"""CheckRollup repository contract — runs against the in-memory fake and (when
TEST_DATABASE_URL is set) real Postgres. Both must behave identically (PLAN D11).
Proves the composite `(monitor_id, bucket_start)` upsert (SPEC §4, §6), the
`bucket_start` window listing, and that `updated_at` is stamped via the injected
`Clock` (D10)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from sentinel.domain.entities import CheckRollup
from sentinel.domain.ports import CheckRollupRepository
from sentinel.infrastructure.db import models  # noqa: F401  -- register tables on metadata
from sentinel.infrastructure.db.check_rollup_repository import SqlCheckRollupRepository
from sentinel.infrastructure.db.engine import create_session_factory
from tests.support.fakes import FixedClock, InMemoryCheckRollupRepository

CLOCK_NOW = datetime(2026, 7, 14, 20, 0, tzinfo=UTC)
BUCKET = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
MONITOR_ID = uuid4()


def sample_rollup(**overrides: object) -> CheckRollup:
    params: dict[str, object] = {
        "monitor_id": MONITOR_ID,
        "bucket_start": BUCKET,
        "checks": 10,
        "failures": 1,
        "latency_p50_ms": 500,
        "latency_p95_ms": 900,
        "latency_p99_ms": 950,
        "latency_sum_ms": 5400,
    }
    params.update(overrides)
    return CheckRollup(**params)  # type: ignore[arg-type]


@pytest.fixture(params=["memory", "postgres"])
async def repo(request: pytest.FixtureRequest) -> AsyncIterator[CheckRollupRepository]:
    clock = FixedClock(CLOCK_NOW)
    if request.param == "memory":
        yield InMemoryCheckRollupRepository(clock=clock)
        return

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping Postgres repository contract")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    try:
        yield SqlCheckRollupRepository(create_session_factory(engine), clock=clock)
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
        await engine.dispose()


async def test_get_missing_returns_none(repo: CheckRollupRepository) -> None:
    assert await repo.get(uuid4(), BUCKET) is None


async def test_save_then_get_round_trips_all_fields(repo: CheckRollupRepository) -> None:
    saved = await repo.save(sample_rollup())
    assert saved.updated_at == CLOCK_NOW  # stamped on save

    fetched = await repo.get(MONITOR_ID, BUCKET)
    assert fetched is not None
    assert fetched.monitor_id == MONITOR_ID
    assert fetched.bucket_start == BUCKET
    assert fetched.checks == 10
    assert fetched.failures == 1
    assert fetched.latency_p50_ms == 500
    assert fetched.latency_p95_ms == 900
    assert fetched.latency_p99_ms == 950
    assert fetched.latency_sum_ms == 5400
    assert fetched.updated_at == CLOCK_NOW


async def test_save_is_upsert_one_row_per_bucket(repo: CheckRollupRepository) -> None:
    await repo.save(sample_rollup(checks=10, failures=1))
    await repo.save(sample_rollup(checks=20, failures=3))  # same (monitor, bucket)

    fetched = await repo.get(MONITOR_ID, BUCKET)
    assert fetched is not None
    assert fetched.checks == 20
    assert fetched.failures == 3

    window = await repo.list_for_window(
        MONITOR_ID, since=BUCKET - timedelta(hours=1), until=BUCKET + timedelta(hours=1)
    )
    assert len(window) == 1  # upsert, not insert


async def test_list_for_window_filters_by_bucket_start_inclusive_and_orders(
    repo: CheckRollupRepository,
) -> None:
    for hours in (-2, -1, 0, 1):
        await repo.save(sample_rollup(bucket_start=BUCKET + timedelta(hours=hours)))

    window = await repo.list_for_window(MONITOR_ID, since=BUCKET - timedelta(hours=1), until=BUCKET)

    starts = [r.bucket_start for r in window]
    assert starts == [BUCKET - timedelta(hours=1), BUCKET]  # inclusive both ends, ascending


async def test_list_for_window_scopes_to_the_monitor(repo: CheckRollupRepository) -> None:
    await repo.save(sample_rollup())
    other = await repo.save(sample_rollup(monitor_id=uuid4()))

    window = await repo.list_for_window(
        other.monitor_id, since=BUCKET - timedelta(hours=1), until=BUCKET + timedelta(hours=1)
    )
    assert [r.monitor_id for r in window] == [other.monitor_id]
