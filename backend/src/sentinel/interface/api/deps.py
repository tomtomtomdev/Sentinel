"""Dependency wiring (composition root for the API). Concrete adapters are
constructed here and injected into use cases; routers depend only on the use
cases. Tests override `get_monitor_service` with a fake-backed service, so the
real engine is never created in the suite."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinel.application.check_service import CheckService
from sentinel.application.monitor_service import MonitorService
from sentinel.config import get_settings
from sentinel.domain.ports import Clock, HttpProbe
from sentinel.infrastructure.clock import SystemClock
from sentinel.infrastructure.db.check_result_repository import SqlCheckResultRepository
from sentinel.infrastructure.db.engine import create_engine, create_session_factory
from sentinel.infrastructure.db.monitor_repository import SqlMonitorRepository
from sentinel.infrastructure.probe import HttpxProbe


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_engine(get_settings().database_url)
    return create_session_factory(engine)


def get_clock() -> Clock:
    return SystemClock()


def get_monitor_service() -> MonitorService:
    repository = SqlMonitorRepository(get_session_factory(), clock=get_clock())
    return MonitorService(repository)


@lru_cache
def get_http_probe() -> HttpProbe:
    """One shared probe (and its pooled `AsyncClient`) for the process. Built
    lazily so importing the app opens no client; the event loop binds on first use."""
    return HttpxProbe()


def get_check_service() -> CheckService:
    factory = get_session_factory()
    clock = get_clock()
    return CheckService(
        monitors=SqlMonitorRepository(factory, clock=clock),
        results=SqlCheckResultRepository(factory),
        probe=get_http_probe(),
        clock=clock,
    )
