from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from sentinel.domain.errors import ValidationError
from sentinel.domain.value_objects import Assertion, Auth, BodyKind, HttpMethod

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
