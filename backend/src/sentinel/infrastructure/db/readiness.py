"""Database readiness adapter for `GET /api/v1/ready` (SPEC §6). Pings Postgres
with a cheap `SELECT 1`; any failure means "not ready" rather than a crash."""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger("sentinel.readiness")


class DbReadinessCheck:
    """`ReadinessCheck` backed by the DB session factory. `check` opens a session,
    runs `SELECT 1`, and returns True on success. Any exception (connection
    refused, pool exhausted, auth failure) is swallowed to `False` and logged
    **without** the exception message — a driver error can embed the connection
    string / password, which must never reach a log line (SPEC §6)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def check(self) -> bool:
        try:
            async with self._session_factory() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception as exc:  # noqa: BLE001 — any failure = "not ready"
            logger.warning(
                "database readiness check failed",
                extra={"error_type": type(exc).__name__},
            )
            return False
