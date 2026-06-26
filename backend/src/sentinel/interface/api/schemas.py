"""API DTOs for monitors (SPEC §5). DTOs are the transport shape — they never
leak ORM rows, and secret header values are redacted in the response serializer
(sentinel-security rule 1). Domain invariants are *not* duplicated here: the
`Monitor` entity is the single source of truth for bounds, so building the entity
is what enforces them (and raises a domain `ValidationError` → 422)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from sentinel.domain.entities import (
    DEFAULT_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    MIN_THRESHOLD,
    Monitor,
)
from sentinel.domain.logic.redaction import redact
from sentinel.domain.value_objects import (
    Assertion,
    Auth,
    AuthType,
    BodyKind,
    HttpMethod,
    MonitorDraft,
)


class AuthDTO(BaseModel):
    type: AuthType
    secret_ref: str | None = None


class AssertionDTO(BaseModel):
    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class MonitorCreate(BaseModel):
    """Request body for POST /monitors. Type/shape validation only; semantic
    bounds are enforced by the `Monitor` entity."""

    name: str
    url: str
    method: HttpMethod = HttpMethod.GET
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    body: str | None = None
    body_kind: BodyKind = BodyKind.NONE
    auth: AuthDTO | None = None
    assertions: list[AssertionDTO] = Field(default_factory=list)
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    follow_redirects: bool = True
    failure_threshold: int = MIN_THRESHOLD
    recovery_threshold: int = MIN_THRESHOLD
    auth_source_id: UUID | None = None
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)

    def to_entity(self) -> Monitor:
        return Monitor(
            name=self.name,
            url=self.url,
            method=self.method,
            headers=dict(self.headers),
            query_params=dict(self.query_params),
            body=self.body,
            body_kind=self.body_kind,
            auth=_auth_to_entity(self.auth),
            assertions=[Assertion(type=a.type, params=a.params) for a in self.assertions],
            interval_seconds=self.interval_seconds,
            timeout_seconds=self.timeout_seconds,
            follow_redirects=self.follow_redirects,
            failure_threshold=self.failure_threshold,
            recovery_threshold=self.recovery_threshold,
            auth_source_id=self.auth_source_id,
            enabled=self.enabled,
            tags=list(self.tags),
        )


class MonitorUpdate(BaseModel):
    """Partial update for PATCH /monitors/{id}. Every field is optional; only
    fields present in the request are applied (`exclude_unset`)."""

    name: str | None = None
    url: str | None = None
    method: HttpMethod | None = None
    headers: dict[str, str] | None = None
    query_params: dict[str, str] | None = None
    body: str | None = None
    body_kind: BodyKind | None = None
    auth: AuthDTO | None = None
    assertions: list[AssertionDTO] | None = None
    interval_seconds: int | None = None
    timeout_seconds: int | None = None
    follow_redirects: bool | None = None
    failure_threshold: int | None = None
    recovery_threshold: int | None = None
    auth_source_id: UUID | None = None
    enabled: bool | None = None
    tags: list[str] | None = None

    def apply_to(self, existing: Monitor) -> Monitor:
        """Return a new `Monitor` with the set fields applied. Reconstruction
        re-runs the entity invariants, so an invalid patch raises ValidationError."""
        changes: dict[str, Any] = {}
        for name in self.model_fields_set:
            value = getattr(self, name)
            if name == "auth":
                changes["auth"] = _auth_to_entity(value)
            elif name == "assertions":
                changes["assertions"] = [Assertion(type=a.type, params=a.params) for a in value]
            elif name == "method":
                changes["method"] = HttpMethod(value)
            elif name == "body_kind":
                changes["body_kind"] = BodyKind(value)
            else:
                changes[name] = value
        return replace(existing, **changes)


class MonitorResponse(BaseModel):
    """Full monitor with secret header values redacted (SPEC §5)."""

    id: UUID
    name: str
    method: HttpMethod
    url: str
    headers: dict[str, str]
    query_params: dict[str, str]
    body: str | None
    body_kind: BodyKind
    auth: AuthDTO | None
    assertions: list[AssertionDTO]
    interval_seconds: int
    timeout_seconds: int
    follow_redirects: bool
    failure_threshold: int
    recovery_threshold: int
    auth_source_id: UUID | None
    enabled: bool
    tags: list[str]
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_entity(cls, monitor: Monitor) -> MonitorResponse:
        return cls(
            id=monitor.id,
            name=monitor.name,
            method=monitor.method,
            url=monitor.url,
            headers=redact(monitor.headers),
            query_params=monitor.query_params,
            body=monitor.body,
            body_kind=monitor.body_kind,
            auth=AuthDTO(type=monitor.auth.type, secret_ref=monitor.auth.secret_ref)
            if monitor.auth
            else None,
            assertions=[AssertionDTO(type=a.type, params=a.params) for a in monitor.assertions],
            interval_seconds=monitor.interval_seconds,
            timeout_seconds=monitor.timeout_seconds,
            follow_redirects=monitor.follow_redirects,
            failure_threshold=monitor.failure_threshold,
            recovery_threshold=monitor.recovery_threshold,
            auth_source_id=monitor.auth_source_id,
            enabled=monitor.enabled,
            tags=list(monitor.tags),
            created_at=monitor.created_at,
            updated_at=monitor.updated_at,
        )


def _auth_to_entity(auth: AuthDTO | None) -> Auth | None:
    if auth is None:
        return None
    return Auth(type=AuthType(auth.type), secret_ref=auth.secret_ref)


class CurlImportRequest(BaseModel):
    command: str


class MonitorDraftResponse(BaseModel):
    """An importer's parsed draft (SPEC §3.1, §5). Unlike `MonitorResponse`, draft
    headers are NOT redacted: the draft is an echo of the user's own input shown
    for review before saving, and masking would corrupt the value the client posts
    back to create the monitor. Nothing here is persisted."""

    name: str
    method: HttpMethod
    url: str
    headers: dict[str, str]
    query_params: dict[str, str]
    body: str | None
    body_kind: BodyKind
    follow_redirects: bool
    assertions: list[AssertionDTO]
    warnings: list[str]

    @classmethod
    def from_draft(cls, draft: MonitorDraft) -> MonitorDraftResponse:
        return cls(
            name=draft.name,
            method=draft.method,
            url=draft.url,
            headers=draft.headers,
            query_params=draft.query_params,
            body=draft.body,
            body_kind=draft.body_kind,
            follow_redirects=draft.follow_redirects,
            assertions=[AssertionDTO(type=a.type, params=a.params) for a in draft.assertions],
            warnings=draft.warnings,
        )


class ImportResponse(BaseModel):
    """Shared response for every importer (SPEC §5): reviewable drafts, nothing
    persisted. The client saves drafts via the normal create endpoint."""

    drafts: list[MonitorDraftResponse]
