from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CursorResult, Result
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, future=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def deleted_count(result: Result[Any]) -> int:
    """Rows affected by a bulk DELETE. `session.execute` is typed as a plain
    `Result`, but a DML statement always yields a `CursorResult` carrying
    `rowcount` — narrow it once here for the pruning repos."""
    return int(cast(CursorResult[Any], result).rowcount or 0)
