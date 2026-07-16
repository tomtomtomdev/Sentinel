from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


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
    `assertion` means the request succeeded but a predicate failed; `blocked`
    means the SSRF guard refused the URL before anything was sent (SPEC §6)."""

    TIMEOUT = "timeout"
    DNS = "dns"
    CONNECTION = "connection"
    TLS = "tls"
    ASSERTION = "assertion"
    BLOCKED = "blocked"
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


# --- State, stats & history (SPEC §3.5, §3.8, §4) ---------------------------


class MonitorStatus(StrEnum):
    """Current health of a monitor (SPEC §3.8). `unknown` until the first check
    confirms `up` or `down`."""

    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"


class StatsWindow(StrEnum):
    """A supported stats window (SPEC §3.5). In S7 every window is computed from
    raw `CheckResult`s; S7a will serve the long windows from hourly rollups."""

    H24 = "24h"
    D7 = "7d"
    D30 = "30d"


@dataclass(frozen=True)
class StateTransition:
    """A confirmed up↔down status change (SPEC §3.8, §4). Only confirmed
    transitions create alerts and `status_changed` events (S8/S9). `at` is the
    time of the check that confirmed the flip."""

    monitor_id: UUID
    from_status: MonitorStatus
    to_status: MonitorStatus
    at: datetime


@dataclass(frozen=True)
class CheckCompleted:
    """A `check_completed` live event (SPEC §3.6) — a small, secret-free summary of
    one recorded check, pushed to connected SSE clients so dashboards update without
    polling. Deliberately narrower than the `CheckResult` entity (no body sample, no
    assertion detail) so no probed/injected value can ever leak over the stream."""

    monitor_id: UUID
    at: datetime
    success: bool
    status_code: int | None = None
    latency_ms: int | None = None
    error: ErrorKind | None = None


# A live event carried by the `EventBus` (SPEC §3.6). `StatusChanged` is just the
# confirmed `StateTransition`; the interface layer serializes each to its SSE frame.
Event = CheckCompleted | StateTransition


# --- Alerting (SPEC §3.7) ---------------------------------------------------


class ChannelType(StrEnum):
    """How an alert is delivered (SPEC §3.7). Each type interprets the channel's
    `config` dict its own way; secret config values are encrypted at rest and
    redacted in responses."""

    WEBHOOK = "webhook"
    TELEGRAM = "telegram"
    EMAIL = "email"


class NotifyKind(StrEnum):
    """What a `should_notify` decision calls for (SPEC §3.7). `transition` is a
    normal per-flip alert; `flapping` is the single summary emitted when a monitor
    crosses the flap threshold; `suppressed` means no alert (already flapping, or
    inside the re-notify cooldown)."""

    TRANSITION = "transition"
    FLAPPING = "flapping"
    SUPPRESSED = "suppressed"


@dataclass(frozen=True)
class AlertPolicy:
    """Tunables for the pure notify decision (SPEC §3.7). `flap_threshold`
    transitions within `flap_window_seconds` trip a single "flapping" summary and
    suppress further per-transition alerts until the monitor stabilizes; a
    `flap_threshold < 2` disables flap damping (a flip needs at least two
    transitions to flap). `renotify_after_seconds` (0 = off, the default) rate-limits
    a repeat alert for the same status."""

    flap_threshold: int = 5
    flap_window_seconds: int = 600
    renotify_after_seconds: int = 0


@dataclass(frozen=True)
class RetentionPolicy:
    """How long history is kept (SPEC §6 retention). Raw `CheckResult`s and the
    `state_transitions` flap history are pruned at `raw_days`; hourly rollups are
    tiny and kept far longer (`rollup_days`, default ≈ 13 months) so long-range
    stats survive raw pruning. Windows must be positive — `RetentionService`
    refuses a policy that would delete everything."""

    raw_days: int = 30
    rollup_days: int = 396


@dataclass(frozen=True)
class NotifyDecision:
    """The outcome of `should_notify` (SPEC §3.7). `notify` is the go/no-go; `kind`
    says which message to send (`transition` vs a `flapping` summary) or why it was
    withheld; `reason` is a human-readable note for logs/audit. `notify` is `True`
    exactly when `kind` is not `suppressed`."""

    notify: bool
    kind: NotifyKind
    reason: str


@dataclass(frozen=True)
class AlertNotification:
    """The alert payload delivered to a channel (SPEC §3.7): the monitor's name, its
    new `status`, when that status began (`since`), the last error (if any), and a
    deep link back to the monitor. `kind` distinguishes a normal per-transition alert
    from a flapping summary so a notifier can word the message accordingly. Carries
    no secret — safe to serialize into a webhook body or a message."""

    monitor_id: UUID
    monitor_name: str
    status: MonitorStatus
    since: datetime
    kind: NotifyKind
    last_error: ErrorKind | None = None
    deep_link: str | None = None


@dataclass(frozen=True)
class NotifyResult:
    """The outcome of one delivery attempt (SPEC §3.7). `ok` is whether the channel
    accepted the alert; `detail` is a short, **secret-free** note for the audit log
    (e.g. ``"HTTP 200"``, ``"ConnectTimeout"``) — never a URL, token, or config
    value, which could themselves be secrets."""

    ok: bool
    detail: str | None = None


@dataclass(frozen=True)
class Stats:
    """Computed uptime/latency over a window (SPEC §3.5, §5). `status`/`since` are
    intentionally absent — they come from the monitor's `MonitorState`. A latency
    percentile is `None` when no timed result fell in the window."""

    window: str
    checks: int
    failures: int
    uptime_pct: float
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    latency_p99_ms: int | None


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
