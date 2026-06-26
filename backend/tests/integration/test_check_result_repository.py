"""CheckResult repository contract — runs against the in-memory fake and (when
TEST_DATABASE_URL is set) real Postgres. Both must behave identically (PLAN D11).
Proves the JSONB mapping of `assertion_results`, the `ErrorKind` enum, the
nullable transport-failure fields, and per-monitor listing."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from sentinel.domain.entities import CheckResult
from sentinel.domain.ports import CheckResultRepository
from sentinel.domain.value_objects import AssertionResult, ErrorKind
from sentinel.infrastructure.db import models  # noqa: F401  -- register tables on metadata
from sentinel.infrastructure.db.check_result_repository import SqlCheckResultRepository
from sentinel.infrastructure.db.engine import create_session_factory
from tests.support.fakes import InMemoryCheckResultRepository

STARTED = datetime(2026, 6, 26, 9, 0, tzinfo=UTC)
FINISHED = STARTED + timedelta(milliseconds=123)
CERT = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
MONITOR_ID = uuid4()


def sample_result(**overrides: object) -> CheckResult:
    params: dict[str, object] = {
        "monitor_id": MONITOR_ID,
        "started_at": STARTED,
        "finished_at": FINISHED,
        "success": True,
        "status_code": 200,
        "latency_ms": 123,
        "response_size_bytes": 456,
        "cert_expires_at": CERT,
        "error": None,
        "assertion_results": [
            AssertionResult(type="status_code", passed=True, detail="status 200 in [200, 299]"),
            AssertionResult(type="max_latency_ms", passed=True, detail="latency 123ms <= 800ms"),
        ],
    }
    params.update(overrides)
    return CheckResult(**params)  # type: ignore[arg-type]


@pytest.fixture(params=["memory", "postgres"])
async def repo(request: pytest.FixtureRequest) -> AsyncIterator[CheckResultRepository]:
    if request.param == "memory":
        yield InMemoryCheckResultRepository()
        return

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping Postgres repository contract")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    try:
        yield SqlCheckResultRepository(create_session_factory(engine))
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
        await engine.dispose()


async def test_add_then_list_round_trips_all_fields(repo: CheckResultRepository) -> None:
    created = await repo.add(sample_result())
    listed = await repo.list_for_monitor(MONITOR_ID)

    assert len(listed) == 1
    fetched = listed[0]
    assert fetched.id == created.id
    assert fetched.monitor_id == MONITOR_ID
    assert fetched.started_at == STARTED
    assert fetched.finished_at == FINISHED
    assert fetched.success is True
    assert fetched.status_code == 200
    assert fetched.latency_ms == 123
    assert fetched.response_size_bytes == 456
    assert fetched.cert_expires_at == CERT
    assert fetched.error is None
    assert fetched.assertion_results == [
        AssertionResult(type="status_code", passed=True, detail="status 200 in [200, 299]"),
        AssertionResult(type="max_latency_ms", passed=True, detail="latency 123ms <= 800ms"),
    ]


async def test_transport_failure_nullable_fields_round_trip(repo: CheckResultRepository) -> None:
    failure = sample_result(
        success=False,
        status_code=None,
        latency_ms=None,
        response_size_bytes=None,
        cert_expires_at=None,
        error=ErrorKind.TIMEOUT,
        assertion_results=[],
    )
    await repo.add(failure)
    fetched = (await repo.list_for_monitor(MONITOR_ID))[0]

    assert fetched.success is False
    assert fetched.status_code is None
    assert fetched.latency_ms is None
    assert fetched.error is ErrorKind.TIMEOUT
    assert fetched.assertion_results == []


async def test_list_is_scoped_to_monitor_and_newest_first(repo: CheckResultRepository) -> None:
    other = uuid4()
    older = await repo.add(sample_result(finished_at=FINISHED))
    newer = await repo.add(sample_result(finished_at=FINISHED + timedelta(minutes=1)))
    await repo.add(sample_result(monitor_id=other))

    listed = await repo.list_for_monitor(MONITOR_ID)
    assert [r.id for r in listed] == [newer.id, older.id]


async def test_list_respects_limit(repo: CheckResultRepository) -> None:
    for i in range(5):
        await repo.add(sample_result(finished_at=FINISHED + timedelta(minutes=i)))
    listed = await repo.list_for_monitor(MONITOR_ID, limit=3)
    assert len(listed) == 3
