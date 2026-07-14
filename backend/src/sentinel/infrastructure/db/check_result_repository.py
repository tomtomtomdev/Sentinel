"""Postgres-backed `CheckResultRepository`. Maps between the domain `CheckResult`
and the `CheckResultRow` table; `assertion_results` and the `ErrorKind` enum are
stored as JSONB / text. Listing is newest-first and bounded by `limit`."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import col, select

from sentinel.domain.entities import CheckResult
from sentinel.domain.value_objects import AssertionResult, ErrorKind
from sentinel.infrastructure.db.models import CheckResultRow


def _to_row(result: CheckResult) -> CheckResultRow:
    return CheckResultRow(
        id=result.id,
        monitor_id=result.monitor_id,
        started_at=result.started_at,
        finished_at=result.finished_at,
        status_code=result.status_code,
        latency_ms=result.latency_ms,
        response_size_bytes=result.response_size_bytes,
        cert_expires_at=result.cert_expires_at,
        success=result.success,
        error=result.error.value if result.error is not None else None,
        assertion_results=[
            {"type": r.type, "passed": r.passed, "detail": r.detail, "skipped": r.skipped}
            for r in result.assertion_results
        ],
    )


def _to_entity(row: CheckResultRow) -> CheckResult:
    return CheckResult(
        id=row.id,
        monitor_id=row.monitor_id,
        started_at=row.started_at,
        finished_at=row.finished_at,
        status_code=row.status_code,
        latency_ms=row.latency_ms,
        response_size_bytes=row.response_size_bytes,
        cert_expires_at=row.cert_expires_at,
        success=row.success,
        error=ErrorKind(row.error) if row.error is not None else None,
        assertion_results=[_assertion_from_json(a) for a in row.assertion_results],
    )


def _assertion_from_json(data: dict[str, Any]) -> AssertionResult:
    return AssertionResult(
        type=data["type"],
        passed=data["passed"],
        detail=data["detail"],
        skipped=data.get("skipped", False),
    )


class SqlCheckResultRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, result: CheckResult) -> CheckResult:
        row = _to_row(result)
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_entity(row)

    async def list_for_monitor(
        self,
        monitor_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = 100,
    ) -> list[CheckResult]:
        async with self._session_factory() as session:
            stmt = select(CheckResultRow).where(col(CheckResultRow.monitor_id) == monitor_id)
            if since is not None:
                stmt = stmt.where(col(CheckResultRow.finished_at) >= since)
            if until is not None:
                stmt = stmt.where(col(CheckResultRow.finished_at) <= until)
            stmt = stmt.order_by(col(CheckResultRow.finished_at).desc()).limit(limit)
            result = await session.execute(stmt)
            return [_to_entity(row) for row in result.scalars().all()]
