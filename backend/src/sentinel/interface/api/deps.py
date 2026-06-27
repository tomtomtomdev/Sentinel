"""Dependency wiring (composition root for the API). Concrete adapters are
constructed here and injected into use cases; routers depend only on the use
cases. Tests override `get_monitor_service` with a fake-backed service, so the
real engine is never created in the suite."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinel.application.auth_source_service import AuthSourceService
from sentinel.application.auth_token_service import AuthTokenService
from sentinel.application.check_service import CheckService
from sentinel.application.monitor_service import MonitorService
from sentinel.config import get_settings
from sentinel.domain.ports import AuthSourceRepository, Clock, HttpProbe, SecretBox, TokenStore
from sentinel.infrastructure.clock import SystemClock
from sentinel.infrastructure.db.auth_source_repository import SqlAuthSourceRepository
from sentinel.infrastructure.db.check_result_repository import SqlCheckResultRepository
from sentinel.infrastructure.db.engine import create_engine, create_session_factory
from sentinel.infrastructure.db.monitor_repository import SqlMonitorRepository
from sentinel.infrastructure.db.token_store import SqlTokenStore
from sentinel.infrastructure.probe import HttpxProbe
from sentinel.infrastructure.secrets import FernetSecretBox


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_engine(get_settings().database_url)
    return create_session_factory(engine)


def get_clock() -> Clock:
    return SystemClock()


@lru_cache
def get_secret_box() -> SecretBox:
    """The process-wide `SecretBox` for at-rest encryption. Built lazily from the
    `SECRET_KEY` key ring so importing the app needs no key; constructing it with an
    empty ring fails fast with a clear message (see `.env.example`)."""
    return FernetSecretBox(get_settings().secret_key_ring())


def get_auth_source_repository() -> AuthSourceRepository:
    return SqlAuthSourceRepository(
        get_session_factory(), clock=get_clock(), secret_box=get_secret_box()
    )


def get_token_store() -> TokenStore:
    return SqlTokenStore(get_session_factory(), secret_box=get_secret_box())


def get_monitor_service() -> MonitorService:
    repository = SqlMonitorRepository(
        get_session_factory(), clock=get_clock(), secret_box=get_secret_box()
    )
    return MonitorService(repository, auth_sources=get_auth_source_repository())


def get_auth_source_service() -> AuthSourceService:
    return AuthSourceService(get_auth_source_repository())


def get_auth_token_service() -> AuthTokenService:
    return AuthTokenService(
        sources=get_auth_source_repository(),
        tokens=get_token_store(),
        probe=get_http_probe(),
        clock=get_clock(),
    )


@lru_cache
def get_http_probe() -> HttpProbe:
    """One shared probe (and its pooled `AsyncClient`) for the process. Built
    lazily so importing the app opens no client; the event loop binds on first use."""
    return HttpxProbe()


def get_check_service() -> CheckService:
    factory = get_session_factory()
    clock = get_clock()
    return CheckService(
        monitors=SqlMonitorRepository(factory, clock=clock, secret_box=get_secret_box()),
        results=SqlCheckResultRepository(factory),
        probe=get_http_probe(),
        clock=clock,
        auth_sources=get_auth_source_repository(),
        auth=get_auth_token_service(),
    )
