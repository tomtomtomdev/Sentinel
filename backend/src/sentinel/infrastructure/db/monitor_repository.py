"""Postgres-backed `MonitorRepository`. Maps between the domain `Monitor` and
the `MonitorRow` table; stamps audit timestamps via the injected `Clock` so the
behaviour matches the in-memory fake."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinel.domain.entities import Monitor
from sentinel.domain.ports import Clock
from sentinel.domain.value_objects import Assertion, Auth, AuthType, BodyKind, HttpMethod
from sentinel.infrastructure.db.models import MonitorRow


def _auth_to_json(auth: Auth | None) -> dict[str, Any] | None:
    if auth is None:
        return None
    return {"type": auth.type.value, "secret_ref": auth.secret_ref}


def _auth_from_json(data: dict[str, Any] | None) -> Auth | None:
    if data is None:
        return None
    return Auth(type=AuthType(data["type"]), secret_ref=data.get("secret_ref"))


def _to_row(monitor: Monitor, *, created_at: datetime, updated_at: datetime) -> MonitorRow:
    return MonitorRow(
        id=monitor.id,
        name=monitor.name,
        method=monitor.method.value,
        url=monitor.url,
        headers=dict(monitor.headers),
        query_params=dict(monitor.query_params),
        body=monitor.body,
        body_kind=monitor.body_kind.value,
        auth=_auth_to_json(monitor.auth),
        assertions=[{"type": a.type, "params": a.params} for a in monitor.assertions],
        interval_seconds=monitor.interval_seconds,
        timeout_seconds=monitor.timeout_seconds,
        follow_redirects=monitor.follow_redirects,
        failure_threshold=monitor.failure_threshold,
        recovery_threshold=monitor.recovery_threshold,
        auth_source_id=monitor.auth_source_id,
        enabled=monitor.enabled,
        tags=list(monitor.tags),
        created_at=created_at,
        updated_at=updated_at,
    )


def _to_entity(row: MonitorRow) -> Monitor:
    return Monitor(
        id=row.id,
        name=row.name,
        method=HttpMethod(row.method),
        url=row.url,
        headers=dict(row.headers),
        query_params=dict(row.query_params),
        body=row.body,
        body_kind=BodyKind(row.body_kind),
        auth=_auth_from_json(row.auth),
        assertions=[Assertion(type=a["type"], params=a.get("params", {})) for a in row.assertions],
        interval_seconds=row.interval_seconds,
        timeout_seconds=row.timeout_seconds,
        follow_redirects=row.follow_redirects,
        failure_threshold=row.failure_threshold,
        recovery_threshold=row.recovery_threshold,
        auth_source_id=row.auth_source_id,
        enabled=row.enabled,
        tags=list(row.tags),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


_MUTABLE_FIELDS = (
    "name",
    "method",
    "url",
    "headers",
    "query_params",
    "body",
    "body_kind",
    "auth",
    "assertions",
    "interval_seconds",
    "timeout_seconds",
    "follow_redirects",
    "failure_threshold",
    "recovery_threshold",
    "auth_source_id",
    "enabled",
    "tags",
    "updated_at",
)


class SqlMonitorRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def add(self, monitor: Monitor) -> Monitor:
        now = self._clock.now()
        row = _to_row(monitor, created_at=monitor.created_at or now, updated_at=now)
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_entity(row)

    async def get(self, monitor_id: UUID) -> Monitor | None:
        async with self._session_factory() as session:
            row = await session.get(MonitorRow, monitor_id)
            return _to_entity(row) if row is not None else None

    async def list(self) -> list[Monitor]:
        async with self._session_factory() as session:
            result = await session.execute(select(MonitorRow))
            return [_to_entity(row) for row in result.scalars().all()]

    async def update(self, monitor: Monitor) -> Monitor:
        async with self._session_factory() as session:
            row = await session.get(MonitorRow, monitor.id)
            if row is None:
                raise LookupError(monitor.id)
            new = _to_row(monitor, created_at=row.created_at, updated_at=self._clock.now())
            for field_name in _MUTABLE_FIELDS:
                setattr(row, field_name, getattr(new, field_name))
            await session.commit()
            await session.refresh(row)
            return _to_entity(row)

    async def delete(self, monitor_id: UUID) -> bool:
        async with self._session_factory() as session:
            row = await session.get(MonitorRow, monitor_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True
