# Sentinel — Specification

> Working name: **Sentinel**. An HTTP API monitoring web app. Users define endpoints
> to watch (by importing `curl` commands / Postman collections, or by manual
> setup), Sentinel probes them on a schedule, records latency / status / assertion
> outcomes, surfaces health dashboards, and alerts on up↔down transitions.
>
> **This file is the source of truth for _what_ the system does.** Behaviour
> changes are made here first, then in `PLAN.md` (how/when), then in code.
> `CLAUDE.md` governs _how_ we build it.

---

## 1. Problem & goals

Engineers need a lightweight, self-hostable way to know when their APIs are
slow, broken, or returning unexpected payloads — without paying per-monitor SaaS
fees or hand-rolling cron + curl. Importing an existing `curl` line or Postman
collection should produce a working monitor in seconds.

**Goals**
- Import a `curl` command or Postman v2.1 collection → reviewable monitor drafts.
- Manual monitor creation with full request control + assertions.
- Periodic probing with per-monitor interval & timeout.
- Rich assertions (status, latency, body, JSON path, headers).
- Designate one request as an **auth source** (token provider): Sentinel logs in,
  caches the token, and injects it into dependent monitors — refreshing on
  expiry or on a 401/403.
- Uptime % + latency percentiles + recent run history per monitor.
- Live status updates (no manual refresh).
- Alerts on state transitions via webhook / Telegram / email.
- Self-hostable as one Docker Compose stack; deployable to a managed host.

**Non-goals (v1)**
- Synthetic browser/E2E monitoring (this is HTTP-only).
- Multi-tenant SaaS billing, orgs, RBAC. v1 is single-tenant / single-team.
- Distributed multi-region probing. One probe location in v1.
- Tracing/APM. This is black-box uptime + contract checking.

---

## 2. Users & primary flows

- **Solo dev / small team** running their own APIs.
- **Flow A — Import:** paste a `curl` line _or_ upload a Postman collection →
  Sentinel parses → user reviews/edits drafts → saves selected as monitors.
- **Flow B — Manual:** fill a form (method, URL, headers, body, auth,
  assertions, interval) → save.
- **Flow C — Observe:** dashboard lists monitors with current status, uptime,
  p95 latency; detail view shows latency chart + recent runs.
- **Flow D — Get alerted:** configure a channel; receive a message when a
  monitor flips down (and when it recovers).
- **Flow E — Authenticated monitors:** define a login request as an _auth
  source_; link monitors to it; Sentinel fetches/refreshes a token and injects it
  automatically so probes hit protected endpoints without re-entering creds.

---

## 3. Functional requirements

### 3.1 Imports
- `POST /api/v1/imports/curl` — body: `{ "command": "<raw curl>" }`. Returns
  **drafts** (not persisted). Supports `-X`, `-H`, `-d`/`--data*`,
  `--url`, bare URL, `-u` basic auth, `--compressed`, `-L`. Unknown flags are
  ignored with a warning per draft.
- `POST /api/v1/imports/postman` — multipart file (collection v2.1 JSON).
  Flattens folders; one draft per request item. Resolves `{{var}}` against the
  collection's `variable` block when present (unresolved vars surfaced as
  warnings).
- (Future) `POST /api/v1/imports/openapi`, `/imports/har`.
- Import responses never persist anything. The client saves drafts via the
  normal create endpoint.

### 3.2 Manual setup & CRUD
- `POST /api/v1/monitors`, `GET /api/v1/monitors`, `GET /api/v1/monitors/{id}`,
  `PATCH /api/v1/monitors/{id}`, `DELETE /api/v1/monitors/{id}`.
- `POST /api/v1/monitors/{id}/check` — run one probe immediately (manual
  trigger), returns the `CheckResult`.

### 3.3 Scheduling & probing
- Each enabled monitor is probed every `interval_seconds` (min 30, default 300).
- A probe issues the request with `timeout_seconds` (default 10), `follow_redirects`,
  captures status, latency, response size, a bounded body sample for assertions,
  and (for HTTPS) the TLS leaf certificate's `notAfter` for cert-expiry checks.
- Network errors (DNS, connect, TLS, timeout) are recorded as failed checks with
  an `error` category — never crash the runner.
- A single slow/hung endpoint must not block others (concurrent probing, bounded
  concurrency).
- **Jitter:** each monitor's next run is spread with per-monitor jitter so checks
  don't all fire on the minute boundary (thundering herd).
- **Skip, don't backfill:** a missed tick (worker was down) is skipped, not
  replayed — a 10-minute outage must not enqueue 10 catch-up checks.
- **Multi-worker safe:** if ever run with >1 worker, due rows are claimed with
  `SELECT … FOR UPDATE SKIP LOCKED` so a monitor is probed by exactly one worker
  per cycle. (Single worker is the v1 default.)

### 3.4 Assertions
Each monitor has an ordered list of assertions. A check `success` iff **all**
pass. Types:
| type | params | passes when |
|---|---|---|
| `status_code` | `equals` or `in: [..]` or `range: [min,max]` | status matches |
| `max_latency_ms` | `value` | latency ≤ value |
| `body_contains` | `text`, `case_sensitive?` | sample contains text |
| `body_not_contains` | `text` | sample lacks text |
| `json_path_equals` | `path` (JSONPath), `value` | resolved value equals |
| `json_path_exists` | `path` | path resolves |
| `header_equals` | `name`, `value` | response header matches |
| `cert_expiry_days` | `min_days` | HTTPS TLS leaf cert valid for ≥ `min_days` more |
Default monitor (if none specified): `status_code in 200–299`.

### 3.5 Results, stats, history
- `GET /api/v1/monitors/{id}/results?from&to&limit` — paginated check history.
- `GET /api/v1/monitors/{id}/stats?window=24h|7d|30d` — uptime %, total checks,
  failures, p50/p95/p99 latency, current status & since. Short windows are
  computed from raw `CheckResult`s; **long windows are served from hourly
  rollups** (§4, §6) so a 30-day query never scans millions of rows.
- `GET /api/v1/monitors?include=summary` — list with current status + 24h uptime.

### 3.6 Live updates
- `GET /api/v1/events` — Server-Sent Events stream. Emits `check_completed` and
  `status_changed` events so dashboards update without polling.

### 3.7 Alerting
- Alert channels CRUD: `webhook` (POST JSON), `telegram` (bot token + chat id),
  `email` (SMTP). Channel secrets are write-only over the API.
- On a confirmed transition (see 3.8) Sentinel notifies all enabled channels once,
  idempotently (a transition fires exactly one notification per channel).
- Notification payload includes monitor name, new status, since, last error,
  and a deep link.
- **Re-notify cooldown:** while a monitor stays `down`, repeat/reminder
  notifications are rate-limited by `renotify_after_seconds` (default off / one
  alert per transition).
- **Flap damping:** if a monitor produces ≥ `flap_threshold` transitions within
  `flap_window_seconds`, suppress per-transition alerts and send a single
  "flapping" summary, then resume normal alerting once it stabilizes. The
  notify decision (`should_notify`) is a pure function over recent transition
  history.

### 3.8 State & transition rules
- A monitor has a current state: `up | down | unknown`.
- Transition to `down` after `failure_threshold` consecutive failed checks
  (default 1). Transition to `up` after `recovery_threshold` consecutive
  successes (default 1). Thresholds are per-monitor.
- Only confirmed transitions create alerts and `status_changed` events.

### 3.9 Auth source (token provider) for authenticated monitors
An **auth source** is a stored login/token-generating request. Monitors may link
to one so Sentinel authenticates them automatically.

- **Auth-source CRUD:** `POST /api/v1/auth-sources`, `GET` (list),
  `GET /{id}`, `PATCH /{id}`, `DELETE /{id}`. An auth source defines its own
  request (method, url, headers, body — credentials live here and are secret)
  plus a **token extractor** and an **injection** spec.
- **Grant modes.** A source has a `mode`:
  - `custom` (default) — the raw request above; fully general.
  - `oauth2_client_credentials` — Sentinel builds the standard token request
    (`grant_type=client_credentials`, `client_id`/`client_secret`, optional
    `scope`, form or basic-auth client auth) from structured fields, so the user
    doesn't hand-craft the body.
  - `oauth2_password` / `oauth2_refresh` — supported via the same builder.
  - **Refresh-token reuse:** when a token response includes a `refresh_token`,
    Sentinel stores it (encrypted) and uses the `refresh_token` grant on the next
    refresh instead of re-sending credentials — fewer full logins, less load on
    the IdP. Falls back to a full login if the refresh grant fails.
- **Token extractor** — where the token is read from the login response:
  `json_path` (e.g. `$.access_token`), `header` (e.g. `Authorization`), or
  `regex`. Optional **expiry**: a `json_path` to `expires_in` (seconds), an
  absolute-time path, or a fixed `ttl_seconds`; if none, treat as
  refresh-on-401 only. OAuth modes default to `$.access_token` / `$.expires_in`.
- **Injection** — how dependent monitors carry the token: `header`
  (name + value template, default `Authorization: {token_type} {token}`),
  `query` param, or `body` field. `token_type` defaults to `Bearer`.
- **Linking:** a monitor has an optional `auth_source_id`. The user can
  designate any saved login request as the source for one or more monitors.
- **Refresh policy (per source):**
  - *Proactive:* refresh when the cached token is missing, expired, or within
    `refresh_before_expiry_seconds` of expiry — _before_ the dependent probe.
  - *Reactive:* if a dependent probe returns a status in `refresh_on_status`
    (default `[401, 403]`), invalidate the token, refresh **once**, and retry
    the probe **once**. Never loop; a persistent 401 is recorded as a failed
    check.
- **Manual refresh:** `POST /api/v1/auth-sources/{id}/refresh` regenerates the
  token now and returns _metadata only_ (status, `obtained_at`, `expires_at`) —
  never the token value.
- **Token caching:** the current token is cached (encrypted at rest) per auth
  source and shared by all monitors linked to it; refreshing once serves many.
- **Security:** credentials and cached tokens are encrypted at rest and redacted
  in every API response and log. The injected token must never appear in stored
  `CheckResult` request/response samples (redact the injection target). The SSRF
  guard (§6) applies to the auth-source URL too.

---

## 4. Domain model

```
Monitor
  id: UUID
  name: str
  method: HttpMethod                 # GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS
  url: str
  headers: dict[str,str]             # secret-bearing names stored redacted (see §6)
  query_params: dict[str,str]
  body: str | None
  body_kind: none|raw|json|form
  auth: Auth | None                  # {type: basic|bearer|none, secret_ref}
  assertions: list[Assertion]
  interval_seconds: int  (>=30)
  timeout_seconds: int   (>=1, <=60)
  follow_redirects: bool
  failure_threshold: int (>=1)
  recovery_threshold: int (>=1)
  auth_source_id: UUID | None        # link to an auth source (§3.9); token injected per its config
  enabled: bool
  tags: list[str]
  created_at, updated_at: datetime

CheckResult
  id: UUID
  monitor_id: UUID
  started_at, finished_at: datetime
  status_code: int | None            # None on transport error
  latency_ms: int | None
  response_size_bytes: int | None
  cert_expires_at: datetime | None    # HTTPS leaf cert notAfter, when captured
  success: bool
  error: ErrorKind | None            # timeout|dns|connection|tls|assertion|blocked|unknown
                                     # `blocked` = the SSRF guard refused the URL (§6)
  assertion_results: list[AssertionResult]

CheckRollup                           # hourly aggregate per monitor (§3.5, §6)
  monitor_id: UUID
  bucket_start: datetime              # hour boundary (UTC); (monitor_id, bucket_start) unique
  checks: int
  failures: int
  latency_p50_ms, latency_p95_ms, latency_p99_ms: int   # from a per-bucket sketch/histogram
  latency_sum_ms: int                 # for weighted aggregation across buckets
  updated_at: datetime

MonitorState                          # current rollup, one per monitor
  monitor_id: UUID
  status: up|down|unknown
  since: datetime
  consecutive_failures: int
  consecutive_successes: int
  last_check_at: datetime | None

AlertChannel
  id: UUID
  type: webhook|telegram|email
  name: str
  config: dict                        # secrets stored encrypted, never returned
  enabled: bool

NotificationLog                       # idempotency / audit
  id, channel_id, monitor_id, transition_to, transition_at, fired_at, ok: bool, detail: str|None
  # transition_at = the confirmed flip time (StateTransition.at); fired_at = send time.
  # (channel_id, monitor_id, transition_at) is unique → one fire per transition per channel.

AuthSource                            # login / token-generating request (§3.9)
  id: UUID
  name: str
  mode: custom|oauth2_client_credentials|oauth2_password|oauth2_refresh  # default custom
  request: ProbeRequest               # method/url/headers/body — credentials are secret, encrypted
  oauth: OAuthConfig | None           # {token_url, client_id, client_secret*, scope, client_auth: body|basic} when mode=oauth2_*
  extractor: TokenExtractor           # {kind: json_path|header|regex, expr}
  expiry: ExpirySpec | None           # {kind: json_path_seconds|absolute_path|ttl_seconds, value}
  token_type: str                     # default "Bearer"
  injection: Injection                # {target: header|query|body, name, value_template}
  refresh_before_expiry_seconds: int  # proactive window, default 60
  refresh_on_status: list[int]        # reactive triggers, default [401, 403]
  enabled: bool
  created_at, updated_at: datetime

TokenState                            # cached token per auth source (one row)
  auth_source_id: UUID
  token: str                          # ENCRYPTED at rest; never returned/logged
  refresh_token: str | None           # ENCRYPTED at rest; used for oauth2 refresh-token reuse
  token_type: str
  obtained_at: datetime
  expires_at: datetime | None
  last_refresh_error: str | None
```

**Value objects / DTOs**: `MonitorDraft` (import output, unsaved),
`ProbeRequest`, `ProbeResponse` (incl. `cert_expires_at`), `Assertion`,
`AssertionResult`, `Stats`, `StateTransition`, `TokenExtractor`, `ExpirySpec`,
`Injection`, `OAuthConfig`, `Token`, `InjectionPlan`.

---

## 5. API contract (representative)

`POST /api/v1/monitors` request:
```json
{
  "name": "Prod health",
  "method": "GET",
  "url": "https://api.example.com/health",
  "headers": {"Authorization": "Bearer ..."},
  "assertions": [
    {"type": "status_code", "params": {"equals": 200}},
    {"type": "max_latency_ms", "params": {"value": 800}},
    {"type": "json_path_equals", "params": {"path": "$.status", "value": "ok"}}
  ],
  "interval_seconds": 60,
  "timeout_seconds": 10
}
```
Response `201`: full `Monitor` with `headers` redacted (`"Authorization": "Bearer ••••"`).

`POST /api/v1/imports/curl` request `{"command": "curl -H 'X-Api-Key: k' https://x/y"}`
→ `200`:
```json
{ "drafts": [ { "name": "GET /y", "method": "GET", "url": "https://x/y",
  "headers": {"X-Api-Key": "k"}, "assertions": [], "warnings": [] } ] }
```

`GET /api/v1/monitors/{id}/stats?window=24h` → `200`:
```json
{ "window": "24h", "checks": 1440, "failures": 3, "uptime_pct": 99.79,
  "latency_ms": {"p50": 120, "p95": 340, "p99": 510},
  "status": "up", "since": "2026-06-25T08:00:00Z" }
```

`POST /api/v1/auth-sources` request:
```json
{
  "name": "Staging login",
  "request": {"method": "POST", "url": "https://api.example.com/auth/login",
    "headers": {"Content-Type": "application/json"},
    "body": "{\"user\":\"svc\",\"pass\":\"s3cr3t\"}"},
  "extractor": {"kind": "json_path", "expr": "$.access_token"},
  "expiry": {"kind": "json_path_seconds", "value": "$.expires_in"},
  "injection": {"target": "header", "name": "Authorization",
    "value_template": "{token_type} {token}"},
  "refresh_before_expiry_seconds": 60
}
```
Response `201`: the auth source with `request.body`/credentials **redacted** and
a `token_state` summary (`{status, obtained_at, expires_at}` — no token).

`POST /api/v1/auth-sources/{id}/refresh` → `200`:
```json
{ "status": "valid", "obtained_at": "2026-06-26T09:00:00Z",
  "expires_at": "2026-06-26T10:00:00Z" }
```
The token value is never present in any response.

SSE `GET /api/v1/events` emits:
```
event: status_changed
data: {"monitor_id":"...","from":"up","to":"down","at":"..."}
```

Errors use a consistent envelope: `{ "error": {"code": "...", "message": "...", "details": {...}} }`.
Validation → `422`; not found → `404`; transport problems in probes are results, not API errors.

---

## 6. Non-functional requirements

- **Secret handling.** Request secrets (auth headers/tokens, channel configs,
  auth-source credentials, and cached tokens) are encrypted at rest. API
  responses redact secret-bearing header values and never return channel secrets
  or tokens. Logs must never contain secret values, and a token injected by an
  auth source must never appear in a stored `CheckResult` sample. Hard rule,
  enforced at the serialization boundary (see `CLAUDE.md` guardrails).
  **Key rotation:** encryption uses `MultiFernet` — decrypt with any key in the
  ring, encrypt with the first — so rotating `SECRET_KEY` doesn't invalidate
  existing ciphertext. Ship a `.env.example`; never commit real keys.
- **SSRF protection.** Probes hit arbitrary user-supplied URLs. By default
  (configurable) deny requests to loopback, link-local, and private IP ranges,
  and the cloud metadata endpoint `169.254.169.254`. Resolve-then-validate to
  avoid DNS-rebinding. May be disabled for trusted self-host use. Applies to
  every outbound user-supplied URL — monitor probes, auth-source logins, and
  webhook channels. A blocked probe is a failed check with `error=blocked`; a
  blocked login is a recorded refresh error; a blocked webhook is a
  `NotificationLog` with `ok=false` — never a crash or a silent success.
- **Access control.** The API must not be exposed to the internet without the
  minimal auth gate (a static API token / basic auth) in place. The gate ships
  before any deploy slice; full hardening (rate limiting, etc.) follows.
- **Performance.** Probe runner sustains ≥ 1k monitors at 1-minute cadence on a
  single small instance via bounded async concurrency. Probe of monitor A never
  blocks B. Long-window stats (7d/30d) are served from hourly **rollups**, not by
  scanning raw `CheckResult`s.
- **Reliability.** A crash mid-cycle loses at most the in-flight checks; on
  restart the runner resumes from persisted schedule state. No probe runs while
  a monitor is disabled. **Dead-man's switch:** the scheduler emits an outbound
  heartbeat to an external watchdog (e.g. healthchecks.io) every cycle; if Sentinel
  itself dies, the watchdog alerts — so a silent worker death is never mistaken
  for "all green." Configurable via `HEARTBEAT_URL` (off if unset).
- **Retention.** Raw check results are pruned by age (default 30 days) and/or row
  cap per monitor; pruning is idempotent and scheduled. Hourly rollups are
  retained far longer (default 13 months) since they're tiny, preserving
  long-range history after raw rows are gone.
- **Observability.** Structured JSON logs, a `/api/v1/health` liveness endpoint,
  basic runtime metrics (checks/sec, queue depth).

---

## 7. Acceptance criteria (capability-level)

- **Import-curl:** a representative `curl` with method, two headers, and a JSON
  `-d` body produces a single draft with those fields and no warnings.
- **Import-postman:** a 3-request collection (one in a folder, one using a
  `{{baseUrl}}` var) yields 3 drafts with vars resolved; an undefined var
  produces a warning, not a failure.
- **Manual create:** posting a valid monitor returns `201`, persists it, and the
  response redacts the `Authorization` header.
- **Probe + assertions:** against a controllable test server, a monitor with a
  status + latency + json_path assertion records a `CheckResult` whose `success`
  reflects each assertion outcome; a 500 or timeout yields `success=false` with
  the right `error`.
- **Scheduling:** a monitor with `interval_seconds=60` is selected for probing
  when ≥60s have elapsed since `last_check_at`, and not before; disabled
  monitors are never selected; per-monitor jitter is applied; a simulated gap
  (worker down) produces one due check on resume, not a backfilled burst.
- **Stats:** uptime % and percentiles computed over a window match a known
  fixture of results.
- **Rollups:** folding a fixture of raw results into hourly rollups, then
  computing a 30-day stat from rollups, matches the raw computation within
  tolerance; rollup folding is idempotent (re-folding a bucket doesn't
  double-count).
- **Cert expiry:** a `cert_expiry_days` assertion fails when the captured leaf
  cert's `notAfter` is nearer than `min_days`, passes otherwise; HTTP (non-TLS)
  monitors skip it cleanly.
- **Transition/alert:** with `failure_threshold=2`, two consecutive failures
  flip state to `down`, emit one `status_changed`, and fire exactly one
  notification per enabled channel; a single failure does not.
- **Flap damping:** a monitor exceeding `flap_threshold` transitions within
  `flap_window_seconds` produces one "flapping" summary instead of per-transition
  alerts, and resumes normal alerts once stable.
- **Live:** a completed check pushes an SSE event observable by a connected client.
- **Auth source — obtain:** defining an auth source with a `json_path` extractor
  and calling refresh fetches a token, caches it encrypted, and returns expiry
  metadata but never the token value.
- **Auth source — inject:** a monitor linked to an auth source has the token
  injected per the injection spec on each probe.
- **Auth source — proactive refresh:** when the cached token is expired or within
  the refresh window, it is regenerated before the dependent probe runs.
- **Auth source — reactive refresh:** a dependent probe returning 401 triggers
  exactly one refresh and one retry; a persistent 401 records a failed check
  without looping.
- **Auth source — OAuth refresh-token reuse:** when a token response includes a
  `refresh_token`, the next refresh uses the refresh grant (not a full login),
  falling back to full login if it fails.
- **Heartbeat:** each scheduler cycle pings `HEARTBEAT_URL` when set; nothing is
  emitted when unset.
- **Auth gate:** with the gate enabled, an unauthenticated request is rejected
  (`401`) and a valid token/credential is accepted.
- **Secrets:** no API response or log line contains a stored secret value, and no
  injected token appears in a stored `CheckResult` sample; rotating the encryption
  key ring still decrypts previously stored ciphertext.

---

## 8. Out of scope / future (parking lot)

OpenAPI & HAR import · **config export (monitor → curl / Postman collection;
round-trips the importers)** · multi-region probes · status pages (public) ·
maintenance windows / mute schedules · per-step request chaining · SLA reports ·
multi-user auth & RBAC · anomaly detection on latency.
