"""Postgres-backed `AlertChannelRepository` + `NotificationLogRepository`
(SPEC §3.7, §4). Maps between the domain entities and their table rows.

An `AlertChannel`'s secret `config` values are encrypted at rest via the injected
`SecretBox` (SPEC §6): they are ciphertext in the JSONB column and plaintext on the
entity. Which keys are secret is the shared `is_secret_config_key` classifier, so
at-rest encryption and API redaction can never drift (cf. PLAN D18). The
notification log carries no secrets, so it needs no `SecretBox`."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import col, select

from sentinel.domain.entities import AlertChannel, NotificationLog
from sentinel.domain.ports import SecretBox
from sentinel.domain.value_objects import ChannelType, MonitorStatus
from sentinel.infrastructure.db.models import AlertChannelRow, NotificationLogRow
from sentinel.infrastructure.db.secret_mapping import decrypt_secret_config, encrypt_secret_config


def _channel_to_row(channel: AlertChannel, box: SecretBox) -> AlertChannelRow:
    return AlertChannelRow(
        id=channel.id,
        type=channel.type.value,
        name=channel.name,
        config=encrypt_secret_config(channel.config, box),
        enabled=channel.enabled,
    )


def _channel_to_entity(row: AlertChannelRow, box: SecretBox) -> AlertChannel:
    return AlertChannel(
        id=row.id,
        name=row.name,
        type=ChannelType(row.type),
        config=decrypt_secret_config(row.config, box),
        enabled=row.enabled,
    )


_CHANNEL_MUTABLE_FIELDS = ("type", "name", "config", "enabled")


class SqlAlertChannelRepository:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], secret_box: SecretBox
    ) -> None:
        self._session_factory = session_factory
        self._secret_box = secret_box

    async def add(self, channel: AlertChannel) -> AlertChannel:
        row = _channel_to_row(channel, self._secret_box)
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _channel_to_entity(row, self._secret_box)

    async def get(self, channel_id: UUID) -> AlertChannel | None:
        async with self._session_factory() as session:
            row = await session.get(AlertChannelRow, channel_id)
            return _channel_to_entity(row, self._secret_box) if row is not None else None

    async def list(self) -> list[AlertChannel]:
        async with self._session_factory() as session:
            result = await session.execute(select(AlertChannelRow))
            return [_channel_to_entity(row, self._secret_box) for row in result.scalars().all()]

    async def update(self, channel: AlertChannel) -> AlertChannel:
        async with self._session_factory() as session:
            row = await session.get(AlertChannelRow, channel.id)
            if row is None:
                raise LookupError(channel.id)
            new = _channel_to_row(channel, self._secret_box)
            for field_name in _CHANNEL_MUTABLE_FIELDS:
                setattr(row, field_name, getattr(new, field_name))
            await session.commit()
            await session.refresh(row)
            return _channel_to_entity(row, self._secret_box)

    async def delete(self, channel_id: UUID) -> bool:
        async with self._session_factory() as session:
            row = await session.get(AlertChannelRow, channel_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True


def _log_to_row(entry: NotificationLog) -> NotificationLogRow:
    return NotificationLogRow(
        id=entry.id,
        channel_id=entry.channel_id,
        monitor_id=entry.monitor_id,
        transition_to=entry.transition_to.value,
        transition_at=entry.transition_at,
        fired_at=entry.fired_at,
        ok=entry.ok,
        detail=entry.detail,
    )


def _log_to_entity(row: NotificationLogRow) -> NotificationLog:
    return NotificationLog(
        id=row.id,
        channel_id=row.channel_id,
        monitor_id=row.monitor_id,
        transition_to=MonitorStatus(row.transition_to),
        transition_at=row.transition_at,
        fired_at=row.fired_at,
        ok=row.ok,
        detail=row.detail,
    )


class SqlNotificationLogRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, entry: NotificationLog) -> NotificationLog:
        row = _log_to_row(entry)
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _log_to_entity(row)

    async def exists(self, *, channel_id: UUID, monitor_id: UUID, transition_at: datetime) -> bool:
        async with self._session_factory() as session:
            stmt = select(col(NotificationLogRow.id)).where(
                col(NotificationLogRow.channel_id) == channel_id,
                col(NotificationLogRow.monitor_id) == monitor_id,
                col(NotificationLogRow.transition_at) == transition_at,
            )
            result = await session.execute(stmt)
            return result.first() is not None

    async def list_for_monitor(
        self, monitor_id: UUID, *, limit: int | None = 100
    ) -> list[NotificationLog]:
        async with self._session_factory() as session:
            stmt = (
                select(NotificationLogRow)
                .where(col(NotificationLogRow.monitor_id) == monitor_id)
                .order_by(col(NotificationLogRow.fired_at).desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return [_log_to_entity(row) for row in result.scalars().all()]
