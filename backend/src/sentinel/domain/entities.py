from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from sentinel.domain.errors import ValidationError
from sentinel.domain.value_objects import (
    Assertion,
    AssertionResult,
    Auth,
    AuthSourceMode,
    BodyKind,
    ErrorKind,
    ExpirySpec,
    HttpMethod,
    Injection,
    MonitorStatus,
    OAuthConfig,
    ProbeRequest,
    TokenExtractor,
)

DEFAULT_REFRESH_BEFORE_EXPIRY_SECONDS = 60
DEFAULT_REFRESH_ON_STATUS = (401, 403)
DEFAULT_TOKEN_TYPE = "Bearer"  # noqa: S105 -- a token *type* label, not a secret

MIN_INTERVAL_SECONDS = 30
DEFAULT_INTERVAL_SECONDS = 300
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 60
DEFAULT_TIMEOUT_SECONDS = 10
MIN_THRESHOLD = 1


@dataclass
class Monitor:
    """A configured HTTP endpoint to probe (SPEC §4). Pure data + invariants;
    timestamps are assigned by the persistence/application layer, not here."""

    name: str
    url: str
    method: HttpMethod = HttpMethod.GET
    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    body_kind: BodyKind = BodyKind.NONE
    auth: Auth | None = None
    assertions: list[Assertion] = field(default_factory=list)
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    follow_redirects: bool = True
    failure_threshold: int = MIN_THRESHOLD
    recovery_threshold: int = MIN_THRESHOLD
    auth_source_id: UUID | None = None
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("monitor name must not be blank")
        if not self.url.strip():
            raise ValidationError("monitor url must not be blank")
        if self.interval_seconds < MIN_INTERVAL_SECONDS:
            raise ValidationError(f"interval_seconds must be >= {MIN_INTERVAL_SECONDS}")
        if not MIN_TIMEOUT_SECONDS <= self.timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ValidationError(
                f"timeout_seconds must be between {MIN_TIMEOUT_SECONDS} and {MAX_TIMEOUT_SECONDS}"
            )
        if self.failure_threshold < MIN_THRESHOLD:
            raise ValidationError(f"failure_threshold must be >= {MIN_THRESHOLD}")
        if self.recovery_threshold < MIN_THRESHOLD:
            raise ValidationError(f"recovery_threshold must be >= {MIN_THRESHOLD}")


@dataclass
class CheckResult:
    """The recorded outcome of one probe (SPEC §4). A fact, not a request — it has
    no invariants. Transport failures are recorded here with `success=False` and an
    `error` (never raised as an API error, SPEC §3.3); on transport failure the
    response fields (`status_code`, `latency_ms`, `response_size_bytes`) are `None`.
    When the request succeeded but an assertion failed, `error` is `assertion`."""

    monitor_id: UUID
    started_at: datetime
    finished_at: datetime
    success: bool
    status_code: int | None = None
    latency_ms: int | None = None
    response_size_bytes: int | None = None
    cert_expires_at: datetime | None = None
    error: ErrorKind | None = None
    assertion_results: list[AssertionResult] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)


@dataclass
class MonitorState:
    """The current up/down rollup for a monitor (SPEC §3.8, §4) — one row per
    monitor. Advanced by the pure `domain.logic.state` fold as each `CheckResult`
    lands: the consecutive-run counters and `last_check_at` update every check,
    while `status` and `since` move only on a confirmed threshold crossing."""

    monitor_id: UUID
    since: datetime
    status: MonitorStatus = MonitorStatus.UNKNOWN
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_check_at: datetime | None = None


@dataclass
class AuthSource:
    """A stored login/token-generating request a monitor can link to (SPEC §3.9).
    For `custom` mode the raw `request` is replayed; for `oauth2_*` modes `oauth`
    carries the structured token-request config. Credentials live in `request`/
    `oauth` and are secrets — encrypted at rest, never serialized."""

    name: str
    request: ProbeRequest
    extractor: TokenExtractor
    injection: Injection
    mode: AuthSourceMode = AuthSourceMode.CUSTOM
    oauth: OAuthConfig | None = None
    expiry: ExpirySpec | None = None
    token_type: str = DEFAULT_TOKEN_TYPE
    refresh_before_expiry_seconds: int = DEFAULT_REFRESH_BEFORE_EXPIRY_SECONDS
    refresh_on_status: list[int] = field(default_factory=lambda: list(DEFAULT_REFRESH_ON_STATUS))
    enabled: bool = True
    id: UUID = field(default_factory=uuid4)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("auth source name must not be blank")
        if self.mode is not AuthSourceMode.CUSTOM and self.oauth is None:
            raise ValidationError(f"{self.mode.value} auth source requires an oauth config")
        if self.refresh_before_expiry_seconds < 0:
            raise ValidationError("refresh_before_expiry_seconds must be >= 0")


@dataclass
class TokenState:
    """The single cached token per auth source, shared by all linked monitors
    (SPEC §3.9, §4). `token`/`refresh_token` are encrypted at rest and never
    returned or logged; `last_refresh_error` records the most recent failed
    refresh for the metadata-only status view."""

    auth_source_id: UUID
    token: str
    token_type: str
    obtained_at: datetime
    expires_at: datetime | None = None
    refresh_token: str | None = None
    last_refresh_error: str | None = None
