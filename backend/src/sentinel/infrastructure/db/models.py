"""SQLAlchemy/SQLModel table definitions. These are the persistence shape only;
the domain entities in `sentinel.domain` are the source of truth and never
import from here."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class MonitorRow(SQLModel, table=True):
    __tablename__ = "monitors"

    id: uuid.UUID = Field(primary_key=True)
    name: str
    method: str
    url: str
    headers: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    query_params: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    body: str | None = Field(default=None)
    body_kind: str
    auth: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    assertions: list[Any] = Field(sa_column=Column(JSONB, nullable=False))
    interval_seconds: int
    timeout_seconds: int
    follow_redirects: bool
    failure_threshold: int
    recovery_threshold: int
    auth_source_id: uuid.UUID | None = Field(default=None)
    enabled: bool
    tags: list[Any] = Field(sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class CheckResultRow(SQLModel, table=True):
    __tablename__ = "check_results"

    id: uuid.UUID = Field(primary_key=True)
    monitor_id: uuid.UUID = Field(index=True)
    started_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    finished_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    status_code: int | None = Field(default=None)
    latency_ms: int | None = Field(default=None)
    response_size_bytes: int | None = Field(default=None)
    cert_expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    success: bool
    error: str | None = Field(default=None)
    assertion_results: list[Any] = Field(sa_column=Column(JSONB, nullable=False))


class CheckRollupRow(SQLModel, table=True):
    """Hourly aggregate per monitor (SPEC §3.5, §4, §6). Composite primary key
    `(monitor_id, bucket_start)` — one row per hour, upserted as checks land."""

    __tablename__ = "check_rollups"

    monitor_id: uuid.UUID = Field(primary_key=True)
    bucket_start: datetime = Field(
        sa_column=Column(DateTime(timezone=True), primary_key=True, nullable=False)
    )
    checks: int
    failures: int
    latency_p50_ms: int
    latency_p95_ms: int
    latency_p99_ms: int
    latency_sum_ms: int
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class MonitorStateRow(SQLModel, table=True):
    """The current up/down rollup for a monitor (SPEC §3.8, §4) — one row per
    monitor, keyed by `monitor_id`, advanced in place as each check lands."""

    __tablename__ = "monitor_states"

    monitor_id: uuid.UUID = Field(primary_key=True)
    status: str
    since: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    consecutive_failures: int
    consecutive_successes: int
    last_check_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class AuthSourceRow(SQLModel, table=True):
    """Auth source (SPEC §3.9). `request` and `oauth` are JSONB; the secret values
    inside them (request body, secret headers, oauth client_secret/username/
    password) are stored encrypted by the repository."""

    __tablename__ = "auth_sources"

    id: uuid.UUID = Field(primary_key=True)
    name: str
    mode: str
    request: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    oauth: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    extractor: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    expiry: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    token_type: str
    injection: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    refresh_before_expiry_seconds: int
    refresh_on_status: list[Any] = Field(sa_column=Column(JSONB, nullable=False))
    enabled: bool
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class TokenStateRow(SQLModel, table=True):
    """The single cached token per auth source (SPEC §3.9, §4). `token` and
    `refresh_token` are stored encrypted. Keyed by `auth_source_id` — one row per
    source."""

    __tablename__ = "token_states"

    auth_source_id: uuid.UUID = Field(primary_key=True)
    token: str
    refresh_token: str | None = Field(default=None)
    token_type: str
    obtained_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_refresh_error: str | None = Field(default=None)
