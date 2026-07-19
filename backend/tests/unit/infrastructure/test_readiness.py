"""S14.3 — the DB readiness adapter (`/api/v1/ready` backing check, SPEC §6).

`DbReadinessCheck.check()` runs a cheap `SELECT 1` and answers a bool: True when
the database is reachable, False on any failure — it never raises (a readiness
probe must not itself crash) and never leaks the connection string / password
into a log line (SPEC §6)."""

from __future__ import annotations

import logging
from types import TracebackType

from sentinel.infrastructure.db.readiness import DbReadinessCheck


class _FakeSession:
    def __init__(self, *, error: Exception | None) -> None:
        self._error = error

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False

    async def execute(self, statement: object) -> None:
        if self._error is not None:
            raise self._error


class _FakeSessionFactory:
    """Stands in for `async_sessionmaker`: calling it yields an async-context
    session whose `execute` succeeds or raises the configured error."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error

    def __call__(self) -> _FakeSession:
        return _FakeSession(error=self._error)


async def test_check_returns_true_when_select_succeeds() -> None:
    check = DbReadinessCheck(_FakeSessionFactory())  # type: ignore[arg-type]

    assert await check.check() is True


async def test_check_returns_false_when_database_unreachable() -> None:
    check = DbReadinessCheck(_FakeSessionFactory(error=OSError("connection refused")))  # type: ignore[arg-type]

    assert await check.check() is False


async def test_check_never_raises_or_leaks_the_connection_string(
    caplog: logging.LogCaptureFixture,
) -> None:
    # A DB connection error whose message embeds the URL + password must not
    # propagate and must not appear in any log line (SPEC §6).
    secret = "postgresql://sentinel:sup3r-secret@db:5432/sentinel"
    check = DbReadinessCheck(_FakeSessionFactory(error=OSError(f"could not connect to {secret}")))  # type: ignore[arg-type]

    with caplog.at_level(logging.WARNING):
        result = await check.check()

    assert result is False
    assert "sup3r-secret" not in caplog.text
    assert secret not in caplog.text
