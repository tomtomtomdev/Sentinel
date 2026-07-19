"""End-to-end re-encryption pass (S15, SPEC §6, PLAN D40).

The acceptance criterion for the key-rotation runbook's missing step: seed every
secret-bearing table under an OLD key, rotate the ring (prepend a NEW key), run
the `ReEncryptor`, and prove every stored ciphertext now decrypts under the NEW
key *alone* — i.e. the old key can finally be dropped from the ring. Postgres-only
(inspects raw rows); skipped when `TEST_DATABASE_URL` is unset, like the rest of
the DB contract suite (PLAN D13).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

from sentinel.domain.entities import AlertChannel, AuthSource, Monitor, TokenState
from sentinel.domain.value_objects import (
    Assertion,
    Auth,
    AuthSourceMode,
    AuthType,
    BodyKind,
    ChannelType,
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
from sentinel.infrastructure.db.alert_channel_repository import SqlAlertChannelRepository
from sentinel.infrastructure.db.auth_source_repository import SqlAuthSourceRepository
from sentinel.infrastructure.db.engine import create_session_factory
from sentinel.infrastructure.db.models import (
    AlertChannelRow,
    AuthSourceRow,
    MonitorRow,
    TokenStateRow,
)
from sentinel.infrastructure.db.monitor_repository import SqlMonitorRepository
from sentinel.infrastructure.db.token_store import SqlTokenStore
from sentinel.infrastructure.reencrypt import ReEncryptor
from sentinel.infrastructure.secrets import FernetSecretBox
from tests.support.fakes import FixedClock

CLOCK_NOW = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
OLD_KEY = Fernet.generate_key().decode()
NEW_KEY = Fernet.generate_key().decode()


def _monitor() -> Monitor:
    return Monitor(
        name="Prod health",
        url="https://api.example.com/health",
        method=HttpMethod.GET,
        headers={"Authorization": "Bearer monitor-token", "Accept": "application/json"},
        query_params={},
        body=None,
        body_kind=BodyKind.NONE,
        auth=Auth(type=AuthType.BEARER, secret_ref="ref-1"),
        assertions=[Assertion(type="status_code", params={"equals": 200})],
        interval_seconds=60,
        timeout_seconds=5,
        follow_redirects=False,
        failure_threshold=2,
        recovery_threshold=2,
        tags=[],
    )


def _auth_source() -> AuthSource:
    return AuthSource(
        name="Login",
        mode=AuthSourceMode.OAUTH2_CLIENT_CREDENTIALS,
        request=ProbeRequest(
            method=HttpMethod.POST,
            url="https://id.example.com/login",
            headers={"X-Api-Key": "api-key-secret", "Content-Type": "application/json"},
            body='{"username":"u","password":"p"}',
        ),
        oauth=OAuthConfig(
            token_url="https://id.example.com/token",
            client_id="cid",
            client_secret="super-secret",
            scope="read",
            client_auth=ClientAuth.BASIC,
        ),
        extractor=TokenExtractor(kind=ExtractorKind.JSON_PATH, expr="$.access_token"),
        expiry=ExpirySpec(kind=ExpiryKind.JSON_PATH_SECONDS, value="$.expires_in"),
        injection=Injection(target=InjectionTarget.HEADER, name="Authorization"),
        token_type="Bearer",
        refresh_before_expiry_seconds=60,
        refresh_on_status=[401],
    )


def _token_state(source_id: object) -> TokenState:
    return TokenState(
        auth_source_id=source_id,
        token="access-xyz",
        token_type="Bearer",
        obtained_at=CLOCK_NOW,
        expires_at=CLOCK_NOW + timedelta(hours=1),
        refresh_token="refresh-abc",
    )


def _channel() -> AlertChannel:
    return AlertChannel(
        name="ops-telegram",
        type=ChannelType.TELEGRAM,
        config={"bot_token": "12345:secret-token", "chat_id": "42"},
        enabled=True,
    )


@pytest.fixture
async def seeded() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Fresh schema seeded under the OLD key ring; yields the session factory."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping Postgres re-encryption test")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = create_session_factory(engine)
    clock = FixedClock(CLOCK_NOW)
    old_box = FernetSecretBox([OLD_KEY])
    source = await SqlAuthSourceRepository(factory, clock=clock, secret_box=old_box).add(
        _auth_source()
    )
    await SqlMonitorRepository(factory, clock=clock, secret_box=old_box).add(_monitor())
    await SqlTokenStore(factory, secret_box=old_box).save(_token_state(source.id))
    await SqlAlertChannelRepository(factory, secret_box=old_box).add(_channel())
    try:
        yield factory
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
        await engine.dispose()


async def test_reencrypt_makes_all_ciphertext_readable_under_the_new_key_alone(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    # Rotate the ring (new key first, old still present) and re-encrypt.
    rotated_ring = FernetSecretBox([NEW_KEY, OLD_KEY])
    report = await ReEncryptor(seeded, rotated_ring).run()

    assert report.monitors == 1
    assert report.auth_sources == 1
    assert report.token_states == 1
    assert report.alert_channels == 1

    # Every stored ciphertext must now decrypt under the NEW key alone — proving
    # nothing depends on the old key any more, so it is safe to drop.
    new_only = FernetSecretBox([NEW_KEY])
    async with seeded() as session:
        monitor = (await session.execute(select(MonitorRow))).scalars().one()
        assert new_only.decrypt(monitor.headers["Authorization"].encode()) == "Bearer monitor-token"
        assert monitor.headers["Accept"] == "application/json"  # non-secret untouched

        source = (await session.execute(select(AuthSourceRow))).scalars().one()
        body = new_only.decrypt(source.request["body"].encode())
        assert body == '{"username":"u","password":"p"}'
        assert new_only.decrypt(source.request["headers"]["X-Api-Key"].encode()) == "api-key-secret"
        assert new_only.decrypt(source.oauth["client_secret"].encode()) == "super-secret"

        token = (await session.execute(select(TokenStateRow))).scalars().one()
        assert new_only.decrypt(token.token.encode()) == "access-xyz"
        assert new_only.decrypt(token.refresh_token.encode()) == "refresh-abc"

        channel = (await session.execute(select(AlertChannelRow))).scalars().one()
        assert new_only.decrypt(channel.config["bot_token"].encode()) == "12345:secret-token"
        assert channel.config["chat_id"] == "42"  # non-secret untouched


async def test_reencrypt_lets_the_old_key_be_dropped(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    await ReEncryptor(seeded, FernetSecretBox([NEW_KEY, OLD_KEY])).run()

    # The old key alone can no longer read what it originally wrote.
    old_only = FernetSecretBox([OLD_KEY])
    async with seeded() as session:
        token = (await session.execute(select(TokenStateRow))).scalars().one()
        with pytest.raises(InvalidToken):
            old_only.decrypt(token.token.encode())


async def test_reencrypt_is_idempotent(
    seeded: async_sessionmaker[AsyncSession],
) -> None:
    box = FernetSecretBox([NEW_KEY, OLD_KEY])
    await ReEncryptor(seeded, box).run()
    # A second pass (now everything is already under the new key) still succeeds
    # and reads back correctly — re-running is safe.
    report = await ReEncryptor(seeded, box).run()
    assert report.token_states == 1

    async with seeded() as session:
        token = (await session.execute(select(TokenStateRow))).scalars().one()
        assert FernetSecretBox([NEW_KEY]).decrypt(token.token.encode()) == "access-xyz"
