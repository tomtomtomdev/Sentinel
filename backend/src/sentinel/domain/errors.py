from __future__ import annotations

# `value_objects` imports nothing from `errors`, so this stays one-directional.
from sentinel.domain.value_objects import ErrorKind


class DomainError(Exception):
    """Base class for all domain-level errors. The API layer maps these to the
    SPEC §5 error envelope; they are never leaked as raw 500s."""


class ValidationError(DomainError):
    """An entity or value object violated one of its invariants."""


class NotFoundError(DomainError):
    """A requested entity does not exist. Mapped to a 404 at the API boundary."""


class ProbeError(Exception):
    """A transport-level failure while probing (DNS, connect, TLS, timeout),
    carrying the classified `ErrorKind`. The httpx adapter raises it; the probe use
    case catches it and records a failed `CheckResult` — it is deliberately NOT a
    `DomainError`, so it never reaches the API error envelope as a 4xx/5xx
    (SPEC §3.3: probe transport problems are results, not API errors)."""

    def __init__(self, kind: ErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
