"""Pure auth-source logic (SPEC §3.9) — building token requests, extracting the
token from a login response, deciding whether to refresh, and injecting the token
into a dependent monitor's request. Zero I/O: no network, no DB, and the current
time is injected (never read from a clock), so all of it is deterministically
unit-tested. The orchestration (load source/token, run the probe, persist the
cached token, reactive 401 retry) lives in the application layer.

Reuses the SPEC-subset JSONPath resolver from the assertion engine for token and
expiry extraction."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from sentinel.domain.entities import AuthSource, TokenState
from sentinel.domain.errors import TokenExtractionError
from sentinel.domain.logic.json_path import MISSING, resolve_json_path
from sentinel.domain.value_objects import (
    ClientAuth,
    ExpiryKind,
    ExpirySpec,
    ExtractorKind,
    HttpMethod,
    InjectionPlan,
    InjectionTarget,
    NeedsRefresh,
    OAuthConfig,
    OAuthGrant,
    ProbeRequest,
    ProbeResponse,
    Token,
    TokenExtractor,
)

_FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"


def build_token_request(auth_source: AuthSource) -> ProbeRequest:
    """`custom` mode: replay the stored login request. Returns a copy so callers
    (injection, etc.) never mutate the source's stored request."""
    req = auth_source.request
    return replace(req, headers=dict(req.headers), query_params=dict(req.query_params))


def build_oauth_token_request(
    oauth: OAuthConfig, grant: OAuthGrant, refresh_token: str | None = None
) -> ProbeRequest:
    """Build the standard OAuth2 token request (RFC 6749) for the given grant.
    Client credentials go in the form body (`client_secret_post`) or an HTTP Basic
    header (`client_secret_basic`) per `oauth.client_auth`. A `refresh_token` grant
    sends the stored refresh token instead of re-sending primary credentials."""
    form: dict[str, str] = {"grant_type": grant.value}
    if grant is OAuthGrant.REFRESH_TOKEN:
        if refresh_token is None:
            raise ValueError("refresh_token grant requires a refresh_token")
        form["refresh_token"] = refresh_token
    elif grant is OAuthGrant.PASSWORD:
        form["username"] = oauth.username or ""
        form["password"] = oauth.password or ""
    if oauth.scope:
        form["scope"] = oauth.scope

    headers = {"Content-Type": _FORM_CONTENT_TYPE}
    if oauth.client_auth is ClientAuth.BASIC:
        raw = f"{oauth.client_id}:{oauth.client_secret or ''}".encode()
        headers["Authorization"] = f"Basic {base64.b64encode(raw).decode('ascii')}"
    else:
        form["client_id"] = oauth.client_id
        if oauth.client_secret:
            form["client_secret"] = oauth.client_secret

    return ProbeRequest(
        method=HttpMethod.POST,
        url=oauth.token_url,
        headers=headers,
        body=urlencode(form),
    )


def extract_token(
    response: ProbeResponse,
    extractor: TokenExtractor,
    expiry: ExpirySpec | None,
    now: datetime,
) -> Token:
    """Read the access token (and any `refresh_token`) from a login response and
    compute its expiry relative to `now`. Raises `TokenExtractionError` when the
    extractor/expiry path or pattern does not resolve."""
    body = _load_json(response.body_sample)
    value = _read_token(response, extractor, body)
    refresh_token = body.get("refresh_token") if isinstance(body, dict) else None
    expires_at = _compute_expiry(expiry, body, now)
    return Token(
        value=value,
        expires_at=expires_at,
        refresh_token=refresh_token if isinstance(refresh_token, str) else None,
    )


def resolve_auth(
    auth_source: AuthSource, token_state: TokenState | None, now: datetime
) -> InjectionPlan | NeedsRefresh:
    """The refresh decision (no I/O): `NeedsRefresh` if there is no cached token,
    it has expired, or it is within `refresh_before_expiry_seconds` of expiry;
    otherwise an `InjectionPlan` carrying the cached token + injection spec."""
    if token_state is None or not token_state.token:
        return NeedsRefresh("no cached token")
    if token_state.expires_at is not None:
        window = timedelta(seconds=auth_source.refresh_before_expiry_seconds)
        if now >= token_state.expires_at - window:
            return NeedsRefresh("token expired or within refresh window")
    return InjectionPlan(
        injection=auth_source.injection,
        token=token_state.token,
        token_type=token_state.token_type,
    )


def apply_injection(request: ProbeRequest, plan: InjectionPlan) -> ProbeRequest:
    """Return a copy of `request` carrying the token per the injection spec. Never
    mutates the input."""
    value = plan.injection.value_template.format(token_type=plan.token_type, token=plan.token)
    target = plan.injection.target
    if target is InjectionTarget.HEADER:
        return replace(request, headers={**request.headers, plan.injection.name: value})
    if target is InjectionTarget.QUERY:
        return replace(request, query_params={**request.query_params, plan.injection.name: value})
    # body: set the field in the JSON object body (starting from {} when empty).
    data = _load_json(request.body) if request.body else {}
    if not isinstance(data, dict):
        raise TokenExtractionError("body injection requires a JSON object request body")
    return replace(request, body=json.dumps({**data, plan.injection.name: value}))


def _load_json(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _read_token(response: ProbeResponse, extractor: TokenExtractor, body: Any) -> str:
    if extractor.kind is ExtractorKind.JSON_PATH:
        if not isinstance(body, (dict, list)):
            raise TokenExtractionError("login response body is not valid JSON")
        value = resolve_json_path(body, extractor.expr)
        if value is MISSING:
            raise TokenExtractionError(f"token path {extractor.expr} did not resolve")
        return str(value)
    if extractor.kind is ExtractorKind.HEADER:
        lowered = {k.lower(): v for k, v in response.headers.items()}
        value = lowered.get(extractor.expr.lower())
        if value is None:
            raise TokenExtractionError(f"token header {extractor.expr} not present")
        return value
    # regex: first capturing group, else the whole match.
    match = re.search(extractor.expr, response.body_sample)
    if match is None:
        raise TokenExtractionError(f"token pattern {extractor.expr!r} did not match")
    return match.group(1) if match.groups() else match.group(0)


def _compute_expiry(expiry: ExpirySpec | None, body: Any, now: datetime) -> datetime | None:
    if expiry is None:
        return None
    if expiry.kind is ExpiryKind.TTL_SECONDS:
        return now + timedelta(seconds=int(expiry.value))
    if not isinstance(body, (dict, list)):
        raise TokenExtractionError("expiry path requires a JSON response body")
    raw = resolve_json_path(body, str(expiry.value))
    if raw is MISSING:
        raise TokenExtractionError(f"expiry path {expiry.value} did not resolve")
    if expiry.kind is ExpiryKind.JSON_PATH_SECONDS:
        return now + timedelta(seconds=int(raw))
    return _parse_absolute(raw)


def _parse_absolute(raw: Any) -> datetime:
    """Parse an absolute expiry: a numeric epoch (seconds) or an ISO-8601 string.
    Naive datetimes are assumed UTC so comparisons stay tz-aware."""
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, UTC)
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError as exc:
        raise TokenExtractionError(f"could not parse absolute expiry {raw!r}: {exc}") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
