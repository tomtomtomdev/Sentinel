"""Postgres-backed `CheckRollupRepository` (SPEC §3.5, §4, §6). Maps between the
domain `CheckRollup` and the `CheckRollupRow` table; `save` is an upsert keyed by
the composite `(monitor_id, bucket_start)`, stamping `updated_at` from the injected
`Clock` (D10). There are no secrets, so no `SecretBox` is needed."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import col, select

from sentinel.domain.entities import CheckRollup
from sentinel.domain.ports import Clock
from sentinel.infrastructure.db.models import CheckRollupRow


def _to_entity(row: CheckRollupRow) -> CheckRollup:
    return CheckRollup(
        monitor_id=row.monitor_id,
        bucket_start=row.bucket_start,
        checks=row.checks,
        failures=row.failures,
        latency_p50_ms=row.latency_p50_ms,
        latency_p95_ms=row.latency_p95_ms,
        latency_p99_ms=row.latency_p99_ms,
        latency_sum_ms=row.latency_sum_ms,
        updated_at=row.updated_at,
    )


class SqlCheckRollupRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], *, clock: Clock) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def get(self, monitor_id: UUID, bucket_start: datetime) -> CheckRollup | None:
        async with self._session_factory() as session:
            row = await session.get(CheckRollupRow, (monitor_id, bucket_start))
            return _to_entity(row) if row is not None else None

    async def save(self, rollup: CheckRollup) -> CheckRollup:
        now = self._clock.now()
        async with self._session_factory() as session:
            row = await session.get(CheckRollupRow, (rollup.monitor_id, rollup.bucket_start))
            if row is None:
                session.add(
                    CheckRollupRow(
                        monitor_id=rollup.monitor_id,
                        bucket_start=rollup.bucket_start,
                        checks=rollup.checks,
                        failures=rollup.failures,
                        latency_p50_ms=rollup.latency_p50_ms,
                        latency_p95_ms=rollup.latency_p95_ms,
                        latency_p99_ms=rollup.latency_p99_ms,
                        latency_sum_ms=rollup.latency_sum_ms,
                        updated_at=now,
                    )
                )
            else:
                row.checks = rollup.checks
                row.failures = rollup.failures
                row.latency_p50_ms = rollup.latency_p50_ms
                row.latency_p95_ms = rollup.latency_p95_ms
                row.latency_p99_ms = rollup.latency_p99_ms
                row.latency_sum_ms = rollup.latency_sum_ms
                row.updated_at = now
            await session.commit()
        return replace(rollup, updated_at=now)

    async def list_for_window(
        self, monitor_id: UUID, *, since: datetime, until: datetime
    ) -> list[CheckRollup]:
        async with self._session_factory() as session:
            stmt = (
                select(CheckRollupRow)
                .where(col(CheckRollupRow.monitor_id) == monitor_id)
                .where(col(CheckRollupRow.bucket_start) >= since)
                .where(col(CheckRollupRow.bucket_start) <= until)
                .order_by(col(CheckRollupRow.bucket_start))
            )
            result = await session.execute(stmt)
            return [_to_entity(row) for row in result.scalars().all()]
