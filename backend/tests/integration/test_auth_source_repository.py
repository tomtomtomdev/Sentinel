"""Repository + token-store contract for the auth source (SPEC §3.9, §4) — runs
against the in-memory fakes and (when TEST_DATABASE_URL is set) real Postgres.
Both must behave identically. Postgres-only tests additionally assert that
credentials and the cached token persist as ciphertext, never plaintext (SPEC §6)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from sentinel.domain.entities import AuthSource, TokenState
from sentinel.domain.ports import AuthSourceRepository, TokenStore
from sentinel.domain.value_objects import (
    AuthSourceMode,
    ClientAuth,
    ExpiryKind,
    ExpirySpec,
    ExtractorKind,
    HttpMethod,
    Injection,
    InjectionTarget,
    OAuthConfig,
    ProbeRequest,
    TokenExtractor,
)
from sentinel.infrastructure.db import models  # noqa: F401  -- register tables on metadata
from sentinel.infrastructure.db.auth_source_repository import SqlAuthSourceRepository
from sentinel.infrastructure.db.engine import create_session_factory
from sentinel.infrastructure.db.models import AuthSourceRow, TokenStateRow
from sentinel.infrastructure.db.token_store import SqlTokenStore
from sentinel.infrastructure.secrets import FernetSecretBox
from tests.support.fakes import (
    FixedClock,
    InMemoryAuthSourceRepository,
    InMemoryTokenStore,
)

CLOCK_NOW = datetime(2026, 6, 27, 9, 0, tzinfo=UTC)
TEST_SECRET_KEY = Fernet.generate_key().decode()

OAUTH = OAuthConfig(
    token_url="https://id.example.com/token",
    client_id="cid",
    client_secret="super-secret",
    scope="read write",
    client_auth=ClientAuth.BASIC,
)


def sample_auth_source(**overrides: object) -> AuthSource:
    params: dict[str, object] = {
        "name": "Login",
        "mode": AuthSourceMode.CUSTOM,
        "request": ProbeRequest(
            method=HttpMethod.POST,
            url="https://id.example.com/login",
            headers={"Content-Type": "application/json", "X-Api-Key": "k"},
            body='{"username":"u","password":"p"}',
        ),
        "extractor": TokenExtractor(kind=ExtractorKind.JSON_PATH, expr="$.access_token"),
        "expiry": ExpirySpec(kind=ExpiryKind.JSON_PATH_SECONDS, value="$.expires_in"),
        "injection": Injection(target=InjectionTarget.HEADER, name="Authorization"),
        "token_type": "Bearer",
        "refresh_before_expiry_seconds": 120,
        "refresh_on_status": [401, 403, 419],
        "oauth": None,
    }
    params.update(overrides)
    return AuthSource(**params)  # type: ignore[arg-type]


def sample_token_state(source_id: object, **overrides: object) -> TokenState:
    params: dict[str, object] = {
        "auth_source_id": source_id,
        "token": "access-xyz",
        "token_type": "Bearer",
        "obtained_at": CLOCK_NOW,
        "expires_at": CLOCK_NOW + timedelta(hours=1),
        "refresh_token": "refresh-abc",
        "last_refresh_error": None,
    }
    params.update(overrides)
    return TokenState(**params)  # type: ignore[arg-type]


@pytest.fixture(params=["memory", "postgres"])
async def auth_repo(request: pytest.FixtureRequest) -> AsyncIterator[AuthSourceRepository]:
    clock = FixedClock(CLOCK_NOW)
    if request.param == "memory":
        yield InMemoryAuthSourceRepository(clock=clock)
        return

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping Postgres auth-source contract")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    try:
        yield SqlAuthSourceRepository(
            create_session_factory(engine),
            clock=clock,
            secret_box=FernetSecretBox([TEST_SECRET_KEY]),
        )
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
        await engine.dispose()


@pytest.fixture(params=["memory", "postgres"])
async def token_store(request: pytest.FixtureRequest) -> AsyncIterator[TokenStore]:
    if request.param == "memory":
        yield InMemoryTokenStore()
        return

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping Postgres token-store contract")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    try:
        yield SqlTokenStore(
            create_session_factory(engine), secret_box=FernetSecretBox([TEST_SECRET_KEY])
        )
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
        await engine.dispose()


# ---------------------------------------------------------- AuthSourceRepository


async def test_add_then_get_round_trips_custom_source(auth_repo: AuthSourceRepository) -> None:
    created = await auth_repo.add(sample_auth_source())
    fetched = await auth_repo.get(created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.name == "Login"
    assert fetched.mode is AuthSourceMode.CUSTOM
    assert fetched.request.method is HttpMethod.POST
    assert fetched.request.url == "https://id.example.com/login"
    assert fetched.request.headers == {"Content-Type": "application/json", "X-Api-Key": "k"}
    assert fetched.request.body == '{"username":"u","password":"p"}'
    assert fetched.extractor == TokenExtractor(kind=ExtractorKind.JSON_PATH, expr="$.access_token")
    assert fetched.expiry == ExpirySpec(kind=ExpiryKind.JSON_PATH_SECONDS, value="$.expires_in")
    assert fetched.injection == Injection(target=InjectionTarget.HEADER, name="Authorization")
    assert fetched.token_type == "Bearer"
    assert fetched.refresh_before_expiry_seconds == 120
    assert fetched.refresh_on_status == [401, 403, 419]
    assert fetched.oauth is None


async def test_add_then_get_round_trips_oauth_source(auth_repo: AuthSourceRepository) -> None:
    created = await auth_repo.add(
        sample_auth_source(mode=AuthSourceMode.OAUTH2_CLIENT_CREDENTIALS, oauth=OAUTH)
    )
    fetched = await auth_repo.get(created.id)

    assert fetched is not None
    assert fetched.mode is AuthSourceMode.OAUTH2_CLIENT_CREDENTIALS
    assert fetched.oauth == OAUTH


async def test_add_stamps_timestamps(auth_repo: AuthSourceRepository) -> None:
    created = await auth_repo.add(sample_auth_source())
    assert created.created_at is not None
    assert created.updated_at is not None
    assert created.updated_at >= created.created_at


async def test_get_unknown_returns_none(auth_repo: AuthSourceRepository) -> None:
    assert await auth_repo.get(uuid4()) is None


async def test_list_returns_all_added(auth_repo: AuthSourceRepository) -> None:
    a = await auth_repo.add(sample_auth_source(name="A"))
    b = await auth_repo.add(sample_auth_source(name="B"))
    listed = await auth_repo.list()
    assert {s.id for s in listed} == {a.id, b.id}


async def test_update_persists_and_preserves_created_at(auth_repo: AuthSourceRepository) -> None:
    created = await auth_repo.add(sample_auth_source())
    created.name = "Renamed"
    created.enabled = False
    created.token_type = "DPoP"

    updated = await auth_repo.update(created)
    assert updated.name == "Renamed"
    assert updated.enabled is False
    assert updated.token_type == "DPoP"
    assert updated.created_at == created.created_at

    refetched = await auth_repo.get(created.id)
    assert refetched is not None
    assert refetched.name == "Renamed"


async def test_delete_removes_and_reports(auth_repo: AuthSourceRepository) -> None:
    created = await auth_repo.add(sample_auth_source())
    assert await auth_repo.delete(created.id) is True
    assert await auth_repo.get(created.id) is None
    assert await auth_repo.delete(created.id) is False


# --------------------------------------------------------------------- TokenStore


async def test_save_then_load_round_trips(token_store: TokenStore) -> None:
    source_id = uuid4()
    saved = await token_store.save(sample_token_state(source_id))

    loaded = await token_store.load(source_id)
    assert loaded is not None
    assert loaded.auth_source_id == source_id
    assert loaded.token == "access-xyz"
    assert loaded.refresh_token == "refresh-abc"
    assert loaded.token_type == "Bearer"
    assert loaded.expires_at == CLOCK_NOW + timedelta(hours=1)
    assert loaded.last_refresh_error is None
    assert saved.token == "access-xyz"


async def test_load_unknown_returns_none(token_store: TokenStore) -> None:
    assert await token_store.load(uuid4()) is None


async def test_save_overwrites_single_row_per_source(token_store: TokenStore) -> None:
    source_id = uuid4()
    await token_store.save(sample_token_state(source_id, token="first"))
    await token_store.save(
        sample_token_state(source_id, token="second", refresh_token=None, last_refresh_error="boom")
    )

    loaded = await token_store.load(source_id)
    assert loaded is not None
    assert loaded.token == "second"
    assert loaded.refresh_token is None
    assert loaded.last_refresh_error == "boom"


# ----------------------------------------------------------- at-rest encryption


def _require_pg() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping at-rest encryption check")
    return url


async def test_credentials_are_encrypted_at_rest() -> None:
    """SPEC §6 — request-body credentials and oauth client_secret persist as
    ciphertext; `get` transparently decrypts. Postgres-only (inspects the raw row)."""
    engine = create_async_engine(_require_pg())
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    box = FernetSecretBox([TEST_SECRET_KEY])
    factory = create_session_factory(engine)
    repo = SqlAuthSourceRepository(factory, clock=FixedClock(CLOCK_NOW), secret_box=box)
    try:
        created = await repo.add(
            sample_auth_source(mode=AuthSourceMode.OAUTH2_CLIENT_CREDENTIALS, oauth=OAUTH)
        )

        async with factory() as session:
            row = await session.get(AuthSourceRow, created.id)
            assert row is not None
            assert row.request["body"] != '{"username":"u","password":"p"}'
            assert box.decrypt(row.request["body"].encode()) == '{"username":"u","password":"p"}'
            assert row.request["headers"]["X-Api-Key"] != "k"
            assert row.oauth["client_secret"] != "super-secret"
            assert box.decrypt(row.oauth["client_secret"].encode()) == "super-secret"

        fetched = await repo.get(created.id)
        assert fetched is not None
        assert fetched.request.body == '{"username":"u","password":"p"}'
        assert fetched.request.headers["X-Api-Key"] == "k"
        assert fetched.oauth is not None
        assert fetched.oauth.client_secret == "super-secret"
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
        await engine.dispose()


async def test_token_is_encrypted_at_rest() -> None:
    """SPEC §6 — the cached token and refresh token persist as ciphertext; `load`
    transparently decrypts. Postgres-only (inspects the raw row)."""
    engine = create_async_engine(_require_pg())
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    box = FernetSecretBox([TEST_SECRET_KEY])
    factory = create_session_factory(engine)
    store = SqlTokenStore(factory, secret_box=box)
    source_id = uuid4()
    try:
        await store.save(sample_token_state(source_id))

        async with factory() as session:
            row = await session.get(TokenStateRow, source_id)
            assert row is not None
            assert row.token != "access-xyz"
            assert box.decrypt(row.token.encode()) == "access-xyz"
            assert row.refresh_token is not None
            assert box.decrypt(row.refresh_token.encode()) == "refresh-abc"

        loaded = await store.load(source_id)
        assert loaded is not None
        assert loaded.token == "access-xyz"
        assert loaded.refresh_token == "refresh-abc"
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
        await engine.dispose()
