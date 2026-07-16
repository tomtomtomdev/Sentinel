"""Postgres-backed `StateTransitionRepository` (SPEC §3.8) — the append-only history
of confirmed up↔down flips that feeds flap damping (SPEC §3.7). Carries no secrets,
so it needs no `SecretBox`. The domain `StateTransition` has no id; the row gets a
fresh surrogate key on insert."""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import col, select

from sentinel.domain.value_objects import MonitorStatus, StateTransition
from sentinel.infrastructure.db.engine import deleted_count
from sentinel.infrastructure.db.models import StateTransitionRow


def _to_row(transition: StateTransition) -> StateTransitionRow:
    return StateTransitionRow(
        id=uuid.uuid4(),
        monitor_id=transition.monitor_id,
        from_status=transition.from_status.value,
        to_status=transition.to_status.value,
        at=transition.at,
    )


def _to_entity(row: StateTransitionRow) -> StateTransition:
    return StateTransition(
        monitor_id=row.monitor_id,
        from_status=MonitorStatus(row.from_status),
        to_status=MonitorStatus(row.to_status),
        at=row.at,
    )


class SqlStateTransitionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, transition: StateTransition) -> StateTransition:
        row = _to_row(transition)
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
        return transition

    async def list_since(self, monitor_id: UUID, *, since: datetime) -> list[StateTransition]:
        async with self._session_factory() as session:
            stmt = (
                select(StateTransitionRow)
                .where(
                    col(StateTransitionRow.monitor_id) == monitor_id,
                    col(StateTransitionRow.at) >= since,
                )
                .order_by(col(StateTransitionRow.at))
            )
            result = await session.execute(stmt)
            return [_to_entity(row) for row in result.scalars().all()]

    async def prune_before(self, cutoff: datetime) -> int:
        """Delete every transition (all monitors) strictly before `cutoff` (SPEC §6
        retention). Flips older than the flap window have no reader anyway."""
        async with self._session_factory() as session:
            result = await session.execute(
                delete(StateTransitionRow).where(col(StateTransitionRow.at) < cutoff)
            )
            await session.commit()
            return deleted_count(result)
