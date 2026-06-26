---
name: sentinel-auth-source
description: >
  How to build and work on Sentinel's auth source (token provider) — the feature
  that lets a user designate one login/token-generating request and have Sentinel
  inject and refresh the token for dependent monitors. Use for slice S5b and any
  work touching login requests, token extraction, token caching/refresh
  (proactive or on 401/403), token injection into monitor requests, or keeping
  tokens out of responses, logs, and stored samples.
---

# Sentinel auth source (token provider)

Implements `SPEC.md §3.9`. An **auth source** is a stored login request plus a
token **extractor**, an **expiry** spec, and an **injection** spec. Monitors link
to one via `auth_source_id`; Sentinel fetches/refreshes the token and injects it.

## Model (see SPEC §4)

`AuthSource.mode` ∈ `custom | oauth2_client_credentials | oauth2_password |
oauth2_refresh` (default `custom`).

`AuthSource`: `request` (method/url/headers/body — credentials, **secret**),
optional `oauth` (`OAuthConfig`: `token_url`, `client_id`, `client_secret`*,
`scope`, `client_auth: body|basic`) for oauth2 modes, `extractor`
(`json_path | header | regex` + expr), `expiry`
(`json_path_seconds | absolute_path | ttl_seconds`, or `None` = refresh-on-401
only), `token_type` (default `Bearer`), `injection` (`target: header|query|body`,
`name`, `value_template` default `"{token_type} {token}"`),
`refresh_before_expiry_seconds` (default 60), `refresh_on_status` (default
`[401,403]`).

`TokenState` (one cached row per source): `token` (**encrypted at rest**),
`refresh_token` (**encrypted**, when the IdP returns one), `token_type`,
`obtained_at`, `expires_at`, `last_refresh_error`.

## Pure functions (in `domain/logic/auth.py`) — test these first, no I/O

- `build_token_request(auth_source) -> ProbeRequest` — `custom` mode: turn the
  source's raw request into the login probe request.
- `build_oauth_token_request(oauth, grant, refresh_token=None) -> ProbeRequest` —
  oauth2 modes: build the standard form body (`grant_type` =
  `client_credentials` / `password` / `refresh_token`, `client_id`, `scope`, and
  either client creds in the body or a Basic auth header per `client_auth`).
  When a `refresh_token` is supplied, build the `refresh_token` grant instead of
  re-sending primary credentials.
- `extract_token(response, extractor, expiry, now) -> Token` — read access token
  from body (JSONPath) / header / regex; also capture `refresh_token` if present;
  compute `expires_at` from the expiry spec relative to `now`. Raise a typed
  `TokenExtractionError` when the path/pattern doesn't match.
- `resolve_auth(auth_source, token_state, now) -> InjectionPlan | NeedsRefresh` —
  the refresh **decision**: return `NeedsRefresh` if no token, expired, or within
  `refresh_before_expiry_seconds` of `expires_at`; otherwise an `InjectionPlan`
  carrying the token + injection spec.
- `apply_injection(request, plan) -> ProbeRequest` — return a new request with the
  token placed per `injection.target` (header/query/body) using `value_template`.

`now` is supplied by `Clock` — never read the wall clock here.

## Use case (in `application/`) — the orchestration

`ProbeMonitorWithAuth` (or fold into the probe use case) does:

1. Load monitor; if `auth_source_id` is set, load `AuthSource` + `TokenState`.
2. `resolve_auth(...)`. On `NeedsRefresh`, refresh the token:
   - oauth2 modes with a stored `refresh_token` → `build_oauth_token_request(...,
     grant="refresh_token", refresh_token=...)`; **fall back to a full login**
     (credentials grant) if the refresh grant fails.
   - otherwise `build_token_request` / oauth credentials grant.
   - → `HttpProbe` → `extract_token` → save token (+ any new `refresh_token`)
     encrypted via `TokenStore`/`SecretBox`. **One cached token per source serves
     all linked monitors** — don't refresh per monitor.
3. `apply_injection` → probe the monitor.
4. **Reactive refresh:** if the response status ∈ `refresh_on_status`, invalidate
   the token, refresh **once**, retry the probe **once**. No loops. A persistent
   401 is recorded as a normal failed `CheckResult` (`error=assertion` or a
   dedicated `auth` kind) — never an API error and never an infinite retry.

Guard concurrent refreshes (per-source lock / single-flight) so a thundering
herd of due monitors triggers one login, not many.

## API (interface/)

`POST/GET/GET{id}/PATCH/DELETE /api/v1/auth-sources`, plus
`POST /api/v1/auth-sources/{id}/refresh`. Responses redact `request.body` and any
credential headers and include a `token_state` summary `{status, obtained_at,
expires_at}` — **never the token value**. `status` ∈ `valid | expired | error |
none`. Monitor create/patch accepts and validates `auth_source_id` (must exist).

## Security (hard rules — see sentinel-security)

- Credentials and cached tokens are encrypted at rest via `SecretBox`; decrypt
  only at probe time.
- The token and credentials never appear in any API response, log line, or stored
  `CheckResult` request/response sample — redact the injection target
  (`injection.name`) and known auth headers before persisting a sample.
- The SSRF guard applies to `auth_source.request.url` exactly as to monitor URLs.

## Test checklist (S5b)

- `extract_token`: success for json_path/header/regex; failure raises typed error;
  expiry computed from `expires_in` seconds, absolute path, and fixed ttl;
  `refresh_token` captured when present.
- `build_oauth_token_request`: client-credentials body/basic-auth variants and
  the `refresh_token` grant render correctly.
- `resolve_auth`: returns `NeedsRefresh` for missing/expired/near-expiry, else an
  `InjectionPlan` — exact boundary at `refresh_before_expiry_seconds` (fake `Clock`).
- `apply_injection`: header/query/body placement; template rendering.
- Integration: link monitor→source, probe injects the token; a 401 triggers
  exactly one refresh + one retry; persistent 401 → one failed check, no loop;
  an oauth2 source with a stored `refresh_token` refreshes via the refresh grant
  and falls back to full login when it fails.
- Redaction: refresh response and a probe sample contain no token/credential.
