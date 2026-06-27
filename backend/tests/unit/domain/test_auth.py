"""Pure auth-source logic (SPEC §3.9) — the heart of the token provider, with no
I/O. `now` is always injected so refresh-window math is deterministic. Covers the
skill's S5b test checklist: extract (json_path/header/regex + expiry + refresh
capture), oauth request building (body/basic + refresh/password grants), the
refresh decision (`resolve_auth` boundary), and injection placement/templating."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import pytest

from sentinel.domain.entities import AuthSource, TokenState
from sentinel.domain.errors import TokenExtractionError, ValidationError
from sentinel.domain.logic.auth import (
    apply_injection,
    build_oauth_token_request,
    build_token_request,
    extract_token,
    resolve_auth,
    token_status,
)
from sentinel.domain.value_objects import (
    AuthSourceMode,
    ClientAuth,
    ExpiryKind,
    ExpirySpec,
    ExtractorKind,
    HttpMethod,
    Injection,
    InjectionPlan,
    InjectionTarget,
    NeedsRefresh,
    OAuthConfig,
    OAuthGrant,
    ProbeRequest,
    ProbeResponse,
    TokenExtractor,
    TokenStatus,
)

NOW = datetime(2026, 6, 27, 12, 0, tzinfo=UTC)


def resp(body: str = "", headers: dict[str, str] | None = None, status: int = 200) -> ProbeResponse:
    return ProbeResponse(status_code=status, latency_ms=1, headers=headers or {}, body_sample=body)


def make_source(**over: object) -> AuthSource:
    params: dict[str, object] = {
        "name": "login",
        "mode": AuthSourceMode.CUSTOM,
        "request": ProbeRequest(method=HttpMethod.POST, url="https://id.example.com/login"),
        "extractor": TokenExtractor(kind=ExtractorKind.JSON_PATH, expr="$.access_token"),
        "injection": Injection(target=InjectionTarget.HEADER, name="Authorization"),
        "expiry": None,
        "oauth": None,
    }
    params.update(over)
    return AuthSource(**params)  # type: ignore[arg-type]


def token_state(**over: object) -> TokenState:
    params: dict[str, object] = {
        "auth_source_id": make_source().id,
        "token": "tok",
        "token_type": "Bearer",
        "obtained_at": NOW,
    }
    params.update(over)
    return TokenState(**params)  # type: ignore[arg-type]


# ---------------------------------------------------------------- extract_token


def test_extract_token_json_path_with_expires_in() -> None:
    tok = extract_token(
        resp('{"access_token":"abc","expires_in":3600}'),
        TokenExtractor(kind=ExtractorKind.JSON_PATH, expr="$.access_token"),
        ExpirySpec(kind=ExpiryKind.JSON_PATH_SECONDS, value="$.expires_in"),
        NOW,
    )
    assert tok.value == "abc"
    assert tok.expires_at == NOW + timedelta(seconds=3600)


def test_extract_token_from_header_case_insensitive() -> None:
    tok = extract_token(
        resp(headers={"X-Token": "hdr-tok"}),
        TokenExtractor(kind=ExtractorKind.HEADER, expr="x-token"),
        None,
        NOW,
    )
    assert tok.value == "hdr-tok"
    assert tok.expires_at is None


def test_extract_token_regex_uses_first_group() -> None:
    tok = extract_token(
        resp("set token=zzz999 now"),
        TokenExtractor(kind=ExtractorKind.REGEX, expr=r"token=(\w+)"),
        None,
        NOW,
    )
    assert tok.value == "zzz999"


def test_extract_token_regex_without_group_uses_whole_match() -> None:
    tok = extract_token(
        resp("abc-tok-xyz"),
        TokenExtractor(kind=ExtractorKind.REGEX, expr=r"\w+-tok"),
        None,
        NOW,
    )
    assert tok.value == "abc-tok"


@pytest.mark.parametrize(
    "extractor",
    [
        TokenExtractor(kind=ExtractorKind.JSON_PATH, expr="$.nope"),
        TokenExtractor(kind=ExtractorKind.HEADER, expr="X-Absent"),
        TokenExtractor(kind=ExtractorKind.REGEX, expr=r"token=(\d+)"),
    ],
)
def test_extract_token_raises_when_not_found(extractor: TokenExtractor) -> None:
    response = resp('{"other":"x"}', headers={"X-Token": "t"})
    with pytest.raises(TokenExtractionError):
        extract_token(response, extractor, None, NOW)


def test_extract_token_json_path_on_non_json_raises() -> None:
    with pytest.raises(TokenExtractionError):
        extract_token(
            resp("<html>not json</html>"),
            TokenExtractor(kind=ExtractorKind.JSON_PATH, expr="$.access_token"),
            None,
            NOW,
        )


def test_extract_token_ttl_seconds_expiry() -> None:
    tok = extract_token(
        resp(headers={"X-Token": "t"}),
        TokenExtractor(kind=ExtractorKind.HEADER, expr="X-Token"),
        ExpirySpec(kind=ExpiryKind.TTL_SECONDS, value=120),
        NOW,
    )
    assert tok.expires_at == NOW + timedelta(seconds=120)


def test_extract_token_absolute_path_epoch_expiry() -> None:
    exp = datetime(2026, 6, 27, 13, 0, tzinfo=UTC)
    tok = extract_token(
        resp(f'{{"access_token":"a","exp":{int(exp.timestamp())}}}'),
        TokenExtractor(kind=ExtractorKind.JSON_PATH, expr="$.access_token"),
        ExpirySpec(kind=ExpiryKind.ABSOLUTE_PATH, value="$.exp"),
        NOW,
    )
    assert tok.expires_at == exp


def test_extract_token_absolute_path_iso_expiry() -> None:
    tok = extract_token(
        resp('{"access_token":"a","exp":"2026-06-27T13:00:00+00:00"}'),
        TokenExtractor(kind=ExtractorKind.JSON_PATH, expr="$.access_token"),
        ExpirySpec(kind=ExpiryKind.ABSOLUTE_PATH, value="$.exp"),
        NOW,
    )
    assert tok.expires_at == datetime(2026, 6, 27, 13, 0, tzinfo=UTC)


def test_extract_token_captures_refresh_token() -> None:
    tok = extract_token(
        resp('{"access_token":"a","refresh_token":"r-123","expires_in":60}'),
        TokenExtractor(kind=ExtractorKind.JSON_PATH, expr="$.access_token"),
        ExpirySpec(kind=ExpiryKind.JSON_PATH_SECONDS, value="$.expires_in"),
        NOW,
    )
    assert tok.refresh_token == "r-123"


def test_extract_token_no_refresh_token_is_none() -> None:
    tok = extract_token(
        resp('{"access_token":"a"}'),
        TokenExtractor(kind=ExtractorKind.JSON_PATH, expr="$.access_token"),
        None,
        NOW,
    )
    assert tok.refresh_token is None


# ----------------------------------------------------------- build_token_request


def test_build_token_request_returns_login_request_copy() -> None:
    src = make_source(
        request=ProbeRequest(
            method=HttpMethod.POST,
            url="https://id.example.com/login",
            headers={"Content-Type": "application/json"},
            body='{"u":"x","p":"y"}',
        )
    )
    req = build_token_request(src)
    assert req.method is HttpMethod.POST
    assert req.url == "https://id.example.com/login"
    assert req.body == '{"u":"x","p":"y"}'
    req.headers["injected"] = "1"  # mutating the copy must not touch the source
    assert "injected" not in src.request.headers


# ------------------------------------------------------ build_oauth_token_request


def test_build_oauth_client_credentials_body_auth() -> None:
    oauth = OAuthConfig(
        token_url="https://id/token",
        client_id="cid",
        client_secret="sec",
        scope="read write",
        client_auth=ClientAuth.BODY,
    )
    req = build_oauth_token_request(oauth, OAuthGrant.CLIENT_CREDENTIALS)
    assert req.method is HttpMethod.POST
    assert req.url == "https://id/token"
    assert req.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert "Authorization" not in req.headers
    form = parse_qs(req.body or "")
    assert form["grant_type"] == ["client_credentials"]
    assert form["client_id"] == ["cid"]
    assert form["client_secret"] == ["sec"]
    assert form["scope"] == ["read write"]


def test_build_oauth_client_credentials_basic_auth() -> None:
    oauth = OAuthConfig(
        token_url="https://id/token",
        client_id="cid",
        client_secret="sec",
        client_auth=ClientAuth.BASIC,
    )
    req = build_oauth_token_request(oauth, OAuthGrant.CLIENT_CREDENTIALS)
    expected = base64.b64encode(b"cid:sec").decode()
    assert req.headers["Authorization"] == f"Basic {expected}"
    form = parse_qs(req.body or "")
    assert "client_secret" not in form
    assert "client_id" not in form  # identity travels in the Basic header
    assert form["grant_type"] == ["client_credentials"]


def test_build_oauth_refresh_token_grant() -> None:
    oauth = OAuthConfig(token_url="https://id/token", client_id="cid", client_secret="sec")
    req = build_oauth_token_request(oauth, OAuthGrant.REFRESH_TOKEN, refresh_token="r-7")
    form = parse_qs(req.body or "")
    assert form["grant_type"] == ["refresh_token"]
    assert form["refresh_token"] == ["r-7"]


def test_build_oauth_password_grant() -> None:
    oauth = OAuthConfig(
        token_url="https://id/token", client_id="cid", username="user", password="pw"
    )
    req = build_oauth_token_request(oauth, OAuthGrant.PASSWORD)
    form = parse_qs(req.body or "")
    assert form["grant_type"] == ["password"]
    assert form["username"] == ["user"]
    assert form["password"] == ["pw"]


# ------------------------------------------------------------------ resolve_auth


def test_resolve_auth_no_token_state_needs_refresh() -> None:
    assert isinstance(resolve_auth(make_source(), None, NOW), NeedsRefresh)


def test_resolve_auth_empty_token_needs_refresh() -> None:
    assert isinstance(resolve_auth(make_source(), token_state(token=""), NOW), NeedsRefresh)


def test_resolve_auth_valid_token_returns_injection_plan() -> None:
    src = make_source()
    ts = token_state(expires_at=NOW + timedelta(hours=1))
    plan = resolve_auth(src, ts, NOW)
    assert isinstance(plan, InjectionPlan)
    assert plan.token == "tok"
    assert plan.token_type == "Bearer"
    assert plan.injection == src.injection


def test_resolve_auth_at_refresh_window_boundary_needs_refresh() -> None:
    src = make_source(refresh_before_expiry_seconds=60)
    ts = token_state(expires_at=NOW + timedelta(seconds=60))  # now == expires - window
    assert isinstance(resolve_auth(src, ts, NOW), NeedsRefresh)


def test_resolve_auth_just_outside_window_returns_plan() -> None:
    src = make_source(refresh_before_expiry_seconds=60)
    ts = token_state(expires_at=NOW + timedelta(seconds=61))
    assert isinstance(resolve_auth(src, ts, NOW), InjectionPlan)


def test_resolve_auth_expired_token_needs_refresh() -> None:
    src = make_source()
    ts = token_state(expires_at=NOW - timedelta(seconds=1))
    assert isinstance(resolve_auth(src, ts, NOW), NeedsRefresh)


def test_resolve_auth_no_expiry_returns_plan() -> None:
    ts = token_state(expires_at=None)
    assert isinstance(resolve_auth(make_source(), ts, NOW), InjectionPlan)


# ---------------------------------------------------------------- apply_injection


def test_apply_injection_header_default_template() -> None:
    req = ProbeRequest(method=HttpMethod.GET, url="https://api/health", headers={"Accept": "*/*"})
    plan = InjectionPlan(
        injection=Injection(target=InjectionTarget.HEADER, name="Authorization"),
        token="tok",
        token_type="Bearer",
    )
    out = apply_injection(req, plan)
    assert out.headers["Authorization"] == "Bearer tok"
    assert out.headers["Accept"] == "*/*"
    assert "Authorization" not in req.headers  # non-mutating


def test_apply_injection_query() -> None:
    req = ProbeRequest(method=HttpMethod.GET, url="https://api/health", query_params={"v": "1"})
    plan = InjectionPlan(
        injection=Injection(
            target=InjectionTarget.QUERY, name="access_token", value_template="{token}"
        ),
        token="tok",
        token_type="Bearer",
    )
    out = apply_injection(req, plan)
    assert out.query_params["access_token"] == "tok"
    assert out.query_params["v"] == "1"


def test_apply_injection_body_json_field() -> None:
    req = ProbeRequest(method=HttpMethod.POST, url="https://api/x", body='{"a":1}')
    plan = InjectionPlan(
        injection=Injection(target=InjectionTarget.BODY, name="token", value_template="{token}"),
        token="tok",
        token_type="Bearer",
    )
    out = apply_injection(req, plan)
    assert json.loads(out.body or "") == {"a": 1, "token": "tok"}


def test_apply_injection_body_into_empty_body() -> None:
    req = ProbeRequest(method=HttpMethod.POST, url="https://api/x", body=None)
    plan = InjectionPlan(
        injection=Injection(target=InjectionTarget.BODY, name="token", value_template="{token}"),
        token="tok",
        token_type="Bearer",
    )
    out = apply_injection(req, plan)
    assert json.loads(out.body or "") == {"token": "tok"}


def test_apply_injection_custom_token_type() -> None:
    req = ProbeRequest(method=HttpMethod.GET, url="https://api/health")
    plan = InjectionPlan(
        injection=Injection(target=InjectionTarget.HEADER, name="Authorization"),
        token="tok",
        token_type="DPoP",
    )
    out = apply_injection(req, plan)
    assert out.headers["Authorization"] == "DPoP tok"


# --------------------------------------------------------- AuthSource invariants


def test_auth_source_rejects_blank_name() -> None:
    with pytest.raises(ValidationError):
        make_source(name="  ")


def test_oauth_mode_requires_oauth_config() -> None:
    with pytest.raises(ValidationError):
        make_source(mode=AuthSourceMode.OAUTH2_CLIENT_CREDENTIALS, oauth=None)


def test_custom_mode_allows_no_oauth() -> None:
    assert make_source(mode=AuthSourceMode.CUSTOM, oauth=None).oauth is None


# ------------------------------------------------------------------ token_status


def test_token_status_none_when_no_state() -> None:
    assert token_status(None, NOW) is TokenStatus.NONE


def test_token_status_valid_for_unexpired_token() -> None:
    ts = token_state(expires_at=NOW + timedelta(minutes=5))
    assert token_status(ts, NOW) is TokenStatus.VALID


def test_token_status_valid_when_no_expiry() -> None:
    assert token_status(token_state(expires_at=None), NOW) is TokenStatus.VALID


def test_token_status_expired_when_past_expiry() -> None:
    ts = token_state(expires_at=NOW - timedelta(seconds=1))
    assert token_status(ts, NOW) is TokenStatus.EXPIRED


def test_token_status_error_when_no_token_but_error_recorded() -> None:
    ts = token_state(token="", last_refresh_error="login failed")
    assert token_status(ts, NOW) is TokenStatus.ERROR
