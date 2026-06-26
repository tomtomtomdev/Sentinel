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
