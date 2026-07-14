"""Postgres-backed `MonitorStateRepository` (SPEC §3.8, §4). Maps between the
domain `MonitorState` and the `MonitorStateRow` table; `save` is an upsert keyed by
`monitor_id`, so each monitor has exactly one state row advanced in place as checks
land. The `MonitorStatus` enum is stored as text; there are no secrets, so no
`SecretBox` is needed."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinel.domain.entities import MonitorState
from sentinel.domain.value_objects import MonitorStatus
from sentinel.infrastructure.db.models import MonitorStateRow


def _to_entity(row: MonitorStateRow) -> MonitorState:
    return MonitorState(
        monitor_id=row.monitor_id,
        since=row.since,
        status=MonitorStatus(row.status),
        consecutive_failures=row.consecutive_failures,
        consecutive_successes=row.consecutive_successes,
        last_check_at=row.last_check_at,
    )


class SqlMonitorStateRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, monitor_id: UUID) -> MonitorState | None:
        async with self._session_factory() as session:
            row = await session.get(MonitorStateRow, monitor_id)
            return _to_entity(row) if row is not None else None

    async def save(self, state: MonitorState) -> MonitorState:
        async with self._session_factory() as session:
            row = await session.get(MonitorStateRow, state.monitor_id)
            if row is None:
                session.add(
                    MonitorStateRow(
                        monitor_id=state.monitor_id,
                        status=state.status.value,
                        since=state.since,
                        consecutive_failures=state.consecutive_failures,
                        consecutive_successes=state.consecutive_successes,
                        last_check_at=state.last_check_at,
                    )
                )
            else:
                row.status = state.status.value
                row.since = state.since
                row.consecutive_failures = state.consecutive_failures
                row.consecutive_successes = state.consecutive_successes
                row.last_check_at = state.last_check_at
            await session.commit()
        return state
