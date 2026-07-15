"""Repository contract for alert channels + notification log (SPEC §3.7, §4) —
runs against the in-memory fakes and (when TEST_DATABASE_URL is set) real Postgres;
both must behave identically. A Postgres-only test additionally asserts channel
config secrets persist as ciphertext, never plaintext (SPEC §6)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from sentinel.domain.entities import AlertChannel, NotificationLog
from sentinel.domain.ports import AlertChannelRepository, NotificationLogRepository
from sentinel.domain.value_objects import ChannelType, MonitorStatus
from sentinel.infrastructure.db import models  # noqa: F401  -- register tables on metadata
from sentinel.infrastructure.db.alert_channel_repository import (
    SqlAlertChannelRepository,
    SqlNotificationLogRepository,
)
from sentinel.infrastructure.db.engine import create_session_factory
from sentinel.infrastructure.db.models import AlertChannelRow
from sentinel.infrastructure.secrets import FernetSecretBox
from tests.support.fakes import (
    InMemoryAlertChannelRepository,
    InMemoryNotificationLogRepository,
)

TEST_SECRET_KEY = Fernet.generate_key().decode()
T0 = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def sample_channel(**overrides: object) -> AlertChannel:
    params: dict[str, object] = {
        "name": "ops-telegram",
        "type": ChannelType.TELEGRAM,
        "config": {"bot_token": "12345:secret-token", "chat_id": "42"},
        "enabled": True,
    }
    params.update(overrides)
    return AlertChannel(**params)  # type: ignore[arg-type]


@pytest.fixture(params=["memory", "postgres"])
async def channel_repo(request: pytest.FixtureRequest) -> AsyncIterator[AlertChannelRepository]:
    if request.param == "memory":
        yield InMemoryAlertChannelRepository()
        return

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping Postgres alert-channel contract")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    try:
        yield SqlAlertChannelRepository(
            create_session_factory(engine), secret_box=FernetSecretBox([TEST_SECRET_KEY])
        )
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
        await engine.dispose()


@pytest.fixture(params=["memory", "postgres"])
async def notif_repo(request: pytest.FixtureRequest) -> AsyncIterator[NotificationLogRepository]:
    if request.param == "memory":
        yield InMemoryNotificationLogRepository()
        return

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping Postgres notification-log contract")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    try:
        yield SqlNotificationLogRepository(create_session_factory(engine))
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
        await engine.dispose()


# ------------------------------------------------------- AlertChannelRepository


async def test_add_then_get_round_trips(channel_repo: AlertChannelRepository) -> None:
    created = await channel_repo.add(sample_channel())
    fetched = await channel_repo.get(created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.name == "ops-telegram"
    assert fetched.type is ChannelType.TELEGRAM
    assert fetched.config == {"bot_token": "12345:secret-token", "chat_id": "42"}
    assert fetched.enabled is True


async def test_get_unknown_returns_none(channel_repo: AlertChannelRepository) -> None:
    assert await channel_repo.get(uuid4()) is None


async def test_list_returns_all_added(channel_repo: AlertChannelRepository) -> None:
    a = await channel_repo.add(sample_channel(name="A"))
    b = await channel_repo.add(sample_channel(name="B"))
    listed = await channel_repo.list()
    assert {c.id for c in listed} == {a.id, b.id}


async def test_update_persists(channel_repo: AlertChannelRepository) -> None:
    created = await channel_repo.add(sample_channel())
    created.name = "renamed"
    created.enabled = False
    created.config = {"bot_token": "99999:new", "chat_id": "7"}

    updated = await channel_repo.update(created)
    assert updated.name == "renamed"
    assert updated.enabled is False

    refetched = await channel_repo.get(created.id)
    assert refetched is not None
    assert refetched.name == "renamed"
    assert refetched.config == {"bot_token": "99999:new", "chat_id": "7"}


async def test_update_unknown_raises_lookup(channel_repo: AlertChannelRepository) -> None:
    with pytest.raises(LookupError):
        await channel_repo.update(sample_channel())


async def test_delete_removes_and_reports(channel_repo: AlertChannelRepository) -> None:
    created = await channel_repo.add(sample_channel())
    assert await channel_repo.delete(created.id) is True
    assert await channel_repo.get(created.id) is None
    assert await channel_repo.delete(created.id) is False


# ---------------------------------------------------- NotificationLogRepository


def _log(**overrides: object) -> NotificationLog:
    params: dict[str, object] = {
        "channel_id": uuid4(),
        "monitor_id": uuid4(),
        "transition_to": MonitorStatus.DOWN,
        "transition_at": T0,
        "fired_at": T0 + timedelta(seconds=1),
        "ok": True,
        "detail": None,
    }
    params.update(overrides)
    return NotificationLog(**params)  # type: ignore[arg-type]


async def test_add_then_list_for_monitor(notif_repo: NotificationLogRepository) -> None:
    monitor_id = uuid4()
    entry = _log(monitor_id=monitor_id, transition_to=MonitorStatus.DOWN, detail="sent")
    await notif_repo.add(entry)

    listed = await notif_repo.list_for_monitor(monitor_id)
    assert len(listed) == 1
    assert listed[0].transition_to is MonitorStatus.DOWN
    assert listed[0].ok is True
    assert listed[0].detail == "sent"


async def test_exists_keys_on_channel_monitor_transition_at(
    notif_repo: NotificationLogRepository,
) -> None:
    channel_id, monitor_id = uuid4(), uuid4()
    await notif_repo.add(_log(channel_id=channel_id, monitor_id=monitor_id, transition_at=T0))

    # Same (channel, monitor, transition_at) → already fired.
    assert (
        await notif_repo.exists(channel_id=channel_id, monitor_id=monitor_id, transition_at=T0)
        is True
    )
    # A different transition time for the same channel/monitor → not fired.
    assert (
        await notif_repo.exists(
            channel_id=channel_id, monitor_id=monitor_id, transition_at=T0 + timedelta(minutes=5)
        )
        is False
    )
    # A different channel for the same transition → not fired.
    assert (
        await notif_repo.exists(channel_id=uuid4(), monitor_id=monitor_id, transition_at=T0)
        is False
    )


# --------------------------------------------------------- at-rest encryption


async def test_channel_config_secret_is_encrypted_at_rest() -> None:
    """SPEC §6 — a channel's secret config values persist as ciphertext; `get`
    transparently decrypts. Postgres-only (inspects the raw row)."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping at-rest encryption check")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    box = FernetSecretBox([TEST_SECRET_KEY])
    factory = create_session_factory(engine)
    repo = SqlAlertChannelRepository(factory, secret_box=box)
    try:
        created = await repo.add(sample_channel())

        async with factory() as session:
            row = await session.get(AlertChannelRow, created.id)
            assert row is not None
            assert row.config["bot_token"] != "12345:secret-token"
            assert box.decrypt(row.config["bot_token"].encode()) == "12345:secret-token"
            assert row.config["chat_id"] == "42"  # non-secret stays plaintext

        fetched = await repo.get(created.id)
        assert fetched is not None
        assert fetched.config["bot_token"] == "12345:secret-token"
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
        await engine.dispose()
