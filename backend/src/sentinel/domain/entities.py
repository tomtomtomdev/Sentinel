from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from sentinel.domain.errors import ValidationError
from sentinel.domain.value_objects import (
    Assertion,
    AssertionResult,
    Auth,
    BodyKind,
    ErrorKind,
    HttpMethod,
)

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
