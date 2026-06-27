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


# --- Auth source / token provider (SPEC §3.9, §4) ---------------------------


class AuthSourceMode(StrEnum):
    """How Sentinel obtains a token from an auth source. `custom` replays the
    stored raw request; the `oauth2_*` modes build the standard token request from
    structured `OAuthConfig` fields."""

    CUSTOM = "custom"
    OAUTH2_CLIENT_CREDENTIALS = "oauth2_client_credentials"
    OAUTH2_PASSWORD = "oauth2_password"  # noqa: S105 -- grant-mode label, not a secret
    OAUTH2_REFRESH = "oauth2_refresh"


class ExtractorKind(StrEnum):
    """Where the access token is read from in the login response."""

    JSON_PATH = "json_path"
    HEADER = "header"
    REGEX = "regex"


class ExpiryKind(StrEnum):
    """How a token's expiry is derived. `json_path_seconds` reads a relative
    lifetime (e.g. `expires_in`), `absolute_path` an absolute timestamp,
    `ttl_seconds` a fixed configured lifetime."""

    JSON_PATH_SECONDS = "json_path_seconds"
    ABSOLUTE_PATH = "absolute_path"
    TTL_SECONDS = "ttl_seconds"


class InjectionTarget(StrEnum):
    """Where a dependent monitor's probe carries the token."""

    HEADER = "header"
    QUERY = "query"
    BODY = "body"


class ClientAuth(StrEnum):
    """How OAuth2 client credentials are presented: in the form body
    (`client_secret_post`) or an HTTP Basic header (`client_secret_basic`)."""

    BODY = "body"
    BASIC = "basic"


class OAuthGrant(StrEnum):
    """The OAuth2 grant a token request uses. The auth-source `mode` selects the
    primary grant; `refresh_token` is used for refresh-token reuse regardless."""

    CLIENT_CREDENTIALS = "client_credentials"
    PASSWORD = "password"  # noqa: S105 -- OAuth grant name, not a secret
    REFRESH_TOKEN = "refresh_token"  # noqa: S105 -- OAuth grant name, not a secret


@dataclass(frozen=True)
class TokenExtractor:
    """Reads the access token out of a login response (SPEC §3.9). For
    `json_path`/`header`, `expr` is the path/header name; for `regex`, the first
    capturing group (or whole match) is the token."""

    kind: ExtractorKind
    expr: str


@dataclass(frozen=True)
class ExpirySpec:
    """How to compute a token's expiry. `value` is a JSONPath for the path kinds
    and a seconds count for `ttl_seconds`. `None` (no `ExpirySpec`) means
    refresh-on-401 only."""

    kind: ExpiryKind
    value: str | int


@dataclass(frozen=True)
class Injection:
    """How dependent monitors carry the token (SPEC §3.9). The rendered value is
    `value_template` with `{token_type}`/`{token}` substituted."""

    target: InjectionTarget
    name: str
    value_template: str = "{token_type} {token}"


@dataclass(frozen=True)
class OAuthConfig:
    """Structured OAuth2 token-request config (SPEC §4). `client_secret`,
    `username`, and `password` are secrets (encrypted at rest). `username`/
    `password` back the `oauth2_password` grant."""

    token_url: str
    client_id: str
    client_secret: str | None = None
    scope: str | None = None
    client_auth: ClientAuth = ClientAuth.BODY
    username: str | None = None
    password: str | None = None


@dataclass(frozen=True)
class Token:
    """A freshly extracted token (SPEC §4 value object). `token_type` is governed
    by the auth-source config, so it is not carried here."""

    value: str
    expires_at: datetime | None = None
    refresh_token: str | None = None


@dataclass(frozen=True)
class InjectionPlan:
    """The decision to inject an already-valid cached token: the injection spec
    plus the resolved token + type to render into it (`resolve_auth` output)."""

    injection: Injection
    token: str
    token_type: str


@dataclass(frozen=True)
class NeedsRefresh:
    """`resolve_auth` outcome meaning the cached token is missing, expired, or
    inside the proactive refresh window and must be regenerated first."""

    reason: str


class TokenStatus(StrEnum):
    """The metadata-only health of an auth source's cached token (SPEC §3.9). Used
    in API responses — the token value itself is never returned."""

    VALID = "valid"
    EXPIRED = "expired"
    ERROR = "error"
    NONE = "none"
