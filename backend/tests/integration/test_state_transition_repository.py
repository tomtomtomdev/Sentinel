"""Repository contract for the state-transition history (SPEC §3.8) — the flap-window
source for alerting. Runs against the in-memory fake and (when TEST_DATABASE_URL is
set) real Postgres; both must behave identically: append transitions and read back a
monitor's flips at/after a cutoff, oldest-first, scoped to that monitor."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from sentinel.domain.ports import StateTransitionRepository
from sentinel.domain.value_objects import MonitorStatus, StateTransition
from sentinel.infrastructure.db import models  # noqa: F401  -- register tables on metadata
from sentinel.infrastructure.db.engine import create_session_factory
from sentinel.infrastructure.db.state_transition_repository import SqlStateTransitionRepository
from tests.support.fakes import InMemoryStateTransitionRepository

T0 = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "postgres"])
async def repo(request: pytest.FixtureRequest) -> AsyncIterator[StateTransitionRepository]:
    if request.param == "memory":
        yield InMemoryStateTransitionRepository()
        return

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping Postgres state-transition contract")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    try:
        yield SqlStateTransitionRepository(create_session_factory(engine))
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
        await engine.dispose()


def _transition(monitor_id: object, to: MonitorStatus, at: datetime) -> StateTransition:
    frm = MonitorStatus.UP if to is MonitorStatus.DOWN else MonitorStatus.DOWN
    return StateTransition(monitor_id=monitor_id, from_status=frm, to_status=to, at=at)  # type: ignore[arg-type]


async def test_add_then_list_since_returns_transitions_in_window_oldest_first(
    repo: StateTransitionRepository,
) -> None:
    monitor_id = uuid4()
    await repo.add(_transition(monitor_id, MonitorStatus.DOWN, T0 - timedelta(minutes=20)))
    await repo.add(_transition(monitor_id, MonitorStatus.UP, T0 - timedelta(minutes=5)))
    await repo.add(_transition(monitor_id, MonitorStatus.DOWN, T0 - timedelta(minutes=1)))

    recent = await repo.list_since(monitor_id, since=T0 - timedelta(minutes=10))

    assert [t.at for t in recent] == [T0 - timedelta(minutes=5), T0 - timedelta(minutes=1)]
    assert [t.to_status for t in recent] == [MonitorStatus.UP, MonitorStatus.DOWN]


async def test_list_since_is_scoped_to_the_monitor(repo: StateTransitionRepository) -> None:
    mine, theirs = uuid4(), uuid4()
    await repo.add(_transition(mine, MonitorStatus.DOWN, T0))
    await repo.add(_transition(theirs, MonitorStatus.DOWN, T0))

    recent = await repo.list_since(mine, since=T0 - timedelta(hours=1))

    assert len(recent) == 1
    assert recent[0].monitor_id == mine


async def test_list_since_boundary_is_inclusive(repo: StateTransitionRepository) -> None:
    monitor_id = uuid4()
    await repo.add(_transition(monitor_id, MonitorStatus.DOWN, T0))

    assert len(await repo.list_since(monitor_id, since=T0)) == 1
    assert len(await repo.list_since(monitor_id, since=T0 + timedelta(seconds=1))) == 0


async def test_prune_before_deletes_old_keeps_new_and_is_idempotent(
    repo: StateTransitionRepository,
) -> None:
    """S10.2 retention (SPEC §6): flips with `at` strictly before the cutoff go,
    at/after stays, across all monitors; a second run deletes nothing."""
    mine, theirs = uuid4(), uuid4()
    await repo.add(_transition(mine, MonitorStatus.DOWN, T0 - timedelta(days=31)))
    await repo.add(_transition(theirs, MonitorStatus.DOWN, T0 - timedelta(days=40)))
    await repo.add(_transition(mine, MonitorStatus.UP, T0))  # exactly at the cutoff → kept
    await repo.add(_transition(mine, MonitorStatus.DOWN, T0 + timedelta(minutes=5)))

    deleted = await repo.prune_before(T0)

    assert deleted == 2
    kept = await repo.list_since(mine, since=T0 - timedelta(days=365))
    assert [t.at for t in kept] == [T0, T0 + timedelta(minutes=5)]
    assert await repo.list_since(theirs, since=T0 - timedelta(days=365)) == []
    assert await repo.prune_before(T0) == 0  # idempotent
