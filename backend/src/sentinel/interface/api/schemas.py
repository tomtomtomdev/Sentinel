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

from sentinel.application.stats_service import MonitorSummary, StatsView
from sentinel.domain.entities import (
    DEFAULT_INTERVAL_SECONDS,
    DEFAULT_REFRESH_BEFORE_EXPIRY_SECONDS,
    DEFAULT_REFRESH_ON_STATUS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TOKEN_TYPE,
    MIN_THRESHOLD,
    AlertChannel,
    AuthSource,
    CheckResult,
    Monitor,
    TokenState,
)
from sentinel.domain.logic.auth import token_status
from sentinel.domain.logic.redaction import MASK, redact, redact_config
from sentinel.domain.value_objects import (
    Assertion,
    Auth,
    AuthSourceMode,
    AuthType,
    BodyKind,
    ChannelType,
    ClientAuth,
    ErrorKind,
    ExpiryKind,
    ExpirySpec,
    ExtractorKind,
    HttpMethod,
    Injection,
    InjectionTarget,
    MonitorDraft,
    MonitorStatus,
    OAuthConfig,
    ProbeRequest,
    TokenExtractor,
    TokenStatus,
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


class MonitorSummaryDTO(BaseModel):
    """The 24h dashboard rollup attached to each monitor under `?include=summary`
    (SPEC §3.5): current status + uptime, p95 latency, and last-check time.
    `checks == 0` marks "no data yet" so the UI can distinguish it from 0% uptime."""

    status: MonitorStatus
    since: datetime | None
    last_check_at: datetime | None
    uptime_pct: float
    latency_p95_ms: int | None
    checks: int

    @classmethod
    def from_summary(cls, summary: MonitorSummary) -> MonitorSummaryDTO:
        return cls(
            status=summary.status,
            since=summary.since,
            last_check_at=summary.last_check_at,
            uptime_pct=summary.uptime_pct,
            latency_p95_ms=summary.latency_p95_ms,
            checks=summary.checks,
        )


class MonitorResponse(BaseModel):
    """Full monitor with secret header values redacted (SPEC §5). `summary` is
    populated only for the list view's `?include=summary` and is `None` otherwise."""

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
    summary: MonitorSummaryDTO | None = None

    @classmethod
    def from_entity(
        cls, monitor: Monitor, summary: MonitorSummaryDTO | None = None
    ) -> MonitorResponse:
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
            summary=summary,
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


class AssertionResultDTO(BaseModel):
    type: str
    passed: bool
    detail: str
    skipped: bool


class CheckResultResponse(BaseModel):
    """The outcome of one probe (SPEC §4). On a transport failure the response
    fields are null and `error` is the transport `ErrorKind`; a failed assertion
    sets `error=assertion`. No secret request data or full body is stored here."""

    id: UUID
    monitor_id: UUID
    started_at: datetime
    finished_at: datetime
    status_code: int | None
    latency_ms: int | None
    response_size_bytes: int | None
    cert_expires_at: datetime | None
    success: bool
    error: ErrorKind | None
    assertion_results: list[AssertionResultDTO]

    @classmethod
    def from_entity(cls, result: CheckResult) -> CheckResultResponse:
        return cls(
            id=result.id,
            monitor_id=result.monitor_id,
            started_at=result.started_at,
            finished_at=result.finished_at,
            status_code=result.status_code,
            latency_ms=result.latency_ms,
            response_size_bytes=result.response_size_bytes,
            cert_expires_at=result.cert_expires_at,
            success=result.success,
            error=result.error,
            assertion_results=[
                AssertionResultDTO(type=a.type, passed=a.passed, detail=a.detail, skipped=a.skipped)
                for a in result.assertion_results
            ],
        )


class LatencyPercentilesDTO(BaseModel):
    """Nearest-rank latency percentiles over the window (SPEC §5). Each is `None`
    when no timed result fell in the window (all transport failures / no data)."""

    p50: int | None
    p95: int | None
    p99: int | None


class StatsResponse(BaseModel):
    """Uptime/latency over a window joined with live status/since (SPEC §3.5, §5).
    Short windows are computed from raw `CheckResult`s here; S7a serves the long
    windows from hourly rollups."""

    window: str
    checks: int
    failures: int
    uptime_pct: float
    latency_ms: LatencyPercentilesDTO
    status: MonitorStatus
    since: datetime | None

    @classmethod
    def from_view(cls, view: StatsView) -> StatsResponse:
        stats = view.stats
        return cls(
            window=stats.window,
            checks=stats.checks,
            failures=stats.failures,
            uptime_pct=stats.uptime_pct,
            latency_ms=LatencyPercentilesDTO(
                p50=stats.latency_p50_ms,
                p95=stats.latency_p95_ms,
                p99=stats.latency_p99_ms,
            ),
            status=view.status,
            since=view.since,
        )


# --- Auth source (SPEC §3.9, §5) --------------------------------------------


class ProbeRequestDTO(BaseModel):
    """The auth source's stored login request. In responses the `body`
    (credentials) and secret headers are redacted; in requests they carry the
    real values to persist (encrypted at rest)."""

    method: HttpMethod = HttpMethod.GET
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    body: str | None = None

    def to_value(self) -> ProbeRequest:
        return ProbeRequest(
            method=self.method,
            url=self.url,
            headers=dict(self.headers),
            query_params=dict(self.query_params),
            body=self.body,
        )


class OAuthConfigDTO(BaseModel):
    token_url: str
    client_id: str
    client_secret: str | None = None
    scope: str | None = None
    client_auth: ClientAuth = ClientAuth.BODY
    username: str | None = None
    password: str | None = None

    def to_value(self) -> OAuthConfig:
        return OAuthConfig(
            token_url=self.token_url,
            client_id=self.client_id,
            client_secret=self.client_secret,
            scope=self.scope,
            client_auth=self.client_auth,
            username=self.username,
            password=self.password,
        )


class TokenExtractorDTO(BaseModel):
    kind: ExtractorKind
    expr: str


class ExpirySpecDTO(BaseModel):
    kind: ExpiryKind
    value: int | str


class InjectionDTO(BaseModel):
    target: InjectionTarget
    name: str
    value_template: str = "{token_type} {token}"


class TokenStateSummary(BaseModel):
    """Metadata-only view of a cached token (SPEC §3.9). Never carries the token
    value — only its derived `status` and timing."""

    status: TokenStatus
    obtained_at: datetime | None
    expires_at: datetime | None
    last_refresh_error: str | None

    @classmethod
    def from_state(cls, state: TokenState | None, now: datetime) -> TokenStateSummary:
        return cls(
            status=token_status(state, now),
            obtained_at=state.obtained_at if state else None,
            expires_at=state.expires_at if state else None,
            last_refresh_error=state.last_refresh_error if state else None,
        )


class AuthSourceCreate(BaseModel):
    """Request body for POST /auth-sources. Shape validation only; semantic
    invariants (e.g. oauth required for oauth2_* modes) are enforced by the
    `AuthSource` entity and surface as a `validation_error`."""

    name: str
    mode: AuthSourceMode = AuthSourceMode.CUSTOM
    request: ProbeRequestDTO
    oauth: OAuthConfigDTO | None = None
    extractor: TokenExtractorDTO
    expiry: ExpirySpecDTO | None = None
    token_type: str = DEFAULT_TOKEN_TYPE
    injection: InjectionDTO
    refresh_before_expiry_seconds: int = DEFAULT_REFRESH_BEFORE_EXPIRY_SECONDS
    refresh_on_status: list[int] = Field(default_factory=lambda: list(DEFAULT_REFRESH_ON_STATUS))
    enabled: bool = True

    def to_entity(self) -> AuthSource:
        return AuthSource(
            name=self.name,
            mode=self.mode,
            request=self.request.to_value(),
            oauth=self.oauth.to_value() if self.oauth else None,
            extractor=TokenExtractor(kind=self.extractor.kind, expr=self.extractor.expr),
            expiry=ExpirySpec(kind=self.expiry.kind, value=self.expiry.value)
            if self.expiry
            else None,
            token_type=self.token_type,
            injection=Injection(
                target=self.injection.target,
                name=self.injection.name,
                value_template=self.injection.value_template,
            ),
            refresh_before_expiry_seconds=self.refresh_before_expiry_seconds,
            refresh_on_status=list(self.refresh_on_status),
            enabled=self.enabled,
        )


class AuthSourceUpdate(BaseModel):
    """Partial update for PATCH /auth-sources/{id}. Reconstruction re-runs the
    entity invariants, so an invalid patch raises ValidationError → 422."""

    name: str | None = None
    mode: AuthSourceMode | None = None
    request: ProbeRequestDTO | None = None
    oauth: OAuthConfigDTO | None = None
    extractor: TokenExtractorDTO | None = None
    expiry: ExpirySpecDTO | None = None
    token_type: str | None = None
    injection: InjectionDTO | None = None
    refresh_before_expiry_seconds: int | None = None
    refresh_on_status: list[int] | None = None
    enabled: bool | None = None

    def apply_to(self, existing: AuthSource) -> AuthSource:
        changes: dict[str, Any] = {}
        for name in self.model_fields_set:
            value = getattr(self, name)
            if name == "request":
                changes["request"] = value.to_value()
            elif name == "oauth":
                changes["oauth"] = value.to_value() if value is not None else None
            elif name == "extractor":
                changes["extractor"] = TokenExtractor(kind=value.kind, expr=value.expr)
            elif name == "expiry":
                changes["expiry"] = (
                    ExpirySpec(kind=value.kind, value=value.value) if value is not None else None
                )
            elif name == "injection":
                changes["injection"] = Injection(
                    target=value.target, name=value.name, value_template=value.value_template
                )
            elif name == "mode":
                changes["mode"] = AuthSourceMode(value)
            else:
                changes[name] = value
        return replace(existing, **changes)


class AuthSourceResponse(BaseModel):
    """Full auth source with every credential redacted (SPEC §3.9, §6): the
    request body and secret headers are masked, and oauth `client_secret`/
    `password` are masked. The token value is never present; an optional
    `token_state` carries metadata only."""

    id: UUID
    name: str
    mode: AuthSourceMode
    request: ProbeRequestDTO
    oauth: OAuthConfigDTO | None
    extractor: TokenExtractorDTO
    expiry: ExpirySpecDTO | None
    token_type: str
    injection: InjectionDTO
    refresh_before_expiry_seconds: int
    refresh_on_status: list[int]
    enabled: bool
    created_at: datetime | None
    updated_at: datetime | None
    token_state: TokenStateSummary | None = None

    @classmethod
    def from_entity(
        cls, source: AuthSource, token_state: TokenStateSummary | None = None
    ) -> AuthSourceResponse:
        return cls(
            id=source.id,
            name=source.name,
            mode=source.mode,
            request=_redact_request_dto(source.request),
            oauth=_redact_oauth_dto(source.oauth),
            extractor=TokenExtractorDTO(kind=source.extractor.kind, expr=source.extractor.expr),
            expiry=ExpirySpecDTO(kind=source.expiry.kind, value=source.expiry.value)
            if source.expiry
            else None,
            token_type=source.token_type,
            injection=InjectionDTO(
                target=source.injection.target,
                name=source.injection.name,
                value_template=source.injection.value_template,
            ),
            refresh_before_expiry_seconds=source.refresh_before_expiry_seconds,
            refresh_on_status=list(source.refresh_on_status),
            enabled=source.enabled,
            created_at=source.created_at,
            updated_at=source.updated_at,
            token_state=token_state,
        )


def _redact_request_dto(req: ProbeRequest) -> ProbeRequestDTO:
    return ProbeRequestDTO(
        method=req.method,
        url=req.url,
        headers=redact(req.headers),
        query_params=dict(req.query_params),
        body=MASK if req.body else None,
    )


def _redact_oauth_dto(oauth: OAuthConfig | None) -> OAuthConfigDTO | None:
    if oauth is None:
        return None
    return OAuthConfigDTO(
        token_url=oauth.token_url,
        client_id=oauth.client_id,
        client_secret=MASK if oauth.client_secret else None,
        scope=oauth.scope,
        client_auth=oauth.client_auth,
        username=oauth.username,
        password=MASK if oauth.password else None,
    )


# --- Alert channels (SPEC §3.7, §5) -----------------------------------------


class AlertChannelCreate(BaseModel):
    """Request body for POST /channels. Shape validation only; the `name`
    non-blank invariant is enforced by the `AlertChannel` entity → 422. `config`
    carries the real secret values to persist (encrypted at rest)."""

    name: str
    type: ChannelType
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    def to_entity(self) -> AlertChannel:
        return AlertChannel(
            name=self.name,
            type=self.type,
            config=dict(self.config),
            enabled=self.enabled,
        )


class AlertChannelUpdate(BaseModel):
    """Partial update for PATCH /channels/{id}. Only set fields are applied;
    passing `config` replaces it wholesale (secrets included)."""

    name: str | None = None
    type: ChannelType | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None

    def apply_to(self, existing: AlertChannel) -> AlertChannel:
        changes: dict[str, Any] = {}
        for name in self.model_fields_set:
            value = getattr(self, name)
            if name == "type":
                changes["type"] = ChannelType(value)
            elif name == "config":
                changes["config"] = dict(value) if value is not None else {}
            else:
                changes[name] = value
        return replace(existing, **changes)


class AlertChannelResponse(BaseModel):
    """A channel with secret `config` values masked (SPEC §3.7, §6). The key is
    kept so the user sees the setting exists, but no secret value is ever returned."""

    id: UUID
    type: ChannelType
    name: str
    config: dict[str, Any]
    enabled: bool

    @classmethod
    def from_entity(cls, channel: AlertChannel) -> AlertChannelResponse:
        return cls(
            id=channel.id,
            type=channel.type,
            name=channel.name,
            config=redact_config(channel.config),
            enabled=channel.enabled,
        )
