from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class BodyKind(StrEnum):
    NONE = "none"
    RAW = "raw"
    JSON = "json"
    FORM = "form"


class AuthType(StrEnum):
    NONE = "none"
    BASIC = "basic"
    BEARER = "bearer"


@dataclass(frozen=True)
class Auth:
    """Inline monitor auth. `secret_ref` points at the encrypted secret (S5a);
    the secret value itself never lives on the entity."""

    type: AuthType
    secret_ref: str | None = None


@dataclass(frozen=True)
class Assertion:
    """A single check predicate (SPEC §3.4). Carried as type + params; the pure
    `domain.logic.assertions` engine interprets them against a `ProbeResponse`."""

    type: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssertionResult:
    """Outcome of evaluating one `Assertion` (SPEC §4). `skipped` marks a
    not-applicable assertion (e.g. `cert_expiry_days` on plain HTTP); a skipped
    result is `passed=True` so it never fails the overall check."""

    type: str
    passed: bool
    detail: str
    skipped: bool = False


class ErrorKind(StrEnum):
    """Why a check failed (SPEC §4). Transport failures map to the first four;
    `assertion` means the request succeeded but a predicate failed."""

    TIMEOUT = "timeout"
    DNS = "dns"
    CONNECTION = "connection"
    TLS = "tls"
    ASSERTION = "assertion"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProbeRequest:
    """The HTTP request a probe issues (SPEC §4). A plain value object so pure
    code and tests never depend on httpx."""

    method: HttpMethod
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)
    body: str | None = None


@dataclass(frozen=True)
class ProbeResponse:
    """What a probe captured from a single response (SPEC §3.3, §4). `body_sample`
    is bounded (the adapter caps bytes); `cert_expires_at` is the TLS leaf cert's
    notAfter on HTTPS and `None` for plain HTTP. The assertion engine operates only
    on this object."""

    status_code: int
    latency_ms: int
    headers: dict[str, str] = field(default_factory=dict)
    body_sample: str = ""
    response_size_bytes: int = 0
    cert_expires_at: datetime | None = None


@dataclass
class MonitorDraft:
    """An unsaved, reviewable monitor produced by an importer (SPEC §3.1, §4).
    Deliberately carries no invariants: a draft may be incomplete and is meant to
    be edited before being saved via the create endpoint. `warnings` surface
    anything the importer could not faithfully represent."""

    name: str
    url: str
    method: HttpMethod = HttpMethod.GET
    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    body_kind: BodyKind = BodyKind.NONE
    follow_redirects: bool = False
    assertions: list[Assertion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
