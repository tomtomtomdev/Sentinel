# Sentinel — Progress

> **Living log of where we are.** Updated at the end of every slice (it's part of
> Definition of Done). This file exists so Claude can **clear context and resume
> safely**: a cold start should need only `SPEC.md` + `PLAN.md` + this file.
> Keep it accurate over verbose.

---

## Cold-start checklist (do this first, every fresh context)

1. Read `SPEC.md` (what) and `PLAN.md` (how + slice roadmap).
2. Read **§ Current state** and **§ Next action** below.
3. Run the suite: `just test` (or `cd backend && uv run pytest`). Confirm green.
   - If red on a clean checkout, that's the real next action — fix before new work.
4. Open the next **unchecked** slice in `PLAN.md §5`. Do only that slice.
5. Follow the slice loop in `CLAUDE.md`. Update this file before committing.

---

## Current state

- **Phase:** **S11 COMPLETE (S11.4 — monitor detail shell + auth-source UI).**
  New routes: `/monitors/:id` — detail shell (name + live status pill from
  `GET /monitors/{id}/stats?window=24h`, method chip + URL, 24h stats strip
  [uptime/checks/failures/p50/p95/p99], config summary [interval/timeout/
  assertion count/enabled], **auth-source link select** → `PATCH auth_source_id`
  (None = unlink), two-step delete → `DELETE` + back to dashboard; chart/runs
  panel is an S12 placeholder) and `/auth-sources` — new sidebar nav (key icon):
  list with token-state pill (valid/expired/error/none), expiry time,
  `last_refresh_error`, per-source **Refresh** (`POST /auth-sources/{id}/
  refresh` → toast), Enable/Disable (`PATCH enabled`), Delete; create form for
  **custom mode** (name, login method/URL/body [JSON body auto-gets
  Content-Type], `json_path` token extractor, optional `json_path_seconds`
  expiry, header injection defaulting `Authorization` + `{token_type} {token}`).
  Dashboard cards now **link to the detail page**. No token value is ever
  displayed anywhere (the API never returns one — verified `body: "••••"` on
  the wire). OAuth2 modes + full-field edit are API-only for now (parked).
- **Prior phase:** **S11.3 complete (add-monitor screen).** The
  add-monitor flow works end to end (`docs/design/` Screen 2): segmented tabs —
  **Paste cURL** (textarea + example filler → `POST /imports/curl` → detected-
  request preview: method chip, URL, headers, body pre → Create), **Import
  collection** (dropzone/browse → `POST /imports/postman` multipart → selectable
  endpoint list + select/deselect-all → "Create N monitors" sequential
  `POST /monitors`), **Manual setup** (name w/ URL-derived fallback, method +
  URL, repeatable header rows) — plus the shared **Monitoring rules** block
  (interval 30s–30m → `interval_seconds`, expected status → `status_code equals`
  assertion, assertion rows mapping to `body_contains`/`json_path_equals` [two
  inputs: path + value]/`status_code`/`max_latency_ms` — pure `buildAssertions`
  in `src/lib/rules.ts`). Create navigates back with router state → dashboard
  shows the design's success **toast** + 6s **NEW pill** on the created cards.
  Parse/upload/validation failures surface as toasts (never a dead form). New
  `api.postForm` (multipart, no forced JSON content-type; client now calls
  `fetch(url, init)` directly). **Deviations from the design (recorded):**
  import accepts **Postman v2.1 only** (backend SPEC §3.1 has no OpenAPI/generic
  parser — design mentions them; parked to SPEC §8), parsing is **server-side**
  (the S3/S4 domain parsers are the single source of truth; the design's
  client-side parser spec is unused), and the default assertion row is empty
  (the design's default "status 200" row would duplicate the expected-status
  field, which already emits that assertion).
- **Prior phase:** **S11.2 complete (dashboard screen).** The
  dashboard (`docs/design/` Screen 1) renders real data from
  `GET /monitors?include=summary` via TanStack Query (`useMonitors` in
  `src/lib/monitors.ts`, types mirroring the backend DTOs): 4 summary stat
  cards (Operational / **Unknown** / Down / Avg uptime·24h — the design's
  "Degraded" slot renders the backend's `unknown`, which has no degraded status
  in v1; avg is over monitors with `checks > 0`, "—" when none), monitor card
  grid (status dot + name, method chip, protocol-stripped URL, uptime/p95
  latency/last-check footer; `checks == 0` → "No data yet" footer), client-side
  search filter (name or URL), empty state with add CTA, loading + error
  panels. Pure display formatters in `src/lib/format.ts` (stripProtocol,
  formatUptime — trims trailing zeros, formatLatency — "—" when null, timeAgo —
  injected `now`). **26-bar sparkline deferred to S12** (needs per-monitor
  results = N+1 requests; S11 scope per PLAN §5 is "status + 24h uptime").
- **Prior phase:** **S11.1 complete (frontend scaffold + app shell +
  API client).** S11 split into S11.1–S11.4 (scaffold / dashboard / add-monitor /
  detail+auth-sources). `frontend/` now exists (PLAN §2 stack: pnpm + Vite 6 +
  React 18 + TS strict + Tailwind v4 + TanStack Query + React Router 7; tests
  Vitest 3 + Testing Library, jsdom, in `frontend/tests/`). Design tokens from
  `docs/design/README.md` live as Tailwind `@theme` variables in `src/index.css`
  (fonts Hanken Grotesk/JetBrains Mono via Google Fonts in `index.html`; status/
  accent/border palette; `sntIn`/`sntPulse` keyframes; shared `.snt-field` focus
  style). App shell: 240px sidebar (brand, **Monitors** nav only — the design's
  Incidents/Alerts/Status-pages nav is v1 out-of-scope per SPEC §8, deliberately
  omitted; static Workspace account card) + routes `/monitors` (dashboard
  placeholder: h1, live indicator, Add-monitor button) and `/monitors/new`
  (back link + heading placeholder); `/` redirects to `/monitors`. Typed API
  client (`src/lib/api.ts`): `api.get/post/patch/delete`, base URL
  `VITE_API_BASE_URL` (default `/api/v1`, resolved absolute against the page
  origin), **S9a Bearer token on every call** — token from
  localStorage(`sentinel.auth_token`) with `VITE_AUTH_TOKEN` dev fallback
  (`src/lib/config.ts`) — SPEC §5 error envelope mapped to typed `ApiError`
  (code/message/details/status; non-envelope bodies → `http_<status>`), 204-safe.
  Vite dev proxy `/api` → `localhost:8000` (same-origin dev, no CORS). justfile
  gained `front-build`; `front-test`/`front-dev` recipes now real.
- **Prior phase:** **S10 complete (S10.2 — retention pruning).** History now prunes itself
  (SPEC §6, D31): `prune_before(cutoff) -> int` on `CheckResultRepository`
  (`finished_at`), `StateTransitionRepository` (`at`), `CheckRollupRepository`
  (`bucket_start`) — strictly-older-than, bulk DELETE across all monitors, port +
  fakes + SQL adapters, no migration. `RetentionService` (`application/`) computes
  cutoffs from `RetentionPolicy` (raw **30d** for results + transitions; rollups
  **396d** ≈ 13mo) via the injected `Clock`; idempotent by construction; the service
  constructor rejects a non-positive window (`ValidationError`, fail-at-boot).
  `SchedulerRunner` runs it via `_maybe_prune`: first cycle, then at most once per
  `RETENTION_PRUNE_INTERVAL_SECONDS` (3600); a prune failure is logged + retried next
  interval, never a crashed cycle. Worker-only wiring (`build_runner`); config knobs +
  `.env.example` section. Per-monitor row cap parked (SPEC "and/or" — age-only v1).
- **Prior phase:** **S10.1 complete — SSRF guard on every outbound user-supplied URL.**
  Resolve-then-validate (D30): pure `invalid_url_reason` + `blocked_ip_reason` in
  `domain/logic/url_guard.py` (non-http(s)/host-less URLs; loopback, link-local incl.
  `169.254.169.254`, private, unspecified, multicast, reserved; IPv4-mapped v6
  unwrapped; unparseable = blocked). `SsrfUrlGuard` (`infrastructure/url_guard.py`)
  resolves via an injected resolver (default: loop `getaddrinfo`) and blocks if **any**
  resolved IP is denied — DNS rebinding caught; literal-IP hosts skip resolution;
  guard-time resolution failure passes so the real send classifies `dns`.
  `GuardedHttpProbe` wraps the **shared** probe at both composition roots, so monitor
  probes **and** auth-source logins are guarded with zero call-site changes: blocked
  probe → failed `CheckResult` with new `ErrorKind.BLOCKED` (SPEC §4 updated); blocked
  login → `TokenState.last_refresh_error`. `WebhookNotifier(guard=...)` refuses a
  blocked webhook URL as `NotifyResult(ok=False)` **before** any HTTP; reasons are
  secret-free (never URL/host/IP). `SSRF_GUARD_ENABLED=true` default; `.env.example`
  documents the trade-off. Telegram (fixed host) + `HEARTBEAT_URL` (operator config)
  deliberately unguarded.
- **Prior phase:** **S9a complete — minimal API auth gate.** One `require_auth` FastAPI
  dependency (`interface/api/auth.py`) guards **every** `/api/v1/*` router except the
  `/health` liveness probe — reads, writes, and the SSE `/events` stream all demand
  `Authorization: Bearer <AUTH_TOKEN>` (`AUTH_TOKEN` in `config.py`), compared with
  `secrets.compare_digest` (constant-time). Missing/invalid → `401` in the SPEC §5
  envelope (code `unauthorized`, `WWW-Authenticate: Bearer`) via a new
  `UnauthorizedError` handler in `errors.py` (extends D12). Applied router-wide in
  `create_app()` (`dependencies=[Depends(require_auth)]`), so a new router must opt
  **in** to being open, not out of being gated. **Empty `AUTH_TOKEN` (default) =
  gate open — dev only** (D29); `.env.example` documents "never expose without a
  token" and S13's runbook/compose must set it. The gate reads settings via
  `Depends(get_settings)`, so tests (and S14's richer auth) compose on the same seam.
- **Prior phase:** **S9.3 complete — `Notifier` adapters + `AlertService` wiring. S9 is
  DONE (alert channels + notify, cooldown + flap damping end to end).** New `Notifier`
  port (`send(channel, notification) -> NotifyResult`, **never raises**) with three
  adapters in `infrastructure/notifiers.py`: `WebhookNotifier` (POST JSON),
  `TelegramNotifier` (bot `sendMessage`), and `EmailNotifier` (**parked stub** — SMTP
  deferred, records `ok=False`). New `AlertService` (`application/alert_service.py`)
  consumes a confirmed `StateTransition` **directly** (not via the S8 `EventBus`), runs
  pure `should_notify`, and on notify fans out to all **enabled** channels **exactly
  once** (skips a channel where `NotificationLogRepository.exists(channel_id,
  monitor_id, transition_at)`), sending via the notifier for `channel.type` and
  recording a `NotificationLog` per attempt. Wired as a **4th optional `CheckService`
  dep** (`alerts`, via `maybe_notify(monitor, transition|None, last_error)` — no-ops on
  `None`) so the manual path + all call sites stay green; wired in `deps.py` + the
  scheduler `build_runner`. **`recent_transitions` provenance resolved (D28) = a
  dedicated persisted `state_transitions` store** (new `StateTransitionRepository` port
  + in-memory fake + `SqlStateTransitionRepository` + migration `e7f8a9b0c1d2`), owned
  by `AlertService`: it reads prior flips in the flap window **before** appending the
  current flip and appends **regardless of the notify decision** (so suppressed flips
  still count toward future flap windows — which the fired-only `NotificationLog` can't
  provide). Naturally replay-safe: `CheckService` only alerts when `advance_state`
  confirms a flip, so a replayed check yields no transition. Two new value objects:
  `AlertNotification` (secret-free payload: monitor name, new status, `since`, last
  error, deep link, `kind`) + `NotifyResult` (`ok` + secret-free `detail`); pure
  `format_alert_message` renders telegram/email text (webhook sends structured JSON).
  **Secrets:** channel `config` reaches the notifier already decrypted (repo concern),
  used only to send; `NotifyResult.detail` is a classification (`"HTTP 500"`, exception
  class name), **never** the webhook URL or bot token. `AlertPolicy` built from global
  config (`ALERT_FLAP_THRESHOLD`/`ALERT_FLAP_WINDOW_SECONDS`/
  `ALERT_RENOTIFY_AFTER_SECONDS`); deep link from `DASHBOARD_BASE_URL`.
- **Prior phase:** **S9.2 complete — alert-channel/notification-log persistence + channel
  CRUD API.** Two new entities (SPEC §4): `AlertChannel` (`type`
  webhook|telegram|email, `name`, `config`, `enabled`; no audit timestamps per §4) and
  `NotificationLog` (id/channel_id/monitor_id/transition_to/**transition_at**/fired_at/
  ok/detail — the audit + idempotency ledger). New `AlertChannelRepository`
  (add/get/list/update/delete) and `NotificationLogRepository` (add/`exists`/
  list_for_monitor) ports + in-memory fakes + SQL adapters
  (`infrastructure/db/alert_channel_repository.py`) + rows + migration
  `d4a1b2c3e5f6` (`alert_channels`, `notification_logs` with a **unique
  `(channel_id, monitor_id, transition_at)`** so a transition fires once per channel).
  **Channel `config` secrets are write-only:** encrypted at rest via `SecretBox`
  (`encrypt_secret_config`/`decrypt_secret_config` in `secret_mapping.py`) and masked
  in responses (`redact_config`), both driven by the **same** new
  `is_secret_config_key` heuristic (`*token*/*secret*/*key*/*password*`) so encryption
  and redaction can't drift (mirrors D18). `AlertChannelService` (CRUD, `NotFoundError`
  → 404) + `POST/GET/GET{id}/PATCH/DELETE /api/v1/channels` routes (secret never
  returned). Also fixed a **SPEC §4 gap**: `NotificationLog` had no field to identify
  *which* transition a row belongs to — added `transition_at` (the flip time) so
  exactly-once idempotency has a stable key. Notification-log repo is not yet wired
  into a composition root (S9.3 consumes it); channel repo/service wired into `deps.py`.
- **Prior phase:** **S9.1 complete — pure `should_notify` (flap damping + cooldown).**
  `domain/logic/notify.py::should_notify(transition, recent_transitions, policy, now)
  -> NotifyDecision`. Flap damping (one `flapping` summary at the threshold crossing,
  suppress above it, resume when flips age out; `< 2` disables; exclusive window) wins
  over re-notify cooldown (same-`to_status` repeat within `renotify_after_seconds`;
  default 0 = one alert per transition). VOs: `AlertPolicy`, `NotifyDecision`,
  `NotifyKind`. Consumed by S9.3's `AlertService` (reads the transition **directly**,
  not via the S8 `EventBus`).
- **Earlier phase:** **S8 complete — SSE live events.** `GET /api/v1/events` streams
  `check_completed` (every recorded check) + `status_changed` (confirmed transition) to
  connected dashboards via an in-process `EventBus` port (per-subscriber bounded queue,
  **drop-oldest** back-pressure, `publish` never blocks/raises) wired into the **API**
  root only (scheduler worker deliberately unwired — cross-process delivery is a parked
  Redis drop-in). `CheckService._advance_state` returns the `StateTransition`;
  `_publish_events` emits both. `CheckCompleted` VO is a narrow secret-free summary;
  the SSE frame shape lives in `interface/api/events.py`.
- **Older phase:** **S7/S7a + S8 complete — state, stats, history, rollups, SSE.**
  `MonitorState` advances via `advance_state`; §3.5 read endpoints via `StatsService`;
  hourly `CheckRollup`s back 7d/30d; `GET /events` streams `check_completed`/
  `status_changed`. S5b (auth source) + S6 (scheduler + heartbeat) complete beneath.
- **Last green commit:** S10.1 (`feat(security): SSRF guard — resolve-then-validate
  every outbound user-supplied URL (S10.1)`); S10.2 staged.
- **Test suite:** `just test` (no DB) → **495 passed, 50 skipped** (+12 from S10.2).
  With `TEST_DATABASE_URL=…/sentinel_test` → **545 passed** (no skips). S10.2 added:
  `tests/unit/application/test_retention_service.py` (6 — per-store cutoffs + report
  counts, second-run no-op, custom policy honoured, non-positive window rejected
  [parametrized ×3]), one `prune_before` contract test in each of the three repo
  contract files (prunes old / keeps exactly-at-cutoff / cross-monitor / second run
  0, ×{memory,pg}), and 3 scheduler tests (first cycle primes then waits the
  interval; a raising retention service doesn't abort the cycle; no-retention runner
  still cycles). Worker root smoke: `build_runner` constructs with retention wired.
  **S10.1 detail (still current):** added:
  `tests/unit/domain/test_url_guard.py` (32 collected — scheme/host rejection incl.
  no-URL-echo, every blocked range with a named reason + no-IP-echo, IPv4-mapped v6,
  public passes incl. the 172.32.0.1 boundary, unparseable-IP fail-closed),
  `tests/unit/infrastructure/test_url_guard.py` (9 — public pass, DNS rebinding
  blocked, any-private-among-many blocks, literal IP + bad scheme skip resolution,
  disabled guard passes without resolving, resolver failure passes through,
  `GuardedHttpProbe` raises `ProbeError(BLOCKED)` pre-send / delegates when allowed),
  webhook-guard additions in `test_notifiers.py` (2 — blocked URL → `ok=False` +
  "blocked" detail + no HTTP + no URL leak; public URL passes through), and
  `tests/integration/test_check_pipeline_ssrf.py` (3 — blocked monitor URL → one
  recorded failed check `error=blocked` + inner probe untouched; guard disabled →
  request sent; blocked auth-source login → `last_refresh_error` recorded, no raise).
  Real-wire smoke: default `getaddrinfo` resolver blocks `http://localhost` (loopback)
  and passes `https://example.com`; app boots (`/api/v1/health` 200). Earlier S9a
  detail:
  `tests/integration/test_auth_gate.py` (13 — 401 envelope + `WWW-Authenticate` on
  missing/wrong/non-Bearer credentials; valid token accepted; one route per router
  gated incl. SSE `/events`; `/health` stays open; empty-token dev mode open).
  Real-wire smoke: uvicorn with `AUTH_TOKEN` set → `/health` 200, `/monitors` 401
  (no/bad token), `/events` 401. **S9.3 detail (still current):** S9.3 added:
  `tests/unit/application/test_alert_service.py` (11 — fan-out exactly-once, idempotent
  re-invoke, disabled skipped, cooldown/flap-crossing/above-flap suppression, failing
  notifier → `ok=false` + fan-out continues, unregistered type → `ok=false`, payload
  fields + deep link, transition recorded for flap history),
  `tests/unit/domain/test_alert_message.py` (4 — down/recovery/flapping wording +
  omit-when-absent), `tests/unit/infrastructure/test_notifiers.py` (8 via respx —
  webhook JSON/2xx/5xx/transport-error, telegram bot API + no-token-leak, missing-config,
  email stub), `tests/integration/test_state_transition_repository.py` (3 ×{memory,pg} —
  window/scope/inclusive-boundary), `tests/integration/test_check_pipeline_alert.py`
  (4 — confirmed down+recovery fire once each, replay no-realert, below-threshold silent,
  no-alert-service still probes). Migration verified on a scratch DB: `upgrade head` from
  base ends at single head `e7f8a9b0c1d2`; `downgrade -1` + re-`upgrade head` round-trips.
  ruff + mypy strict clean. Composition roots build (API `get_alert_service`/
  `get_check_service` + worker `build_runner`). **S9.2 detail (still current):** New:
  `tests/unit/domain/test_alert_channel.py` (21 collected — `is_secret_config_key`
  secret/non-secret keys [parametrized], `redact_config` mask/passthrough/no-mutate/
  empty, `AlertChannel` name-blank invariant, `NotificationLog` construction),
  `tests/integration/test_alert_channel_repository.py` (17 with PG = channel round-trip/
  list/update/delete/unknown + notification-log add/list/`exists`-idempotency-key,
  ×{memory,pg}, + PG-only config-ciphertext-at-rest; 8 run without a DB),
  `tests/integration/test_alert_channel_api.py` (8 —
  create-redacts-but-stores-full / list+get redacted / 404 / patch enabled+config /
  delete / blank-name 422). ruff + mypy strict clean. App boots (`/api/v1/health` 200,
  `/api/v1/channels` list 200). Migration verified: `alembic upgrade head` from base on
  a clean DB, single head `d4a1b2c3e5f6`, downgrade/upgrade round-trips.
- **Schema/migrations:** head **`e7f8a9b0c1d2`** (`state_transitions`: append-only
  confirmed-flip history, `monitor_id` index; feeds flap damping). Prior:
  `d4a1b2c3e5f6` (`alert_channels`; `notification_logs`).
- **Deps:** unchanged (`respx` already present; notifiers use the existing `httpx`).
- **Config:** S9a added `auth_token` ("" = gate open, dev only) + the `.env.example`
  "API auth gate" section with a generation one-liner. Prior (S9.3):
  `alert_flap_threshold` (5), `alert_flap_window_seconds` (600),
  `alert_renotify_after_seconds` (0), `dashboard_base_url` ("") — `.env.example`
  Alerting section; `AlertPolicy` built from these in both composition roots.
  (`heartbeat_url`, `scheduler_*` from S6 remain; their `.env.example` backfill
  is still parked.)
- **Deployed:** no.

## Next action

➡️ **Begin S12 — frontend charts + live** (PLAN §5): latency chart (Recharts —
add the dep) + recent-runs table on the detail page (`GET /monitors/{id}/
results`), the dashboard **26-bar sparkline** parked from S11.2 (per-monitor
recent results — consider a batch include or accept N+1 with query caching),
and **live updates via `EventSource`** on `GET /api/v1/events`
(`check_completed` → invalidate/patch monitor summaries + append to the runs
table; `status_changed` → status flip; note: EventSource can't set an
Authorization header — the S9a gate on `/events` needs a token query-param or
fetch-based SSE reader; decide and, if backend changes are needed, spec them
first). Component tests with a fake EventSource.

**Parked follow-ups from S11.1** (not blockers): the auth token has no settings
UI yet (localStorage/`VITE_AUTH_TOKEN` only — add an entry surface when a 401 is
first rendered, likely S11.2+); no frontend CI wiring (PLAN §6 mentions frontend
tests on PR — revisit at S13); no ESLint/Prettier config (ts strict + tests are
the gate for now); fonts load from Google Fonts CDN (self-host at S13 if the
deploy must be offline); sidebar has no responsive collapse.

**Parked follow-ups from S10.2** (not blockers): per-monitor raw **row cap** (SPEC
"and/or" — age-only shipped); pruning runs only in the **worker** (an API-only
deploy never prunes); no `VACUUM`/table-bloat management (Postgres autovacuum is
assumed); `RetentionReport` is logged, not exposed via any endpoint.

**Parked follow-ups from S10.1** (not blockers): httpx follows redirects *within* one
send, so a public URL that 302s to a private address is not re-validated per hop —
closing it needs an httpx request event hook inside `HttpxProbe` (S14 hardening).
Guard reasons are static strings; no per-check debug logging of the resolved IPs.

**Parked follow-ups from S9a** (not blockers): the gate is all-or-nothing global
(no writes-only mode, no per-route scopes — S14 if ever needed); rate limiting on the
401 path (brute-force damping) is S14; `AUTH_TOKEN` is a single shared static
credential (multi-user auth is post-v1); S13 compose/runbook **must set `AUTH_TOKEN`**
(empty = open, D29).

**Parked follow-ups from S9.3** (not blockers): ~~the webhook notifier trusts its
user-supplied URL~~ — **done in S10.1** (guarded, `NotifyResult(ok=False)` on a
blocked URL). Email is a **parked stub** (SMTP delivery deferred; an email channel currently
logs `ok=false` every transition). Per-monitor flap/cooldown overrides remain parked
(policy is global). Periodic "still down" reminder emitter still parked (cooldown
defaults off). `state_transitions` has no retention/pruning yet (S10 retention). The
notifiers open a short-lived `httpx.AsyncClient` per send (no shared pooled client).

---

## Slice checklist (mirror of `PLAN.md §5`)

- [x] **S0** Scaffold & green harness
- [x] **S1** Monitor entity + repository (+ Alembic init)
- [x] **S2** Monitor CRUD API (+ header redaction)
- [x] **S3** curl import
- [x] **S4** Postman import
- [x] **S5** Probe + assertions engine (S5.1 pure engine + S5.2 adapter/persist/endpoint)
- [x] **S5a** Secret-at-rest (`SecretBox` / Fernet)
- [x] **S5b** Auth source / token provider _(split — PLAN D19)_
  - [x] **S5b.1** Pure auth logic + value objects/entities
  - [x] **S5b.2** `AuthSource`/`TokenState` persistence (repo + `TokenStore` + migration)
  - [x] **S5b.3** Auth-source CRUD + manual-refresh API
  - [x] **S5b.4** Probe-pipeline injection + proactive/reactive refresh + single-flight
- [x] **S6** Scheduler runner
- [x] **S7** State, stats & history _(split — see log)_
  - [x] **S7.1** Pure state + stats logic + value objects/entity
  - [x] **S7.2** `MonitorState` persistence (repo + migration) + wire into check pipeline
  - [x] **S7.3** `GET /results`, `GET /stats`, `?include=summary` endpoints
- [x] **S7a** Rollups & long-window stats
- [x] **S8** SSE live events
- [x] **S9** Alert channels + notify (cooldown + flap damping) _(split — see log)_
  - [x] **S9.1** Pure `should_notify` (flap damping + cooldown) + alert value objects
  - [x] **S9.2** `AlertChannel`/`NotificationLog` persistence + channel CRUD API
  - [x] **S9.3** `Notifier` adapters + `AlertService` wiring (idempotent via `NotificationLog`)
- [x] **S9a** Minimal API auth gate
- [x] **S10** SSRF guard + retention _(split — S10.1 guard / S10.2 retention)_
  - [x] **S10.1** SSRF guard (probe + auth-source login + webhook notifier)
  - [x] **S10.2** Retention pruning (raw results + state transitions + rollups)
- [x] **S11** Frontend scaffold _(split — see log)_
  - [x] **S11.1** Scaffold + app shell + API client (Vite/React/TS/Tailwind/Vitest)
  - [x] **S11.2** Dashboard screen (stat cards + monitor card grid)
  - [x] **S11.3** Add-monitor screen (cURL / import / manual + monitoring rules)
  - [x] **S11.4** Monitor detail shell + auth-source manage UI
- [ ] **S12** Frontend charts + live
- [ ] **S13** Containerize & deploy
- [ ] **S14** Hardening

---

## Detailed log (newest first)

> Template per entry — copy this when completing a slice:
>
> ```
> ### S<n> — <title>  · <YYYY-MM-DD>
> Done: <what now works, observable behaviour>
> Tests: <added/where; suite green>
> Decisions: <any new Dn added to PLAN §7, or "none">
> Files: <key paths created/changed>
> Follow-ups / parked: <anything deferred — also add to Parking lot if cross-slice>
> Commit(s): <conventional commit subject lines>
> Resume hint: <the very next concrete step>
> ```

### S11.4 — Monitor detail shell + auth-source manage UI (finishes S11)  · 2026-07-17
Done: The last two S11 surfaces. **Monitor detail** (`/monitors/:id`,
`MonitorDetailPage`): back link, name + status pill (from the 24h stats),
method chip + stripped URL, stats strip (uptime / checks / failures /
p50/p95/p99 via `useMonitorStats`), config summary (interval, timeout,
assertion count, enabled), **auth-source select** (options from
`GET /auth-sources`; change → `PATCH /monitors/{id} {auth_source_id}`, "" →
`null` unlink, toast), **two-step delete** (Delete monitor → Confirm delete →
`DELETE` → navigate back with a "Monitor deleted" toast), and an S12
placeholder panel for chart + runs. Dashboard cards are now wrapped in a
`<Link to=/monitors/{id}>` (design: clickable cards). **Auth sources**
(`/auth-sources`, `AuthSourcesPage`, new sidebar nav item with a key icon —
no mockup in `docs/design/`, follows the existing tokens): list rows show
name, mode chip, enabled state, **token-state pill**
(valid=green/expired=amber/error=red/none=gray), expiry clock time, and
`last_refresh_error`; actions per row — **Refresh** (`POST
/auth-sources/{id}/refresh`, toast "Token refreshed" or "Refresh failed —
token is {status}"), **Enable/Disable** (`PATCH {enabled}`), **Delete**.
Create form (custom mode): name (URL fallback), login method/URL/body (a
JSON-looking body auto-adds `Content-Type: application/json`), token path
(`json_path` extractor, default `$.access_token`), optional expires-in path
(`json_path_seconds`), inject-into-header name (default `Authorization`,
template `{token_type} {token}`). **No token value is ever rendered** —
`token_state` is metadata-only by API design (verified on the wire:
credentials echo as `••••`, `token_state` carries status/timestamps only).
Types + hooks in `src/lib/authSources.ts` and `monitors.ts`
(`useMonitor`/`useMonitorStats`, `MonitorDetail`/`MonitorStats`).
Tests: `tests/monitor-detail.test.tsx` (3 — identity + stats + config render
and the stats query hits `?window=24h`; auth-source select PATCHes the right
body; two-step delete calls `DELETE` and returns to the dashboard),
`tests/auth-sources.test.tsx` (4 — list with token pills + refresh error
shown; manual refresh posts + toasts; create posts the exact SPEC §5 payload
[custom mode, json_path extractor, header injection]; disable PATCHes +
delete DELETEs), `dashboard.test.tsx` +assert card href, `app.test.tsx` +nav
item + `/auth-sources` route render. `pnpm test` → **47 passed**; `pnpm
build` clean; backend gate 495/50 + ruff + mypy clean. Real-wire smoke:
created an auth source through the Vite proxy (response redacts the body,
`token_state: null` pre-refresh), fetched `stats?window=24h` for a fresh
monitor (unknown/0 checks shape), deleted both.
Decisions: none new (D32 stands; OAuth-modes-UI + full-field-edit parked
below).
Files: `frontend/src/lib/authSources.ts` (new), `frontend/src/lib/monitors.ts`
(+detail/stats types + hooks), `frontend/src/pages/{MonitorDetailPage,
AuthSourcesPage}.tsx` (new), `frontend/src/App.tsx` (+2 routes),
`frontend/src/components/{Layout.tsx,icons.tsx,MonitorCard.tsx}` (nav item +
KeyIcon; exported `STATUS`/`StatusPill`), `frontend/src/pages/
DashboardPage.tsx` (card → Link), `frontend/tests/{monitor-detail,
auth-sources}.test.tsx` (new) + `dashboard`/`app` test additions.
Follow-ups / parked: OAuth2 modes (client-credentials/password/refresh) and
full-field auth-source **edit** are API-only (UI is create/toggle/refresh/
delete); the detail page doesn't edit monitor fields beyond `auth_source_id`
(name/url/interval edit UI parked); add-monitor manual tab has no auth-source
select yet (link from the detail page instead); auth-source create form
doesn't expose custom headers/query params or `refresh_on_status`.
Commit(s): `feat(frontend): monitor detail shell + auth-source manage UI —
S11 complete (S11.4)`.
Resume hint: start S12 — decide the SSE auth mechanism first (EventSource
can't send Authorization; likely a `?token=` query param accepted by the S9a
gate — spec it in SPEC §5 before coding), then failing tests for the latency
chart + runs table + sparkline + live invalidation.

### S11.3 — Add-monitor screen (cURL / import / manual + rules)  · 2026-07-17
Done: A monitor can be created from the UI three ways (design Screen 2, SPEC
§3.1). **Paste cURL:** textarea (+ "Use example") → `POST /imports/curl` → the
"Detected request" preview card (method chip, URL, `key:` headers, body
`<pre>`) → Monitoring rules → Create. **Import collection:** dropzone with
drag-over state or browse → `POST /imports/postman` (multipart via new
`api.postForm`) → header "{file} · N requests" + Select/Deselect-all +
checkbox list (method chip, name, URL) → interval+status (compact rules) →
"Create N monitor(s)" posting each selected draft. **Manual setup:** name
(blank → derived from URL path tail), method select + URL, repeatable header
rows (≥1 kept), full rules. Shared **Monitoring rules**: interval select
(30s/1m/5m/10m/30m → seconds via `intervalToSeconds`), expected status →
`{type:"status_code",params:{equals}}`, assertion rows → `body_contains{text}`
/ `json_path_equals{path,value}` (row grows a second path input — the design's
single value field can't carry both) / `status_code{equals}` /
`max_latency_ms{value}`; pure `buildAssertions` skips blank rows. Create
success: invalidate the monitors query, `navigate("/monitors", {state:{toast,
newIds}})` → dashboard shows the bottom-center auto-dismiss **Toast** (new
`components/Toast.tsx`, ~3s, re-trigger resets) and a 6s **NEW pill** on the
new cards (`MonitorCard isNew`). Failures (unparseable cURL, invalid JSON,
missing URL) → toasts, form stays. API client change: `apiFetch` now calls
`fetch(url, init)` (not `new Request`) so a jsdom `FormData` isn't coerced
cross-realm in tests; behaviour identical in the browser.
Deviations from the design (all deliberate): Postman v2.1 **only** (no
OpenAPI/generic parser in the backend — SPEC §3.1; candidates for §8), parsing
is **server-side** (S3/S4 domain parsers are the single source of truth — the
design's client-side parser specs are not reimplemented), default assertion
list is empty (the design's default "Status code equals 200" row would emit a
duplicate of the expected-status field's assertion).
Tests: `tests/rules.test.ts` (5 — interval mapping + options, every row type →
backend params, blank-skip), `tests/add-monitor.test.tsx` (8 — tabs render/
default, curl parse posts command + preview shows chip/URL/header/body, create
posts draft+rules exactly and returns to dashboard, parse failure toast,
manual create with headers + 5m interval, missing-URL toast + no post, import
upload → postForm + list + deselect + create-1-of-2, upload-failure toast),
`api.test.ts` +1 (postForm: no forced content-type, Bearer kept, body
passthrough), `dashboard.test.tsx` +1 (arrival state → toast + NEW pill).
`pnpm test` → **39 passed**; `pnpm build` clean. Backend untouched (495/50 +
ruff + mypy clean). Real-wire smoke: `POST /imports/curl` through the Vite
proxy returns the exact `MonitorDraft` shape the client types expect.
Decisions: none new (D32 conventions; deviations recorded here + Parking lot).
Files: `frontend/src/lib/{rules.ts,imports.ts}` (new),
`frontend/src/components/{Toast.tsx}` (new), `frontend/src/components/
{icons.tsx,MonitorCard.tsx}` (+6 icons; +NEW pill), `frontend/src/lib/api.ts`
(+`postForm`, fetch(url, init)), `frontend/src/pages/AddMonitorPage.tsx`
(placeholder → full screen), `frontend/src/pages/DashboardPage.tsx` (arrival
toast + newIds), `frontend/tests/{rules.test.ts,add-monitor.test.tsx}` (new) +
`api.test.ts`/`dashboard.test.tsx` additions.
Follow-ups / parked: OpenAPI + generic-JSON import (needs a backend parser —
SPEC §8 candidate); "Load an example collection" link (design) omitted — needs
a bundled sample; per-draft edit before create (name/URL tweaks) not offered;
sequential create-N has no partial-failure recovery UI (first error toasts and
stops); body/`body_kind` not editable in the manual tab (curl/import only).
Commit(s): `feat(frontend): add-monitor screen — cURL parse, Postman import,
manual setup + monitoring rules (S11.3)`.
Resume hint: start S11.4 — read `interface/api/auth_sources.py` DTOs first;
then failing tests for the detail-page shell (`/monitors/:id`) + auth-source
list/create/refresh screens; make dashboard cards link to the detail page.

### S11.2 — Dashboard screen (stat cards + monitor card grid)  · 2026-07-17
Done: The dashboard is real (design `docs/design/README.md` Screen 1). New
`useMonitors` TanStack Query hook (`src/lib/monitors.ts`) fetches
`GET /monitors?include=summary` (S7.3 shape: `summary.{status,since,
last_check_at,uptime_pct,latency_p95_ms,checks}`); TS types mirror the backend
DTO field names. `DashboardPage` renders: header (h1, pulsing live indicator,
**search field** filtering by name/URL client-side, Add-monitor button), a
4-up **summary stat** strip — Operational / **Unknown** / Down counts + Avg
uptime·24h (mean over monitors with `checks > 0`; "—" when none) — and the
**monitor card grid** (`auto-fill minmax(300px,1fr)`; `MonitorCard`: status
dot + truncated name, colored method chip, protocol-stripped mono URL, status
pill, footer with colored uptime, mono p95 latency ("—" when null), relative
last-check time; `checks == 0` → "No data yet — waiting for the first check").
Explicit loading, error ("Could not load monitors — …"), and empty ("No
monitors yet" + CTA) states. Pure formatters in `src/lib/format.ts`:
`stripProtocol`, `formatUptime` (trims trailing zeros: "100%", "99.79%"),
`formatLatency`, `timeAgo` (injected `now` — pure). **Design adaptations:**
backend has no `degraded` status (SPEC §3.8: up/down/unknown), so the design's
Degraded slot (amber) renders **Unknown**; the 26-bar sparkline is **deferred
to S12** (needs per-monitor recent results = N+1 fetches; S11 scope is "status
+ 24h uptime" per PLAN §5). NEW-pill behavior belongs to S11.3 (create flow).
Tests: `tests/format.test.ts` (5 blocks — protocol strip, uptime/latency
formats, timeAgo buckets + null) + `tests/dashboard.test.tsx` (6 — include
param on the query, card contents per status incl. no-data card, stat-card
counts + avg over data-bearing monitors only, search filter, empty state,
error state); `app.test.tsx` now mocks the api module (and `tests/setup.ts`
switched `restoreAllMocks` → `clearAllMocks` so factory-time mock
implementations survive between tests). `pnpm test` → **24 passed**;
`pnpm build` (tsc strict) clean. Backend untouched: 495/50 + ruff + mypy
clean. Real-wire smoke: uvicorn (with `SECRET_KEY`) + `pnpm dev` → created a
monitor via `POST /monitors`, `GET /monitors?include=summary` through the Vite
proxy returns exactly the typed shape (unknown/checks=0 → no-data card path);
seeded monitor deleted after.
Decisions: none new (D32 covers the conventions; the Unknown-for-Degraded
mapping + sparkline deferral are S12-visible notes, recorded here).
Files: `frontend/src/lib/{monitors.ts,format.ts}` (new),
`frontend/src/components/MonitorCard.tsx` (new — card + `MethodChip`),
`frontend/src/components/icons.tsx` (+Search, +TrendingUp),
`frontend/src/pages/DashboardPage.tsx` (placeholder → real screen),
`frontend/tests/{format.test.ts,dashboard.test.tsx}` (new),
`frontend/tests/{app.test.tsx,setup.ts}` (api mock; clearAllMocks).
Follow-ups / parked: 26-bar sparkline + live updates via SSE (**S12**);
monitor cards not yet clickable (detail route is S11.4); dashboard doesn't
poll/refresh (S12 live slice decides polling vs SSE invalidation); the design's
NEW pill arrives with the create flow (S11.3).
Commit(s): `feat(frontend): dashboard — summary stats + monitor card grid from
live API data (S11.2)`.
Resume hint: start S11.3 — read `interface/api/imports.py` for the exact
curl/postman import routes + draft shape, and the assertion type names in
`domain/`; then write failing component tests for the add-monitor tabs.

### S11.1 — Frontend scaffold + app shell + API client  · 2026-07-17
Done: `frontend/` exists and boots (PLAN §2 stack): pnpm + Vite 6 + React 18 +
TypeScript strict + Tailwind v4 (`@tailwindcss/vite`) + TanStack Query + React
Router 7; Vitest 3 + Testing Library (jsdom) with tests in `frontend/tests/`.
**S11 split** into S11.1 (this), S11.2 (dashboard), S11.3 (add-monitor), S11.4
(detail shell + auth-source UI). Design tokens from `docs/design/README.md`
committed as Tailwind `@theme` variables (`src/index.css`: text/surface/border/
accent/status palette, Hanken Grotesk + JetBrains Mono via Google Fonts,
`sntIn`/`sntPulse` keyframes, `.snt-field` focus ring). App shell (`Layout.tsx`):
240px `#fafafa` sidebar — brand tile + wordmark, **Monitors** nav (active style
per design; the design's Incidents/Alerts/Status-pages items are v1 out-of-scope
per SPEC §8 and deliberately omitted rather than rendered dead), static
Workspace/Self-hosted account card — and a scrolling white main pane. Routes:
`/` → redirect `/monitors` (dashboard placeholder: h1 + pulsing live indicator +
black Add-monitor button) and `/monitors/new` (back link + "Add a monitor"
heading + design sub-copy); real screens land in S11.2/S11.3. Typed API client
(`src/lib/api.ts` + `src/lib/config.ts`): `api.get/post/patch/delete` over
fetch; base URL `VITE_API_BASE_URL` default `/api/v1`, resolved absolute against
the page origin (works same-origin, in tests, and with an absolute URL); sends
the **S9a `Authorization: Bearer`** header on every call when a token exists —
localStorage `sentinel.auth_token` first, `VITE_AUTH_TOKEN` dev-only fallback
(`.env.example` warns Vite env is public); SPEC §5 envelope → typed `ApiError`
(status/code/message/details), non-envelope error bodies → `http_<status>`,
204-safe. Vite dev server proxies `/api` → `http://localhost:8000` (no CORS).
justfile: +`front-build`; existing `front-test`/`front-dev` now work.
Tests: `frontend/tests/api.test.ts` (9 — Bearer attached / absent without a
token / persisted; base-path prefix + JSON parse; POST content-type + body;
204 DELETE; envelope→ApiError incl. 401 `unauthorized`; non-envelope fallback)
+ `frontend/tests/app.test.tsx` (4 — sidebar brand/nav, dashboard at
`/monitors` with Add-monitor action, `/` redirect, add-monitor screen at
`/monitors/new`). `pnpm test` → **13 passed**. `pnpm build` (tsc strict + vite)
clean. Backend untouched: `just test` 495/50, `just lint` + `just types` clean.
Boot smoke: uvicorn + `pnpm dev` → `curl localhost:5173/api/v1/health` through
the proxy returns `{"status":"ok"}`; SPA index serves.
Decisions: **D32** (S11 split; token from localStorage with Vite-env dev
fallback; ApiError envelope mapping in one fetch wrapper; Tailwind v4 `@theme`
tokens as the design-token home; out-of-scope nav omitted; frontend tests live
in `frontend/tests/` mirroring PLAN §3) added to PLAN §7.
Files: `frontend/{package.json,vite.config.ts,tsconfig.json,index.html,
.env.example,.gitignore}`, `frontend/src/{main.tsx,App.tsx,index.css}`,
`frontend/src/lib/{api.ts,config.ts}`, `frontend/src/components/{Layout.tsx,
icons.tsx}`, `frontend/src/pages/{DashboardPage.tsx,AddMonitorPage.tsx}`,
`frontend/tests/{setup.ts,api.test.ts,app.test.tsx}`, `justfile`
(+`front-build`).
Follow-ups / parked: auth-token settings UI (no way to enter the token in the
app yet); frontend CI job; ESLint/Prettier; self-hosted fonts (S13); responsive
sidebar collapse; `pnpm-lock.yaml` committed for reproducibility.
Commit(s): `feat(frontend): scaffold Vite/React/TS/Tailwind SPA — app shell +
authed API client (S11.1)`.
Resume hint: start S11.2 — first check the real shape of
`GET /api/v1/monitors` + the S7.3 summary include in `interface/api/`, then
write failing component tests for the stat cards + monitor card grid (mock the
api module), then build the dashboard per `docs/design/README.md` Screen 1.

### S10.2 — Retention pruning (finishes S10)  · 2026-07-16
Done: History is pruned on a schedule (SPEC §6 retention). The three history repos —
`CheckResultRepository` (keyed on `finished_at`), `StateTransitionRepository` (`at`;
parked from S9.3), `CheckRollupRepository` (`bucket_start`; parked from S7a) — each
gained `prune_before(cutoff) -> int`: one bulk DELETE of rows **strictly older** than
the cutoff (a row exactly at the cutoff is kept), across **all** monitors, returning
the count; port + in-memory fakes + SQL adapters (a shared `deleted_count` helper in
`db/engine.py` narrows SQLAlchemy's `Result` → `CursorResult.rowcount` once); no
migration (deletes only). `RetentionService` (`application/retention_service.py`)
computes the cutoffs from a new `RetentionPolicy` VO via the injected `Clock`: raw
`CheckResult`s **and** `state_transitions` at `raw_days` (default **30** — flips
older than the flap window have no reader), rollups at `rollup_days` (default
**396** ≈ 13 months) so long-range stats survive raw pruning; returns a
`RetentionReport` (per-store delete counts) for the worker log. Idempotent by
construction (an age cutoff re-run deletes nothing). The policy VO is a plain
dataclass like `AlertPolicy` (`value_objects` keeps its no-`errors`-import
invariant); the **service constructor** rejects a non-positive window with
`ValidationError`, so a misconfigured worker fails at boot instead of silently
deleting everything. Scheduling lives in `SchedulerRunner`: optional `retention` dep
+ `retention_interval_seconds` (default 3600); `_maybe_prune(now)` runs on the first
cycle, then at most once per interval, and a pruning failure (DB blip) is logged and
retried next interval — never a crashed cycle. Wired in the **worker only**
(`build_runner`; the API root doesn't prune). Config: `RETENTION_RAW_DAYS=30`,
`RETENTION_ROLLUP_DAYS=396`, `RETENTION_PRUNE_INTERVAL_SECONDS=3600` +
`.env.example` Retention section.
Tests: `tests/unit/application/test_retention_service.py` (6),
`prune_before` contract tests appended to `test_check_result_repository.py` /
`test_state_transition_repository.py` / `test_check_rollup_repository.py`
(×{memory,pg} each — prunes old, keeps exactly-at-cutoff + newer, cross-monitor,
second run 0), scheduler tests in `test_scheduler.py` (3 — first-cycle prime + wait
interval + re-prune after it elapses via `FixedClock.set`; raising retention doesn't
abort the cycle; runner without retention cycles). Suite: **495 passed / 50 skipped**
(no DB, +12); **545 passed** with PG (`sentinel_test` — SQL DELETEs verified real).
ruff + mypy strict clean. App boots (`/api/v1/health` 200); `build_runner` smoke
shows retention wired.
Decisions: **D31** (per-repo `prune_before` strictly-older-than; `RetentionService`
owns cutoffs, one raw window for results + transitions, 13-mo rollup window;
plain-VO policy + fail-at-boot validation in the service; `_maybe_prune` interval
scheduling in the runner, log-and-retry on failure; worker-only wiring; row cap
parked) added to PLAN §7.
Files: `src/sentinel/domain/value_objects.py` (+`RetentionPolicy`),
`src/sentinel/domain/ports.py` (+`prune_before` ×3),
`src/sentinel/application/retention_service.py` (new — service + `RetentionReport`),
`src/sentinel/infrastructure/db/{check_result,state_transition,check_rollup}_repository.py`
(+`prune_before`), `src/sentinel/infrastructure/db/engine.py` (+`deleted_count`),
`src/sentinel/infrastructure/scheduler.py` (+retention dep + `_maybe_prune` +
wiring), `src/sentinel/config.py` (+3 knobs), `backend/.env.example` (+Retention),
`tests/support/fakes.py` (+`prune_before` ×3), the new unit test file + additions to
the three contract files and `test_scheduler.py`.
Follow-ups / parked: per-monitor raw **row cap** (SPEC "and/or"); pruning runs only
in the worker process; no bloat management beyond autovacuum; `RetentionReport` has
no API surface (log only).
Commit(s): `feat(retention): prune raw results, transitions, and rollups on a worker
interval (S10.2)`.
Resume hint: start S11 (frontend scaffold, design source `docs/design/`) — or S13
(containerize) if the frontend is deferred; the backend feature set through S10 is
complete and green.

### S10.1 — SSRF guard on outbound user-supplied URLs  · 2026-07-16
Done: Every outbound user-supplied URL is now resolve-then-validated before anything
is sent (SPEC §6, sentinel-security §3): monitor probe URLs, auth-source login URLs,
and webhook channel URLs. Two pure functions in `domain/logic/url_guard.py` —
`invalid_url_reason` (rejects non-http(s) schemes and host-less URLs syntactically)
and `blocked_ip_reason` (classifies one resolved IP: loopback, link-local incl. the
metadata endpoint `169.254.169.254`, private incl. `fc00::/7`, unspecified,
multicast, reserved; IPv4-mapped IPv6 is unwrapped so `::ffff:10.0.0.1` can't smuggle
v4 ranges; an unparseable value is blocked, fail-closed). Reasons are short and
**secret-free** — never the URL/host/IP, since they flow into
`NotificationLog.detail` and refresh errors and a webhook URL is itself a secret.
`SsrfUrlGuard` (`infrastructure/url_guard.py`) does the I/O half: resolve the host
via an **injected resolver** (default = the event loop's `getaddrinfo`; tests script
it) and block if **any** resolved IP is denied — which is exactly what catches DNS
rebinding (public-looking name → private A record). A literal-IP host is classified
without resolution; a guard-time resolution failure passes the URL through so the
real send fails and gets classified `dns`, not `blocked` (error kinds stay honest).
`GuardedHttpProbe` decorates the `HttpProbe` port, raising
`ProbeError(ErrorKind.BLOCKED)` **before** the inner probe opens a connection — and
because the check pipeline and `AuthTokenService` share one probe instance, wrapping
it at both composition roots (`deps.get_http_probe`/`get_url_guard`, scheduler
`build_runner`) guards probes **and** logins with zero call-site changes: a blocked
monitor URL is one recorded failed `CheckResult` (`error=blocked` — new `ErrorKind`
member; SPEC §4 enum updated, §6 expanded) and a blocked login lands in
`TokenState.last_refresh_error`. `WebhookNotifier` takes the guard directly and
returns `NotifyResult(ok=False, detail="blocked: …")` without sending. Toggle:
`SSRF_GUARD_ENABLED` (default **on**; `.env.example` section documents when off is
acceptable). Telegram (fixed `api.telegram.org` host) and the operator-configured
`HEARTBEAT_URL` are deliberately unguarded (not user input).
Tests: `tests/unit/domain/test_url_guard.py` (32 collected), `tests/unit/
infrastructure/test_url_guard.py` (9), `test_notifiers.py` +2,
`tests/integration/test_check_pipeline_ssrf.py` (3). Suite: **483 passed / 47
skipped** (no DB, +49); **530 passed** with PG (`sentinel_test`). ruff + mypy strict
clean. App boots (`/api/v1/health` 200). Real-wire: the default resolver blocks
`http://localhost` (loopback) and passes `https://example.com`.
Decisions: **D30** (pure classification in domain / resolve in infrastructure with
an injected resolver; one guard instance wrapping the shared probe covers probe +
auth login; webhook guarded directly; blocked = data never a crash; secret-free
reasons; resolution failure defers to the real send's `dns`; redirect re-validation
parked to S14) added to PLAN §7.
Files: `src/sentinel/domain/logic/url_guard.py` (new),
`src/sentinel/infrastructure/url_guard.py` (new — `SsrfUrlGuard`,
`GuardedHttpProbe`), `src/sentinel/domain/value_objects.py` (+`ErrorKind.BLOCKED`),
`src/sentinel/infrastructure/notifiers.py` (webhook guard),
`src/sentinel/interface/api/deps.py` (+`get_url_guard`, wrap probe, guard webhook),
`src/sentinel/infrastructure/scheduler.py` (same wiring), `src/sentinel/config.py`
(+`ssrf_guard_enabled`), `backend/.env.example` (+SSRF section), `SPEC.md` (§4 enum,
§6 scope), the three new test files + `test_notifiers.py`.
Follow-ups / parked: **redirect hops are not re-validated** (httpx follows redirects
inside one send; a public URL could 302 to a private address — needs an httpx
request event hook in `HttpxProbe`; S14 hardening). No allow-list override for
intentionally-private monitor targets (all-or-nothing toggle). S10.2 (retention) is
the second half of S10.
Commit(s): `feat(security): SSRF guard — resolve-then-validate every outbound
user-supplied URL (S10.1)`.
Resume hint: start S10.2 — write the failing `prune_before` contract tests (prunes
old / keeps new / second run deletes 0, ×{memory,pg}) for check-result /
state-transition / rollup repos before the port methods, `RetentionService`, config
knobs, and scheduler interval wiring.

### S9a — Minimal API auth gate  · 2026-07-16
Done: The API can no longer be exposed unauthenticated (sentinel-security §4, PLAN D9).
A single `require_auth` FastAPI dependency (`interface/api/auth.py`) demands
`Authorization: Bearer <AUTH_TOKEN>` on **every** `/api/v1/*` route — reads, writes,
imports, auth sources, channels, and the SSE `/events` stream — leaving only the
`/api/v1/health` liveness probe open (deploy probes need no secret). The token compare
is **constant-time** (`secrets.compare_digest` over encoded bytes); a missing/wrong
credential or non-Bearer scheme raises an interface-level `UnauthorizedError` that the
existing handler registry (D12) maps to the SPEC §5 envelope: `401`, code
`unauthorized`, plus `WWW-Authenticate: Bearer`. Applied in `create_app()` via
`include_router(..., dependencies=[Depends(require_auth)])` on all routers except
`health`, so the gate short-circuits **before** any service/DB dependency resolves and
a future router must opt **in** to being open rather than out of being gated. Both
reads and writes are gated (no writes-only knob — the S11 client sends the token on
every call). **Empty `AUTH_TOKEN` (the default) disables the gate** — decided **open
in dev** over fail-closed (D29) so local dev and the DB-less suite run without
ceremony; `.env.example` gained an "API auth gate" section (generation one-liner +
"NEVER expose without a token"), and S13's compose/runbook must set it. The gate reads
settings via `Depends(get_settings)` — the seam tests override per-app and S14 layers
rate limiting / richer auth onto.
Tests: `tests/integration/test_auth_gate.py` (13 — missing token → 401 envelope +
`WWW-Authenticate`; wrong token / non-Bearer scheme → 401 (response never echoes the
token); valid token → 200; parametrized one-route-per-router sweep proves monitors
(read+write), imports, auth-sources, channels, and SSE `/events` are all gated;
`/health` stays open with the token set; empty token = open). Suite: **434 passed /
47 skipped** (no DB, +13); **481 passed** with PG (`sentinel_test`). ruff + mypy
strict clean. Real-wire smoke: uvicorn booted with `AUTH_TOKEN` set → `/health` 200,
`/monitors` 401 without/with a bad token, `/events` 401.
Decisions: **D29** (one router-wide `require_auth` dependency, everything gated except
`/health`; reads gated too; constant-time compare; interface-level `UnauthorizedError`
→ 401 envelope via D12 registry; empty `AUTH_TOKEN` = dev-open, documented trade-off;
settings via `Depends(get_settings)` as the S14 composability seam) added to PLAN §7.
Files: `src/sentinel/interface/api/auth.py` (new — `require_auth` +
`UnauthorizedError`), `src/sentinel/interface/api/errors.py` (+401 handler),
`src/sentinel/interface/main.py` (gate all routers except health),
`src/sentinel/config.py` (+`auth_token`), `backend/.env.example` (+API auth gate
section), `tests/integration/test_auth_gate.py` (new).
Follow-ups / parked: rate limiting on the 401 path + any per-route scopes are **S14**;
single shared static credential (multi-user auth post-v1); **S13 must set
`AUTH_TOKEN`** in compose/deploy (empty = open); the SSE gate check happens once at
connect (fine for a static token — nothing to revoke mid-stream in v1).
Commit(s): `feat(auth): minimal API auth gate — Bearer AUTH_TOKEN on all /api/v1 (S9a)`.
Resume hint: start S10 — write the failing SSRF-guard unit tests (blocked ranges,
public-host pass, toggle, DNS-rebinding via an injected resolver) before the guard
module, then wire it into probe + auth refresh + webhook notifier; retention/pruning
is the second half (consider an S10.1/S10.2 split).

### S9.3 — `Notifier` adapters + `AlertService` wiring (finishes S9)  · 2026-07-16
Done: Alerting works **end to end** (SPEC §3.7). On a confirmed `StateTransition` the
pipeline now runs pure `should_notify` and, when it says notify, fans out to all
**enabled** channels **exactly once**, sends via the notifier for each `channel.type`,
and records a `NotificationLog` per attempt. New `Notifier` port
(`send(channel, notification) -> NotifyResult`, **never raises**) with three adapters in
`infrastructure/notifiers.py`: `WebhookNotifier` (POST the payload as JSON to
`config["url"]`), `TelegramNotifier` (bot `sendMessage` with `chat_id` + rendered text),
`EmailNotifier` (**parked stub** — SMTP deferred, returns `ok=False`). New `AlertService`
(`application/alert_service.py`) consumes the transition **directly** (not via the S8
`EventBus`), builds `AlertPolicy` from config, decides, and fans out — skipping any
channel where `NotificationLogRepository.exists(channel_id, monitor_id, transition_at)`
(the S9.2 idempotency key), so re-firing the same transition is a no-op. Wired as a
**4th optional `CheckService` dep** (`alerts`) through `maybe_notify(monitor,
transition|None, last_error)` (no-ops on a `None` transition), so the manual path + every
call site stay green; wired into `deps.py` (`get_alert_service` + `get_notifiers` +
notification-log/transition repos) and the scheduler `build_runner`.
Resolved the S9.2 **open question (`recent_transitions` provenance)** with a **dedicated
persisted `state_transitions` store** (D28, option a): new `StateTransitionRepository`
port (`add` / `list_since(monitor_id, since)`) + in-memory fake + `SqlStateTransition
Repository` + `state_transitions` table (surrogate `id`; the `StateTransition` VO has
none; no secrets → no `SecretBox`) + migration `e7f8a9b0c1d2`. `AlertService` **owns**
it: reads prior flips in the flap window **before** appending the current flip (so it's
not double-counted) and appends **regardless of the notify decision** — so suppressed
flips still count toward future flap windows, which the fired-only `NotificationLog`
can't provide and reconstructing from `CheckResult`s would duplicate the state machine
to derive. Replay-safe: `CheckService` only alerts when `advance_state` **confirms** a
flip (a replayed check yields no transition), so `on_transition` fires once per real
flip. Two new value objects (`domain/value_objects.py`): `AlertNotification` (secret-free
payload — monitor name, new status, `since`, last error, deep link, `kind`) and
`NotifyResult` (`ok` + a **secret-free** `detail`). Pure `format_alert_message`
(`domain/logic/notify.py`) renders telegram/email text; the webhook sends structured
JSON. **Secrets:** channel `config` reaches the notifier already decrypted (repo
concern), used only to send; `NotifyResult.detail` is a classification (`"HTTP 500"`, the
exception class name) — **never** the webhook URL or bot token (which can themselves be
secrets, SPEC §6). `AlertPolicy` from global config (`alert_flap_threshold`=5 /
`alert_flap_window_seconds`=600 / `alert_renotify_after_seconds`=0); deep link from
`dashboard_base_url` (empty ⇒ no link). SSRF-guarding the user-supplied webhook URL is
**S10** (the notifier trusts it for now).
Tests: `tests/unit/application/test_alert_service.py` (11), `tests/unit/domain/
test_alert_message.py` (4), `tests/unit/infrastructure/test_notifiers.py` (8 via respx),
`tests/integration/test_state_transition_repository.py` (3 ×{memory,pg}),
`tests/integration/test_check_pipeline_alert.py` (4). Suite: **421 passed / 47 skipped**
(no DB, +30; +3 skips are the PG-only transition contract); **468 passed** with PG
(`sentinel_test`). ruff + mypy strict clean. Composition roots build (API + worker).
Migration verified on a scratch DB: `upgrade head` from base → single head
`e7f8a9b0c1d2`; `downgrade -1` + re-`upgrade head` round-trips. `.env.example` gained the
Alerting section.
Decisions: **D28** (Notifier port + webhook/telegram adapters + email stub;
`AlertService` consuming the confirmed transition directly, exactly-once via
`NotificationLog.exists`, 4th optional `CheckService` dep; `recent_transitions` from a
dedicated persisted `state_transitions` store owned by `AlertService`, appended for every
confirmed flip incl. suppressed, replay-safe; `AlertNotification`/`NotifyResult` VOs +
pure `format_alert_message`; secret-free `detail`; policy + deep-link from config) added
to PLAN §7.
Files: `src/sentinel/domain/value_objects.py` (+`AlertNotification`, +`NotifyResult`),
`src/sentinel/domain/ports.py` (+`StateTransitionRepository`, +`Notifier`),
`src/sentinel/domain/logic/notify.py` (+`format_alert_message`),
`src/sentinel/application/alert_service.py` (new), `src/sentinel/application/
check_service.py` (+`alerts` dep + `_maybe_alert`), `src/sentinel/infrastructure/
notifiers.py` (new), `src/sentinel/infrastructure/db/models.py` (+`StateTransitionRow`),
`src/sentinel/infrastructure/db/state_transition_repository.py` (new),
`alembic/versions/e7f8a9b0c1d2_create_state_transitions_table.py` (new),
`src/sentinel/config.py` (+alert policy + `dashboard_base_url`),
`src/sentinel/interface/api/deps.py` + `src/sentinel/infrastructure/scheduler.py` (wire
AlertService into both composition roots), `backend/.env.example` (+Alerting section),
`tests/support/fakes.py` (+`InMemoryStateTransitionRepository`, +`FakeNotifier`), the five
new test files (+`tests/unit/application/__init__.py`).
Follow-ups / parked: SSRF-guard the webhook URL (**S10**); email SMTP (stub for now);
per-monitor flap/cooldown overrides; periodic "still down" reminder; `state_transitions`
retention/pruning (**S10**); notifiers open a per-send `httpx.AsyncClient` (no shared
pool). SSE `/events` + the whole API still have **no auth gate** — that's **S9a**, next.
Commit(s): `feat(alerts): Notifier adapters + AlertService — idempotent fan-out, flap history (S9.3)`.
Resume hint: start S9a — write the failing auth-gate tests (unauthenticated `/api/v1/*`
→ 401, valid `AUTH_TOKEN` → accepted, constant-time compare) before adding the FastAPI
dependency + `AUTH_TOKEN` config + `.env.example` entry.

### S9.2 — `AlertChannel`/`NotificationLog` persistence + channel CRUD API  · 2026-07-16
Done: The alerting **persistence + CRUD** layer ships (SPEC §3.7, §4). Two entities:
`AlertChannel` (`type` webhook|telegram|email, `name`, `config: dict`, `enabled`; no
audit timestamps — SPEC §4 omits them) and `NotificationLog` (id/channel_id/monitor_id/
transition_to/**transition_at**/fired_at/ok/detail — audit + idempotency). New
`AlertChannelRepository` (add/get/list/update/delete) + `NotificationLogRepository`
(add / `exists(channel_id, monitor_id, transition_at)` / list_for_monitor newest-first)
ports, in-memory fakes, and SQL adapters (`infrastructure/db/alert_channel_repository.py`
— both repos) + rows (`AlertChannelRow`, `NotificationLogRow`) + migration
`d4a1b2c3e5f6` (`alert_channels`; `notification_logs` with a **unique
`(channel_id, monitor_id, transition_at)`** constraint + `channel_id`/`monitor_id`
indexes). **Channel `config` secrets are write-only:** encrypted at rest via `SecretBox`
(`encrypt_secret_config`/`decrypt_secret_config` added to `secret_mapping.py`) and masked
in every response (`redact_config`) — both keyed off the **same** new pure
`is_secret_config_key` heuristic (a config key is secret if it contains
token/secret/key/password/passwd), so encryption and redaction can never drift (mirrors
D18 for headers). Only string secret values are encrypted (non-str like `port`/`use_tls`
pass through). `AlertChannelService` (CRUD; `NotFoundError` → 404) + `POST/GET/GET{id}/
PATCH/DELETE /api/v1/channels` routes with `AlertChannelCreate`/`Update`/`Response` DTOs
(response masks secret config values). Wired `get_alert_channel_repository` +
`get_alert_channel_service` in `deps.py` + registered the router in `main.py`. The
notification-log repo has **no API surface** and is **not yet wired** into a composition
root — S9.3's `AlertService` consumes it.
Spec change: **SPEC §4 `NotificationLog` gained `transition_at`** (the confirmed flip
time, distinct from `fired_at` = send time). The original field list (`transition_to` +
`fired_at`) can't identify *which* transition a row belongs to — down→up→down repeats
`transition_to`, and `fired_at≈now` — so exactly-once idempotency (SPEC §3.7) had no
stable key. `(channel_id, monitor_id, transition_at)` is now the unique idempotency key.
Tests: `tests/unit/domain/test_alert_channel.py` (21 collected — `is_secret_config_key`
[parametrized secret/non-secret], `redact_config` mask/passthrough/no-mutate/empty,
`AlertChannel` blank-name → `ValidationError`, `NotificationLog` construct);
`tests/integration/test_alert_channel_repository.py` (17 with PG — channel CRUD contract
+ notification-log add/list/`exists` idempotency-key semantics, ×{memory,pg}; PG-only
config-ciphertext-at-rest asserts `bot_token` stored encrypted, `chat_id` plaintext);
`tests/integration/test_alert_channel_api.py` (8 — create redacts-but-stores-full /
list+get redacted / 404 / patch enabled+config-replace / delete→404 / blank-name 422).
Suite: **391 passed / 44 skipped** (no DB), +37; **435 passed** with PG (`sentinel_test`).
ruff + mypy strict clean. App boots (`/api/v1/health` 200, `/api/v1/channels` list 200).
Migration verified: `alembic upgrade head` from base on a clean scratch DB (chain ends at
`d4a1b2c3e5f6`), single head, `downgrade -1` + re-`upgrade head` round-trips.
Decisions: **D27** (channel-config secret handling via a shared `is_secret_config_key`
classifier driving both at-rest encryption and API masking; `NotificationLog.transition_at`
+ the `(channel_id, monitor_id, transition_at)` unique idempotency key; `AlertChannel`
carries no audit timestamps so its SQL repo needs no `Clock`; `/api/v1/channels` route;
notification-log repo built + contract-tested now but wired in S9.3) added to PLAN §7.
Files: `src/sentinel/domain/value_objects.py` (+`ChannelType`), `src/sentinel/domain/
entities.py` (+`AlertChannel`, +`NotificationLog`, +`Any` import), `src/sentinel/domain/
logic/redaction.py` (+`is_secret_config_key`, +`redact_config`), `src/sentinel/domain/
ports.py` (+`AlertChannelRepository`, +`NotificationLogRepository`), `src/sentinel/
infrastructure/db/secret_mapping.py` (+config crypto), `src/sentinel/infrastructure/db/
models.py` (+`AlertChannelRow`, +`NotificationLogRow`), `src/sentinel/infrastructure/db/
alert_channel_repository.py` (new — both SQL repos), `alembic/versions/
d4a1b2c3e5f6_create_alert_tables.py` (new), `src/sentinel/application/
alert_channel_service.py` (new), `src/sentinel/interface/api/schemas.py` (+channel DTOs),
`src/sentinel/interface/api/channels.py` (new — router), `src/sentinel/interface/api/
deps.py` + `src/sentinel/interface/main.py` (wire + register), `tests/support/fakes.py`
(+2 fakes), the three new test files, and `SPEC.md` §4 (`NotificationLog.transition_at`).
Follow-ups / parked: **S9.3** — `Notifier` port + webhook/telegram adapters + the
`AlertService` that consumes the transition, runs `should_notify`, fans out to enabled
channels exactly-once (via `NotificationLog.exists`), and logs; wire as a 4th optional
`CheckService` dep + into the scheduler. **Open:** `recent_transitions` provenance for
flap detection (dedicated table vs reconstruct vs log-every-transition — see Next
action). Per-type config **schema** validation (webhook needs `url`, telegram
`bot_token`+`chat_id`, email SMTP fields) is deferred — the entity only enforces a
non-blank name in v1; the S9.3 notifier handles/validates missing keys. Non-string
secret config values are not encrypted (credentials are strings by convention).
Commit(s): `feat(alerts): alert-channel + notification-log persistence + channel CRUD (S9.2)`.
Resume hint: start S9.3 — write the failing `AlertService` test (a confirmed down
transition fires each enabled channel exactly once; re-firing the same transition is a
no-op via `NotificationLog.exists`; disabled/suppressed/below-threshold fire nothing;
a failing notifier records `ok=false`) before the `Notifier` port + adapters and the
`CheckService` wiring. Decide the `recent_transitions` source first.

### S9.1 — Pure `should_notify` (flap damping + cooldown) + alert value objects  · 2026-07-15
Done: The I/O-free notify decision (SPEC §3.7) ships ahead of any channels/adapters.
`domain/logic/notify.py::should_notify(transition, recent_transitions, policy, now) ->
NotifyDecision` is a pure function over a confirmed `StateTransition` and the monitor's
**prior** transitions. **Flap damping** (SPEC §7): counting the current flip plus the
prior transitions still inside `flap_window_seconds`, the flip that first reaches
`flap_threshold` returns one `flapping` summary (`notify=True`), any further flip while
the count stays above the threshold is `suppressed` (`notify=False`), and once old flips
age out of the window normal `transition` alerts resume — a single summary, not a storm.
`flap_threshold < 2` disables damping (a flip needs ≥2 transitions to flap); the flap
window boundary is exclusive (`t.at > now - window`). **Cooldown** (SPEC §3.7): when
`renotify_after_seconds > 0`, a repeat alert for the *same* `to_status` within the
cooldown is suppressed; the default (0) = one alert per confirmed transition. Flap
damping is evaluated first and wins over cooldown. Three new value objects in
`domain/value_objects.py`: `AlertPolicy` (defaults flap_threshold=5 /
flap_window_seconds=600 / renotify_after_seconds=0), `NotifyDecision` (notify/kind/
reason), `NotifyKind` (transition|flapping|suppressed; `notify` is `True` iff kind !=
suppressed). No persistence, adapters, or wiring (S9.2/S9.3).
Tests: `tests/unit/domain/test_notify.py` (13 — transition + recovery notify; flap
below/crossing/above threshold; resume-after-window-clears; window boundary exclusive;
damping disabled `<2`; flap-beats-cooldown; cooldown off-by-default/suppress/elapsed/
per-status). Suite: **354 passed / 35 skipped** (no DB), +13; **389 with PG**
(`sentinel_test`). ruff + mypy strict clean. App imports/boots (in-suite API tests +
explicit import smoke).
Decisions: **D26** (S9 split S9.1/S9.2/S9.3; pure `should_notify` with flap-beats-
cooldown precedence, exclusive window boundary, `flap_threshold < 2` disables; cooldown
is per-`to_status` repeat suppression, default off = one-alert-per-transition;
`AlertPolicy` is a global-config policy VO, not a per-monitor field — the Monitor §4
carries no flap/renotify fields; periodic while-down *reminders* parked) added to
PLAN §7.
Files: `src/sentinel/domain/value_objects.py` (+`NotifyKind`/`AlertPolicy`/
`NotifyDecision`), `src/sentinel/domain/logic/notify.py` (new),
`tests/unit/domain/test_notify.py` (new).
Follow-ups / parked: `AlertChannel`/`NotificationLog` entities + repos + migration +
channel CRUD (secrets write-only via `SecretBox`) are **S9.2**; the `Notifier` port +
webhook/telegram adapters + the `AlertService` that loads recent transitions, runs
`should_notify`, fires enabled channels once (idempotent via `NotificationLog`), and
logs are **S9.3** (consumes the transition **directly**, not via the S8 `EventBus`).
**Open for S9.3:** provenance of `recent_transitions` — a `NotificationLog` records only
*fired* notifications, so flap history needs all transitions incl. suppressed ones
(dedicated store vs reconstruct). Periodic "still down" reminder emitter (scheduler-
driven re-alert gated by the cooldown) is parked — cooldown defaults off and §7 has no
reminder acceptance test.
Commit(s): `feat(alerts): pure should_notify — flap damping + re-notify cooldown (S9.1)`.
Resume hint: start S9.2 — write the failing `AlertChannelRepository` contract test
(create stores encrypted config + redacts on read) and channel-CRUD API test (secret
never returned) before the entities, ports, fakes, SQL repos/models, migration, and
routes/DTOs.

### S8 — SSE live events  · 2026-07-15
Done: `GET /api/v1/events` streams Server-Sent Events to connected dashboards
(SPEC §3.6) so they update without polling. Two event types: `check_completed`
after **every** recorded `CheckResult` and `status_changed` on a **confirmed** state
transition — the point where the `StateTransition` from `advance_state` is finally
consumed. New `EventBus` domain port: `publish(event)` (fan-out, never blocks/raises)
+ `subscribe()` returning an async context manager whose iterator yields events until
the subscriber disconnects, then deregisters. `InProcessEventBus`
(`infrastructure/events.py`) gives each subscriber a bounded `asyncio.Queue`; a full
queue **drops its oldest** event so a slow SSE client stays current instead of stalling
the check pipeline, and a leaked/gone subscriber self-heals on the next publish (its
generator wakes, the write fails, cancellation runs the deregister). Two event VOs in
`domain/value_objects.py`: a new **`CheckCompleted`** (a narrow, **secret-free** summary
— monitor_id/at/success/status_code/latency_ms/error, deliberately smaller than the
`CheckResult` entity so no probed/injected value can leak over the wire) and the
existing **`StateTransition`** reused verbatim as `status_changed` (no duplicate VO);
`Event = CheckCompleted | StateTransition`. The SSE frame — event-name line + compact
JSON `data:` line + terminating blank line (SPEC §5) — is built by `to_sse_frame` in
`interface/api/events.py` (transport concern); the endpoint is a `StreamingResponse`
over `text/event-stream` that subscribes and serializes each event.
`CheckService._advance_state` now **returns** the `StateTransition | None`, and a new
`_publish_events(result, transition)` emits `check_completed` always + `status_changed`
when the transition is non-None (so UNKNOWN→up/down first-confirmation and up↔down both
push; a below-threshold check pushes only `check_completed`). `events` is a **third
optional** `CheckService` dep (mirrors `states`/`rollups`, D20/D24) so the manual path
and every existing call site stay green. Wired into the **API** composition root only
(`get_event_bus`, an `@lru_cache` singleton shared by the check pipeline and `/events`).
Tests: `tests/unit/interface/test_sse_serialization.py` (3), `tests/unit/
infrastructure/test_event_bus.py` (5), `tests/integration/test_events_api.py` (7 — 4
CheckService-publish + route-registered + 2 end-to-end draining the endpoint's
`StreamingResponse.body_iterator`). Suite: **341 passed / 35 skipped** (no DB); **376
with PG** (`sentinel_test`). ruff + mypy strict clean. App boots (`/api/v1/health` 200);
real-wire SSE framing smoke-tested against a live uvicorn (`content-type:
text/event-stream`; both frames byte-correct).
Decisions: **D25** (in-process `EventBus` port + drop-oldest adapter; `check_completed`
every check / `status_changed` only on a confirmed transition; new secret-free
`CheckCompleted` VO + reuse `StateTransition`; frame shape in `interface`; third optional
`CheckService.events` dep; API-only wiring, scheduler deliberately unwired pending a
Redis-backed cross-process bus; tested via `body_iterator` because `httpx.ASGITransport`
buffers and hangs on an infinite stream) added to PLAN §7.
Files: `src/sentinel/domain/value_objects.py` (+`CheckCompleted`, +`Event` alias),
`src/sentinel/domain/ports.py` (+`EventBus`), `src/sentinel/infrastructure/events.py`
(new — `InProcessEventBus`), `src/sentinel/application/check_service.py` (`events` dep,
`_advance_state` returns the transition, +`_publish_events`),
`src/sentinel/interface/api/events.py` (new — router + `to_sse_frame`),
`src/sentinel/interface/api/deps.py` (+`get_event_bus`, wire into `get_check_service`),
`src/sentinel/interface/main.py` (register router), `tests/support/fakes.py`
(+`FakeEventBus`), `tests/unit/interface/{__init__,test_sse_serialization}.py` (new),
`tests/unit/infrastructure/test_event_bus.py` (new),
`tests/integration/test_events_api.py` (new).
Follow-ups / parked: **cross-process delivery** (scheduler worker → API SSE clients)
needs a Redis-backed `EventBus` adapter behind the same port — until then, only
API-triggered (manual) checks push live events; the worker's `CheckService` is
intentionally left without an `events` dep (an in-process bus there would be a no-op
that falsely implies delivery). No server-initiated keepalive comment yet (disconnect
cleanup relies on cancellation + self-heal-on-next-publish; add a keepalive tick if idle
clients need faster reclamation). SSE has **no API-auth gate** yet — S9a covers auth
across the API surface. `max_queue` is a hardcoded default (100), not config.
Commit(s): `feat(events): SSE live events — EventBus port + /events stream (S8)`.
Resume hint: start S9 — write failing unit tests for pure `should_notify` (cooldown +
flap damping over recent transition history, `now` injected) before the `AlertChannel`
entity/repo/migration, the `Notifier` port + adapters, `NotificationLog` idempotency,
and the application wiring that consumes the `StateTransition` on a confirmed flip.

### S7a — Rollups & long-window stats  · 2026-07-14
Done: Long-window (7d/30d) stats are now served from hourly `CheckRollup`s instead
of scanning raw rows (SPEC §6, PLAN D7). Two pure functions in
`domain/logic/rollups.py`: `hour_bucket(at)` (UTC hour truncation) and
`fold_results_into_rollup(existing | None, results) -> CheckRollup` — it
**recomputes** a single hour bucket's aggregate from the raw `CheckResult`s in it
(checks, failures, nearest-rank p50/p95/p99 over timed results, `latency_sum_ms`),
so re-folding the same rows is **idempotent** (no double-count) and the per-bucket
numbers match `compute_stats` restricted to that hour **exactly**. The bucket comes
from `existing.bucket_start` (update) or the first result's hour (create); only
results in that bucket are counted (a wider fetch is safe); no existing + no results
raises `ValueError`; `updated_at` is left `None` (stamped at persistence, D10). Also
`aggregate_rollups(rollups, window) -> Stats`: checks/failures/uptime are exact sums;
latency percentiles are **check-weighted** across the buckets that recorded a latency
(`None` when none) — approximate across heterogeneous buckets, the accepted rollup
trade-off ("within tolerance", SPEC §7). The nearest-rank helper (→
`nearest_rank_percentile`) and a new `uptime_pct(checks, failures)` were promoted to
public in `domain/logic/stats.py` and reused by both paths so raw and rollup stats
can't drift. New `CheckRollup` entity (SPEC §4), `CheckRollupRepository` port
(`get(monitor_id, bucket_start)` / `save` upsert by composite `(monitor_id,
bucket_start)` / `list_for_window`), in-memory fake + `SqlCheckRollupRepository`
(`check_rollups` table, composite PK, migration `c9d2e5f80a14`; `updated_at` via
injected `Clock`; no secrets → no `SecretBox`). `CheckService` gained a **second
optional** `rollups` dep (mirrors `states`, D20): `run_check` → `_advance_rollup`
refetches the result's hour bucket from raw (`list_for_monitor` since=bucket,
until=bucket+1h, `limit=None`) and upserts the recomputed rollup — on **every** path
incl. transport failures. `StatsService.stats` now branches: **24h** from raw
`compute_stats`, **7d/30d** from `aggregate_rollups` over `list_for_window(since=
hour_bucket(window_start(window, now)), until=now)`. Wired into `deps.py`
(`get_stats_service` + `get_check_service`) and the worker `build_runner`.
Tests: `tests/unit/domain/test_rollups.py` (13); `tests/integration/
test_check_rollup_repository.py` (5 × {memory, pg}); `tests/integration/
test_check_pipeline_rollup.py` (5); `test_monitor_stats_api.py` +1 (7d/30d from
rollups) with the harness folding rollups; `test_monitor_api.py` harness wires the
rollup fake. Suite: **326 passed / 35 skipped** (no DB); **361 with PG**
(`sentinel_test`). ruff + mypy strict clean. App boots (`/api/v1/health` 200); all
three composition roots build with the rollup repo wired (no DB opened at import).
Decisions: **D24** (fold recomputes-not-increments for idempotency + exact per-bucket
parity; aggregate uses exact count sums + check-weighted per-bucket percentile
sketches, approximate across heterogeneous buckets; promoted `nearest_rank_percentile`
+ `uptime_pct` to shared; `rollups` a second optional `CheckService` dep; 24h raw /
7d-30d rollup split in `StatsService`; composite-PK `check_rollups`, `updated_at` via
Clock) added to PLAN §7.
Files: `src/sentinel/domain/entities.py` (+`CheckRollup`),
`src/sentinel/domain/logic/rollups.py` (new),
`src/sentinel/domain/logic/stats.py` (`_percentile`→`nearest_rank_percentile`,
+`uptime_pct`), `src/sentinel/domain/ports.py` (+`CheckRollupRepository`),
`src/sentinel/infrastructure/db/models.py` (+`CheckRollupRow`),
`src/sentinel/infrastructure/db/check_rollup_repository.py` (new),
`alembic/versions/c9d2e5f80a14_create_check_rollups_table.py` (new),
`src/sentinel/application/check_service.py` (optional `rollups` dep + `_advance_rollup`),
`src/sentinel/application/stats_service.py` (24h-raw / 7d-30d-rollup branch),
`src/sentinel/interface/api/deps.py` + `src/sentinel/infrastructure/scheduler.py`
(wire rollup repo), `tests/support/fakes.py` (+`InMemoryCheckRollupRepository`),
`tests/unit/domain/test_rollups.py` + `tests/integration/{test_check_rollup_repository,
test_check_pipeline_rollup}.py` (new), `tests/integration/{test_monitor_stats_api,
test_monitor_api}.py` (rollup wiring).
Follow-ups / parked: **rollup retention (13mo)** + raw pruning is **S10** — nothing
prunes `check_rollups` yet. `aggregate_rollups` percentiles are approximate for
heterogeneous hourly distributions and at window edges (partial boundary bucket
included whole); exact for homogeneous buckets, which the parity test uses.
`latency_sum_ms` is persisted per SPEC §4 but not yet read by `aggregate_rollups`
(reserved for a future weighted-mean); percentiles are weighted by `checks`. The
`?include=summary` list still computes 24h from raw per-monitor (N+1, D23) — rollups
don't help the 24h path. The `StateTransition` from `advance_state` is still
unconsumed (S8 event / S9 alert).
Commit(s): `feat(stats): hourly rollups + long-window stats from rollups (S7a)`.
Resume hint: start S8 — write the failing SSE integration test (a connected client
receives `check_completed` after `run_check`, and `status_changed` only on a
threshold crossing) before the event-bus port/fake/adapter, `GET /events`, and the
`CheckService` publish calls (consume `transition_between` here; new optional
`events` dep).

### S7.3 — `/results`, `/stats`, `?include=summary` endpoints  · 2026-07-14
Done: The §3.5 read model ships and **S7 is complete**. Three endpoints, all
orchestrated by a new `StatsService` (`application/stats_service.py`, ports only, no
rules): `GET /monitors/{id}/results?from&to&limit` (windowed, newest-first history;
`from`/`to` map to inclusive `finished_at` bounds via `Query(alias="from")`→`since`/
`until`; `limit` bounded 1..1000; unknown monitor → 404); `GET /monitors/{id}/stats?
window=24h|7d|30d` (a `StatsView` = pure `compute_stats` joined with `status`/`since`
from `MonitorStateRepository` → §5 shape `{window,checks,failures,uptime_pct,
latency_ms:{p50,p95,p99},status,since}`; typed `StatsWindow` param so an unknown
window becomes a `RequestValidationError` → `validation_error` 422 via the existing
handler, D12; unknown monitor → 404; no state/no checks → status `unknown`, since
`null`, uptime `0.0`, percentiles `null`); and `GET /monitors?include=summary`
(attaches a `MonitorSummary` DTO per monitor: `status`, `since`, `last_check_at`, 24h
`uptime_pct`, 24h `latency_p95_ms`, `checks` — **N+1** by design, one
`MonitorState.get` + one 24h `compute_stats` per monitor, acceptable at v1; the
`summary` field is `null` without the flag). `CheckResultRepository.list_for_monitor`
gained optional `since`/`until` (inclusive `finished_at`) + `limit: int | None`
(`None` = no cap) on the port, the in-memory fake, and `SqlCheckResultRepository`
(conditional `.where()` + `.limit(None)`); the stats path fetches the **whole window
unbounded** and `compute_stats` re-filters (S7 computes from raw; long-window rollups
are S7a). New public `window_start(window, now)` helper in `domain/logic/stats.py`
keeps the window math DRY. New DTOs (`schemas.py`): `StatsResponse`/
`LatencyPercentilesDTO`/`MonitorSummaryDTO`, and `MonitorResponse` gained an optional
`summary`. Wired `get_stats_service` in `deps.py`. The `StateTransition` from
`advance_state` remains **unconsumed** (S8 event / S9 alert).
Tests: `tests/integration/test_monitor_stats_api.py` (12, via `httpx.ASGITransport`
with in-memory fakes + `dependency_overrides`, D13 — results newest-first / from-to
window inclusive / limit / 404; stats match a 10-check fixture [9 latencies 100..900
+ 1 timeout → uptime 90.0, nearest-rank p50=500/p95=p99=900] with status+since /
window selects 24h-vs-7d / no-data→unknown / unknown-window→422 / unknown-monitor→404;
summary attaches status+since+last_check+uptime+p95+checks / no-state→"no data" /
plain list `summary=null`); 3 new `CheckResultRepository` contract tests
(none-limit→all, since/until window inclusive, since composes with limit) × {memory,
pg}. `test_monitor_api.py` fixture now also overrides `get_stats_service` (the list
route composes it). Suite: **302 passed / 30 skipped** (no DB); **332 with PG**
(`sentinel_test`; the new window/`limit=None` SQL verified against real Postgres).
ruff + mypy strict clean. App boots (`/api/v1/health` 200).
Decisions: **D23** (S7.3 read model via `StatsService`; `list_for_monitor` gains a
`[since, until]` window + unbounded `limit`; summary richer than the SPEC minimum to
feed the `docs/design/` dashboard; typed-enum window → 422; N+1 summaries;
`window_start` helper) added to PLAN §7.
Files: `src/sentinel/application/stats_service.py` (new — `StatsService` +
`StatsView`/`MonitorSummary`), `src/sentinel/domain/logic/stats.py`
(+`window_start`), `src/sentinel/domain/ports.py` (`list_for_monitor` since/until/
`limit|None`), `src/sentinel/infrastructure/db/check_result_repository.py` (window
filter), `src/sentinel/interface/api/schemas.py` (+stats/summary DTOs, `MonitorResponse.
summary`), `src/sentinel/interface/api/monitors.py` (+`/results`, `/stats`,
`?include=summary`), `src/sentinel/interface/api/deps.py` (+`get_stats_service`),
`tests/support/fakes.py` (fake `list_for_monitor` window),
`tests/integration/{test_monitor_stats_api.py (new), test_check_result_repository.py,
test_monitor_api.py}`.
Follow-ups / parked: **7d/30d are computed from raw** unbounded scans — S7a replaces
them with hourly rollups (`fold_results_into_rollup` + `aggregate_rollups` +
`CheckRollup`/repo/migration, and fold in `run_check`). The `?include=summary` N+1 is
fine at v1 but would batch nicely once rollups exist. Summary omits a "group"/tag
rollup (dashboard groups are a frontend concern, S11). `from > to` yields an empty
list (not an error, by design).
Commit(s): `feat(stats): results/stats/summary read endpoints via StatsService (S7.3)`.
Resume hint: start S7a — write failing unit tests for `fold_results_into_rollup`
(idempotent per hour bucket) + `aggregate_rollups` (weighted percentiles, parity vs
raw within tolerance) before the `CheckRollup` entity/repo/migration, folding into
`run_check`, and switching `StatsService` to serve 7d/30d from rollups.

### S7.2 — `MonitorState` persistence + wire into check pipeline  · 2026-07-14
Done: A monitor's up/down rollup now persists and advances automatically. New
`MonitorStateRepository` port (`get(monitor_id) -> MonitorState | None`,
`save(state)` upsert — one row per monitor, keyed by `monitor_id`) with an
in-memory fake (`InMemoryMonitorStateRepository`) and a `SqlMonitorStateRepository`
mapping `MonitorState`↔`MonitorStateRow` (`MonitorStatus` stored as text, `since`/
`last_check_at` timestamptz; **no secrets → no `SecretBox`**). New `monitor_states`
table + Alembic migration `e11783af3b0a` (`upgrade head` from base verified clean).
`CheckService` gained an **optional** `states` dep (mirrors the optional auth deps,
D20 — keeps the manual-check path + pre-S7.2 tests green unchanged). `run_check`
was refactored to `_probe_and_record(monitor) -> CheckResult` then
`_advance_state(monitor, result)`, so **every** result — success, failed-assertion,
and transport-failure (`ProbeError`) — folds into the state: `initial_state(id,
result.finished_at)` on first check, then `advance_state(...)` with the monitor's
`failure_threshold`/`recovery_threshold`, then `save`. Counters + `last_check_at`
bump every check; `status`/`since` flip only on a confirmed threshold crossing. The
`StateTransition` is deliberately **not consumed yet** (S8 emits `status_changed`,
S9 fires the alert). Wired into both composition roots (`deps.py` `get_check_service`
and `scheduler.py` `build_runner`), so scheduled + manual checks both track state.
Tests: `tests/integration/test_monitor_state_repository.py` (4 × {memory, pg} =
8 — get-missing→None, full-field round-trip, save-is-upsert-one-row-per-monitor,
unknown-state/null-last_check round-trip); `tests/integration/test_check_pipeline_
state.py` (3 — fail×2→confirmed DOWN then success→UP with counters/`since`/
`last_check_at` advancing across a moving `FixedClock`; transport-failure advances
as a failure; no-state-repo→still probes + records, state untouched). Suite:
**287 passed / 27 skipped** (no DB); **314 with PG** (`sentinel_test`). ruff + mypy
strict clean. App boots; `get_check_service` + `build_runner` both construct with
the state repo wired (no DB opened at import).
Decisions: none new (under **D22**). Notable choices: `states` is an **optional**
`CheckService` dep (parity with the optional auth deps, D20) so the manual-check
path and every existing `CheckService(...)` call site stay green without edits;
state advances on the transport-failure path too (a down endpoint counts toward the
failure threshold, SPEC §3.8); `MonitorState` carries no secrets so the SQL repo
needs no `SecretBox`; `save` returns the passed-in entity (no server-side mutation
to reflect back). Caveat surfaced: integration repo tests set up schema via
`create_all`/`drop_all` (bypassing alembic) and leave `alembic_version` stamped, so
`alembic revision --autogenerate` against a used test DB mis-detects every table as
new — the migration was hand-trimmed to just `monitor_states` and verified via a
clean `upgrade head` from base (consistent with S1's autogenerate-drift follow-up).
Files: `src/sentinel/domain/ports.py` (+`MonitorStateRepository`, +`MonitorState`
import), `src/sentinel/domain/logic/state.py` (unchanged — reused),
`src/sentinel/infrastructure/db/models.py` (+`MonitorStateRow`),
`src/sentinel/infrastructure/db/monitor_state_repository.py` (new),
`alembic/versions/e11783af3b0a_create_monitor_states_table.py` (new),
`src/sentinel/application/check_service.py` (optional `states` dep + `_advance_state`
+ `run_check` refactor), `src/sentinel/interface/api/deps.py` (wire state repo),
`src/sentinel/infrastructure/scheduler.py` (wire state repo into `build_runner`),
`tests/support/fakes.py` (+`InMemoryMonitorStateRepository`),
`tests/integration/{test_monitor_state_repository,test_check_pipeline_state}.py` (new).
Follow-ups / parked: the `/results` (from/to window) + `/stats` + `?include=summary`
endpoints are S7.3; long-window stats from rollups is S7a; the `StateTransition` is
consumed in S8/S9. Consider an autogenerate-drift guard (or stamping the test DB via
alembic) so future autogen isn't misleading — parked (also noted in S1).
Commit(s): `feat(state): MonitorState persistence + fold into check pipeline (S7.2)`.
Resume hint: start S7.3 — write the failing API tests (`GET /monitors/{id}/results`
with from/to, `GET /monitors/{id}/stats?window=`, list `?include=summary`) before
extending `list_for_monitor` with a from/to window and assembling the stats response
from `compute_stats` + `MonitorState` (status/since).

### S7.1 — Pure state + stats logic + value objects/entity  · 2026-07-14
Done: The I/O-free heart of SPEC §3.8 (state) and §3.5 (stats) is in place — no
DB, no network, `now`/timestamps always injected. `domain/logic/state.py`:
`initial_state(monitor_id, at)` (unknown, zero counters, since=at, no last check);
`advance_state(state, result, *, failure_threshold, recovery_threshold) ->
MonitorState` folds one `CheckResult` into the next state — the consecutive
counters and `last_check_at` update every check, `status` flips to `down`/`up`
only after `failure_threshold`/`recovery_threshold` consecutive outcomes, and
`since` moves to the result's `finished_at` only on a flip; `transition_between(
before, after) -> StateTransition | None` yields the confirmed up↔down change
(`at = after.since`), else `None`. `domain/logic/stats.py`: `compute_stats(
results, window, now) -> Stats` filters to `[now - window, now]` (cutoff
inclusive), counts checks/failures, `uptime_pct = round((checks-failures)/checks*
100, 2)` (0.0 on an empty window — callers read `checks == 0` as "no data"), and
computes nearest-rank p50/p95/p99 over only the results that recorded a latency
(transport failures excluded; `None` when none). New value objects `MonitorStatus`
(up/down/unknown), `StatsWindow` (24h/7d/30d), `StateTransition`, `Stats`, and the
`MonitorState` entity (SPEC §4). No persistence/endpoints (S7.2/S7.3).
Tests: `tests/unit/domain/test_state.py` (8) + `tests/unit/domain/test_stats.py`
(8). Suite: **280 passed / 23 skipped** (no DB); **303 with PG**. ruff + mypy
strict clean. App boots (`test_health` green in-suite).
Decisions: **D22** (S7 split S7.1/S7.2/S7.3; the "derive_transition" decision
realized as a clean `advance_state` fold + separate `transition_between` read to
avoid duplicated counter logic — deviates from the tentative single-function name
in PLAN §5; nearest-rank percentiles returning observed integer ms; empty-window
uptime `0.0`; `Stats` omits status/since which come from `MonitorState`) added to
PLAN §7.
Files: `src/sentinel/domain/value_objects.py` (+`MonitorStatus`/`StatsWindow`/
`StateTransition`/`Stats`, +`UUID` import), `src/sentinel/domain/entities.py`
(+`MonitorState`), `src/sentinel/domain/logic/state.py` (new),
`src/sentinel/domain/logic/stats.py` (new),
`tests/unit/domain/{test_state,test_stats}.py` (new).
Follow-ups / parked: persistence (`MonitorStateRepository` + `monitor_states`
table + migration) and wiring `advance_state` into `CheckService.run_check` is
S7.2; the `GET /results` / `GET /stats` / `?include=summary` endpoints are S7.3;
long-window stats from rollups is S7a. The `StateTransition` from `advance_state`
is not consumed yet (S8 event / S9 alert).
Commit(s): `feat(state): pure state-transition + stats logic + value objects (S7.1)`.
Resume hint: start S7.2 — write the failing integration test that a sequence of
checks advances + persists `MonitorState` (status/since/counters), then add the
`MonitorStateRepository` port + fake + `SqlMonitorStateRepository` + `monitor_states`
migration and fold `advance_state` into `CheckService.run_check` (load-or-init →
advance → save).

### S6 — Scheduler runner  · 2026-06-27
Done: The probe loop now runs on a cadence. A worker
(`python -m sentinel.infrastructure.scheduler`, `just worker`) selects due enabled
monitors and probes them automatically. Pure decisions live in
`domain/logic/scheduling.py`: `select_due_monitors(monitors, now, last_run_by_id)`
(enabled + never-run-or-`now >= next_run_at`, input order; disabled never selected),
`next_run_at(monitor, last_run)` (`last_run + interval + jitter`), and
`jitter_seconds(id, interval)` (deterministic per-monitor offset in
`[0, interval*0.1)` from the id's bytes — no RNG/clock; **non-negative** so a check
is never selected *before* its interval, satisfying SPEC §7 "not before"). The async
`SchedulerRunner.run_cycle` lists monitors → `select_due` → probes each due one via
the **reused `CheckService.run_check`** (auth injection + assertions + persistence
all inherited) under an `asyncio.Semaphore` (bounded concurrency), records each run
time, then pings the `Heartbeat` — **every cycle, even idle**. A check that raises
is logged + skipped (attempt time recorded to avoid a hot-loop) so the cycle never
crashes (SPEC §3.3). `run_forever` seeds then loops on `scheduler_poll_seconds`
until a stop event (SIGINT/SIGTERM). **Skip-don't-backfill** is structural: boolean
selection returns a monitor at most once per cycle and the next run is computed from
the *actual* run time. Schedule state is an in-memory `last_run_by_id` map
**seeded on startup from each monitor's most recent `CheckResult.finished_at`**
(`seed_schedule`), so a restart resumes the cadence instead of re-probing all at
once (SPEC §6) — no `last_check_at` column added (deferred to S7's `MonitorState`).
New `Heartbeat` port (`domain/ports.py`) + `NullHeartbeat`/`HttpxHeartbeat`
adapters (`infrastructure/heartbeat.py`): the dead-man's switch (PLAN D8) GETs
`HEARTBEAT_URL` each cycle, **never raises** (a watchdog outage can't crash the
runner), no-op when unset. The worker is a **second composition root**
(`build_runner` in `infrastructure/scheduler.py`) wiring concrete adapters directly,
not importing `interface/api/deps.py`, so the dependency rule holds.
Tests: `tests/unit/domain/test_scheduling.py` (12 — jitter determinism/window/
spread, next_run interval+jitter, due-at-boundary-inclusive, not-before, never-run,
disabled-never, jitter-delays-due, gap→single (no backfill), mixed-set order);
`tests/integration/test_scheduler.py` (7 — cycle probes+records both, disabled not
probed, heartbeat each cycle, heartbeat-when-idle, just-probed-not-due-same-instant,
seed-resumes-from-results→0 probes, one-failing-check-doesn't-abort);
`test_scheduler_loop.py` (1 — `run_forever` cycles then stops on event);
`test_heartbeat.py` (3 — ping GETs the URL via respx, swallows ConnectError, Null
inert). Suite: **264 passed / 23 skipped** (no DB); **287 with PG** (no skips).
ruff + mypy strict clean. Web app boots (`/api/v1/health` 200); worker module
imports + `build_runner` constructs without a live DB.
Decisions: **D21** (pure scheduling decisions; non-negative deterministic jitter;
skip-don't-backfill via boolean selection; thin runner reusing `CheckService` with
bounded concurrency + per-check failure isolation; in-memory last-run map seeded
from persisted results, no `last_check_at` column yet; `Heartbeat` port + Null/Httpx
adapters that never raise; worker as a second infra composition root) added to
PLAN §7.
Files: `src/sentinel/domain/logic/scheduling.py` (new),
`src/sentinel/domain/ports.py` (+`Heartbeat`),
`src/sentinel/infrastructure/heartbeat.py` (new),
`src/sentinel/infrastructure/scheduler.py` (new — runner + `build_runner`/`main`),
`src/sentinel/config.py` (+`heartbeat_url`/`scheduler_poll_seconds`/
`scheduler_max_concurrency`), `tests/support/fakes.py` (+`FakeHeartbeat`),
`tests/unit/domain/test_scheduling.py`, `tests/integration/{test_scheduler,
test_scheduler_loop,test_heartbeat}.py` (new). (`just worker` recipe already
existed.)
Follow-ups / parked: extract a shared composition module so the worker
(`build_runner`) and the API (`deps.py`) don't duplicate adapter wiring (minor
drift risk). Multi-worker `SELECT … FOR UPDATE SKIP LOCKED` claim path is documented
but not built (single-worker is v1). The heartbeat's per-process `HttpxHeartbeat`
client is never explicitly closed in `run_forever` (process-lifetime). An explicit
`last_check_at`/`MonitorState` (and state transitions/stats) is S7. `.env.example`
not yet updated with the three new scheduler vars (add in S7/S13 docs pass).
Commit(s): `feat(scheduler): due-selection + jitter + async runner with heartbeat (S6)`.
Resume hint: start S7 — write failing unit tests for `derive_transition`
(failure/recovery thresholds) and fixture-based `compute_stats` (uptime % +
percentiles over a window, `now` injected) before `MonitorState`, the repo, and the
`GET /results` / `GET /stats` / `?include=summary` endpoints.

### S5b.4 — Probe-pipeline injection + proactive/reactive refresh + single-flight  · 2026-06-27
Done: A monitor linked to an auth source is now authenticated automatically.
`CheckService.run_check` (deps now optionally carry `auth_sources` + an
`AuthTokenService`) loads the `AuthSource` when `monitor.auth_source_id` is set,
**proactively** resolves a token (`ensure_fresh`: `resolve_auth` → refresh on
`NeedsRefresh`), `apply_injection`s it into the probe request, then probes. If the
response status ∈ the source's `refresh_on_status` (default 401/403) **and** no
refresh already happened this cycle, it **reactively** refreshes once + retries the
probe once — capped at one refresh per check, no loops; a persistent 401 evaluates
to one failed `CheckResult` (`error=assertion`). `AuthTokenService` gained
`ensure_fresh(source, now) -> (plan, did_refresh)`, `force_refresh`, a per-source
single-flight `asyncio.Lock` (double-checked inside the lock so a herd triggers one
login), and a `_grant_plan` that tries the **OAuth2 refresh-token grant first when a
refresh token is cached, falling back to the mode's primary grant** (full login) on
failure. A wholly failed refresh records `last_refresh_error` and **keeps any
existing valid token**. The injected token is decrypted at use (TokenStore) and
never lands in a stored sample (`CheckResult` stores none) — the decrypt-at-use
half of D18. `CheckService` was refactored into small helpers (`_inject`,
`_maybe_reactive_retry`, `_send`, `_record`); the no-auth path is unchanged.
Tests: `tests/integration/test_probe_auth_injection.py` (6 — cached-token-injected,
missing→proactive-refresh→inject, 401→one-refresh+one-retry, persistent-401→one
failed-check-no-loop, oauth refresh-token reuse, reuse-failure→client_credentials
fallback) via `FakeHttpProbe` + in-memory fakes, calling `run_check` directly.
Suite: 241 passed / 23 skipped (no DB); **264 with PG**. ruff + mypy strict clean.
App boots (`/api/v1/health` 200).
Decisions: **D20** (auth owned by `AuthTokenService`; one-refresh-per-check via
`did_refresh`; single-flight double-check; `_grant_plan` reuse-then-fallback;
failed refresh preserves a valid token; optional `CheckService` auth deps) added to
PLAN §7.
Files: `src/sentinel/application/auth_token_service.py` (rewritten:
ensure_fresh/force_refresh/locks/grant-plan/reuse+fallback),
`src/sentinel/application/check_service.py` (auth injection + reactive retry,
refactored helpers), `src/sentinel/interface/api/deps.py` (wire auth into
`get_check_service`), `tests/integration/test_probe_auth_injection.py` (new).
Follow-ups / parked: `AuthSource.request` is required even for oauth modes (the
builder ignores it; a stub url suffices) — could become optional for oauth sources
(parked, minor wart). The single-flight lock is per-process (fine for the single
worker; revisit if the scheduler ever runs multi-process). `cert_expiry_days` on the
login request isn't asserted. Scheduler that drives `run_check` on a cadence is S6.
Commit(s): `feat(auth): probe-pipeline token injection + proactive/reactive refresh + single-flight (S5b.4)`.
Resume hint: start S6 — write failing unit tests for pure `select_due_monitors` +
`next_run_at` (Clock injected) before the async scheduler worker, jitter, and the
`HEARTBEAT_URL` ping; reuse `CheckService` (auth already wired). Add `just worker`.

### S5b.3 — Auth-source CRUD + manual-refresh API  · 2026-06-27
Done: The auth source has a full API. `POST/GET/GET{id}/PATCH/DELETE
/api/v1/auth-sources` (CRUD via new `AuthSourceService`) + `POST
/api/v1/auth-sources/{id}/refresh`. **Every credential is redacted in responses**
(SPEC §6): the login `request.body` → `••••`, secret request headers via the shared
`redact()`, oauth `client_secret`/`password` → `••••` (`client_id`/`username` kept
as identifiers). `GET/{id}` and refresh include a metadata-only `token_state`
summary `{status, obtained_at, expires_at, last_refresh_error}` where `status` comes
from the new pure `token_status(state, now) -> TokenStatus` (valid/expired/error/
none) — **the token value is never serialized**. The refresh use case
(`AuthTokenService`) builds the mode's token request (custom → `build_token_request`;
oauth2_client_credentials/password → `build_oauth_token_request`; oauth2_refresh →
refresh-token grant from the cached token), probes via `HttpProbe`, runs
`extract_token`, and saves the cached `TokenState`; a `ProbeError`/`TokenExtractionError`
is **recorded** as `last_refresh_error` (→ `status=error`, HTTP 200) and **keeps any
previously valid token** (no drop on a transient IdP blip). `MonitorService` gained
an optional `AuthSourceRepository` and now rejects a monitor whose `auth_source_id`
doesn't exist (`ValidationError` → 422); wired in `deps.py` (existing monitor unit
tests pass `None` → validation skipped, still green). New `TokenStatus` enum.
Tests: `tests/integration/test_auth_source_api.py` (12 — create-redacts-but-stores-
full, oauth client_secret redaction, list, get+token_state=none, get-404, patch,
delete→404, refresh→metadata-only/no-token-leak/cached, refresh-failure→error-status,
refresh-404, monitor-rejects-unknown-source, monitor-accepts-existing-source) via
`dependency_overrides` with in-memory fakes + `FakeHttpProbe`; `test_auth.py` +5
`token_status` cases. Suite: 235 passed / 23 skipped (no DB); **258 with PG**. ruff
(incl. fixing an over-broad `"u" in text` test assertion → exact credential-payload
check; replaced a production `assert` with a guard) + mypy strict clean. App boots.
Decisions: none new (under D19). Notable choices: refresh failures are HTTP 200 with
`status=error` (consistent with §3.3 "transport problems are results"); a failed
refresh preserves an existing valid token; `last_refresh_error` (non-secret) is
included in the metadata alongside the skill's `{status, obtained_at, expires_at}`;
`client_id`/`username` shown, `client_secret`/`password`/body masked.
Files: `src/sentinel/application/auth_source_service.py` (new),
`src/sentinel/application/auth_token_service.py` (new),
`src/sentinel/application/monitor_service.py` (+auth_source_id validation),
`src/sentinel/domain/value_objects.py` (+`TokenStatus`),
`src/sentinel/domain/logic/auth.py` (+`token_status`),
`src/sentinel/interface/api/schemas.py` (+auth-source DTOs + redaction helpers),
`src/sentinel/interface/api/auth_sources.py` (new routes),
`src/sentinel/interface/api/deps.py` (+repo/store/services wiring),
`src/sentinel/interface/main.py` (register router),
`tests/integration/test_auth_source_api.py` (new),
`tests/unit/domain/test_auth.py` (+token_status).
Follow-ups / parked: probe-pipeline injection + proactive/reactive refresh +
single-flight + refresh-token reuse is S5b.4. List does not include `token_state`
(kept cheap; GET/{id} does). Manual refresh uses the primary grant per mode (reuse
optimisation is S5b.4). `value_template`/`refresh_on_status` not deeply validated
beyond shape.
Commit(s): `feat(auth): auth-source CRUD + manual-refresh API, redacted (S5b.3)`.
Resume hint: start S5b.4 — write the failing `CheckService`-with-auth integration
tests (inject→probe; 401→one refresh+one retry; persistent-401→one failed check;
refresh-token reuse+fallback) before wiring `resolve_auth`/`apply_injection` into
`run_check`, extending `AuthTokenService` for refresh-token reuse, and adding the
per-source `asyncio.Lock` single-flight.

### S5b.2 — `AuthSource`/`TokenState` persistence (repo + `TokenStore` + migration)  · 2026-06-27
Done: The auth source persists. New `AuthSourceRepository` (add/get/list/update/
delete) and `TokenStore` (load/`save`-as-upsert — one cached `TokenState` row per
source) ports with in-memory fakes (`InMemoryAuthSourceRepository`,
`InMemoryTokenStore`). `SqlAuthSourceRepository` maps `AuthSource`↔`AuthSourceRow`
(request/oauth/extractor/expiry/injection as JSONB; mode/token_type/status as
scalars) and `SqlTokenStore` maps `TokenState`↔`TokenStateRow`. **At-rest
encryption via the injected `SecretBox`** (SPEC §6, PLAN D18): the login `request`
body (= credentials), secret-bearing request headers, and oauth `client_secret`/
`username`/`password` are ciphertext in the row; the cached `token`/`refresh_token`
likewise — all decrypted on read so the entity carries plaintext and the domain/
application layers stay crypto-free. The shared header crypto was promoted from the
monitor repo's private `_encrypt_headers`/`_decrypt_headers` into
`infrastructure/db/secret_mapping.py` (`encrypt_value`/`decrypt_value`/
`encrypt_secret_headers`/`decrypt_secret_headers`); the monitor repo now imports it
(no behaviour change). New `auth_sources` + `token_states` tables + Alembic
migration `a7c3f1e9d2b4` (head). The monitors table already had `auth_source_id`.
Tests: `tests/integration/test_auth_source_repository.py` (memory + PG contract —
custom + oauth round-trip, timestamps, get-missing, list, update-preserves-created_at,
delete; token-store save/load/overwrite/load-missing; **2 PG-only** ciphertext-at-
rest checks: request body + oauth client_secret, and token + refresh_token).
`test_monitor_row_mapping.py` repointed at the shared module. Suite: 218 passed /
23 skipped (no DB); **241 passed with PG** (`sentinel_test`). `alembic upgrade head`
verified clean from base. ruff + mypy strict clean. App boots (`/api/v1/health` 200).
Decisions: none new (under D18/D19 — at-rest encryption stays at the repo boundary,
shared classifier; TokenStore decrypts the token on `load`, so the application layer
never touches `SecretBox`).
Files: `src/sentinel/domain/ports.py` (+`AuthSourceRepository`,`TokenStore`),
`src/sentinel/infrastructure/db/secret_mapping.py` (new, shared crypto),
`src/sentinel/infrastructure/db/monitor_repository.py` (use shared crypto),
`src/sentinel/infrastructure/db/models.py` (+`AuthSourceRow`,`TokenStateRow`),
`src/sentinel/infrastructure/db/auth_source_repository.py` (new),
`src/sentinel/infrastructure/db/token_store.py` (new),
`alembic/versions/a7c3f1e9d2b4_create_auth_source_tables.py` (new),
`tests/support/fakes.py` (+2 fakes),
`tests/integration/test_auth_source_repository.py` (new),
`tests/unit/infrastructure/test_monitor_row_mapping.py` (repointed).
Follow-ups / parked: CRUD + manual-refresh API + monitor `auth_source_id`
validation is S5b.3; probe injection + proactive/reactive refresh + single-flight
is S5b.4. `query_params` secrets in the login request are not encrypted (v1 — body
+ secret headers cover credentials); revisit if a source ever puts a secret there.
Commit(s): `feat(auth): AuthSource/TokenState persistence — repos, TokenStore, migration (S5b.2)`.
Resume hint: start S5b.3 — write the failing auth-source API tests (create→redacted,
refresh→metadata-only) before the DTOs/service/routes and `deps.py` wiring; redact
`request.body` + credential headers + oauth secrets; refresh returns status +
obtained_at/expires_at only.

### S5b.1 — Pure auth-source logic + value objects/entities  · 2026-06-27
Done: The I/O-free heart of the token provider (SPEC §3.9) is in place — no
network, no DB, `now` always injected. New `domain/logic/auth.py` with five pure
functions: `build_token_request` (custom mode → a copy of the stored login
request), `build_oauth_token_request` (RFC 6749 form body for
client_credentials/password/refresh_token grants; `client_auth=basic` → an
`Authorization: Basic` header, `body` → client_id/secret in the form),
`extract_token` (reads the access token via json_path/header/regex — regex uses the
first capturing group else the whole match — captures `refresh_token` best-effort
from the JSON body, and computes `expires_at` from `ttl_seconds` /
`json_path_seconds` / `absolute_path` (epoch or ISO); raises `TokenExtractionError`
when a path/pattern/expiry doesn't resolve), `resolve_auth` (the refresh decision:
`NeedsRefresh` when no/empty token, expired, or `now >= expires_at − refresh window`
[boundary inclusive], else an `InjectionPlan`), and `apply_injection`
(header/query/body placement via `value_template`, non-mutating; body sets a field
in the JSON-object body). New `AuthSource` + `TokenState` entities (invariants:
non-blank name, oauth required for oauth2_* modes) and the auth value objects —
`TokenExtractor`, `ExpirySpec`, `Injection`, `OAuthConfig` (+ optional secret
`username`/`password` for the password grant), `Token`, `InjectionPlan`,
`NeedsRefresh`, and the `AuthSourceMode`/`ExtractorKind`/`ExpiryKind`/
`InjectionTarget`/`ClientAuth`/`OAuthGrant` enums. `TokenExtractionError` added
(a `DomainError`). Reuses the S5.1 JSONPath resolver for token/expiry paths.
Tests: `tests/unit/domain/test_auth.py` (33 — extract success for
json_path/header(case-insensitive)/regex(+/-group), not-found + non-JSON raise,
ttl/json-path-seconds/absolute(epoch+ISO) expiry, refresh-token capture/absence;
oauth body+basic client auth, refresh-token + password grants; resolve_auth
missing/empty/valid/expired/at-boundary/just-outside/no-expiry; injection
header/query/body(+empty body)/custom-token-type/non-mutating; three AuthSource
invariants). Suite: 208 passed / 11 skipped (no DB). ruff (incl. 4 targeted
`# noqa: S105` on grant-name/token-type string constants) + mypy strict clean.
App boots (`/api/v1/health` 200).
Decisions: **D19** (S5b split into four sub-slices, pure-logic-first; `Token` omits
`token_type` (config-governed); `OAuthConfig` gains `username`/`password`; RFC-6749
client-auth placement; JSON-object body injection; boundary-inclusive refresh
window) added to PLAN §7.
Files: `src/sentinel/domain/logic/auth.py` (new),
`src/sentinel/domain/value_objects.py` (+auth VOs/enums),
`src/sentinel/domain/entities.py` (+`AuthSource`,`TokenState`,+ defaults),
`src/sentinel/domain/errors.py` (+`TokenExtractionError`),
`tests/unit/domain/test_auth.py` (new).
Follow-ups / parked: persistence (repo/`TokenStore`/migration) is S5b.2; CRUD +
manual refresh is S5b.3; probe injection + proactive/reactive refresh + single-flight
is S5b.4. Capturing a login response's own `token_type` (vs the config default) is
parked. `oauth2_refresh` mode's initial-grant mapping is decided in S5b.4's
orchestration (the pure builder just takes a grant).
Commit(s): `feat(auth): pure auth-source logic + value objects/entities (S5b.1)`.
Resume hint: start S5b.2 — write the failing `AuthSourceRepository`/`TokenStore`
contract test (memory + PG, ciphertext-at-rest assertion) before the rows,
migration, and `Sql*` adapters with `SecretBox` encryption.

### S5a — Secret-at-rest (`SecretBox`, key-ring)  · 2026-06-27
Done: Monitor secret-bearing header values are now **encrypted at rest**. New
`SecretBox` port (`encrypt(str) -> bytes` / `decrypt(bytes) -> str`,
`domain/ports.py`) + `FernetSecretBox` adapter (`infrastructure/secrets.py`) over
`cryptography.fernet.MultiFernet`: the ring is parsed from `SECRET_KEY` (comma-
separated Fernet keys) — **encrypt with the first key, decrypt with any**, so
rotating is prepend-a-key-and-redeploy with no re-encryption. Encryption is
**transparent at the `SqlMonitorRepository` boundary** (`_encrypt_headers` on write,
`_decrypt_headers` on read); the `Monitor` entity always carries plaintext (SPEC §4)
and the DB row never does. Which headers are secret is decided by the **same**
`is_secret_header` classifier that drives API redaction (promoted from private
`_is_secret` in `domain/logic/redaction.py`) so encryption and redaction can't
drift. `CheckService`/`_to_probe_request` and the whole domain/application layer are
unchanged (crypto-free). `SecretBox` is built lazily (`lru_cache get_secret_box`) in
`deps.py` and injected into both `SqlMonitorRepository` sites; the app boots with no
`SECRET_KEY` (empty ring fails fast only when actually constructed). Shipped
`backend/.env.example` (DATABASE_URL + SECRET_KEY with generation + rotation notes).
Tests: `tests/unit/infrastructure/test_secret_box.py` (7 — round-trip, ciphertext-
not-plaintext, non-deterministic, empty-plaintext, decrypt-after-rotation,
encrypt-with-first-key, empty-ring-raises); `tests/unit/test_config.py` (3 —
`secret_key_ring` split/strip/blank-drop/empty); `tests/unit/infrastructure/
test_monitor_row_mapping.py` (3 — DB-free: secret values ciphered + others pass
through, full round-trip, empty headers); `tests/integration/test_monitor_repository.py`
(+1 Postgres-only: ciphertext in the raw `MonitorRow`, `get` decrypts; fixture now
injects a `FernetSecretBox`). Suite: 175 passed / 11 skipped (no DB); 186 passed
with PG (`sentinel_test`). ruff + mypy strict clean. App boots; `/api/v1/health` 200.
Decisions: **D18** (transparent at-rest encryption at the repo boundary — not at
probe time — keeping domain/application crypto-free; MultiFernet key ring; shared
`is_secret_header`; no migration; `auth.secret_ref` is a non-secret reference; S5b
owns decrypt-at-injection for dynamic tokens) added to PLAN §7.
Files: `src/sentinel/domain/ports.py` (+`SecretBox`),
`src/sentinel/infrastructure/secrets.py` (new),
`src/sentinel/config.py` (+`secret_key`/`secret_key_ring`),
`src/sentinel/domain/logic/redaction.py` (`_is_secret`→`is_secret_header`),
`src/sentinel/infrastructure/db/monitor_repository.py` (encrypt/decrypt headers +
`SecretBox` ctor param),
`src/sentinel/interface/api/deps.py` (+`get_secret_box`, wired into both repos),
`backend/pyproject.toml` (+`cryptography`), `backend/uv.lock`, `backend/.env.example` (new),
`tests/unit/infrastructure/{test_secret_box,test_monitor_row_mapping}.py` (new),
`tests/unit/test_config.py` (new),
`tests/integration/test_monitor_repository.py` (secret_box fixture + at-rest test).
Follow-ups / parked: auth-source credentials + cached tokens + **injected** tokens
(decrypt-at-use) are S5b; `AlertChannel.config` secrets are S9; SSRF guard on
outbound URLs is S10. `auth.secret_ref` stays plaintext (it is a reference, not a
secret). No data migration was needed (no production data; tokens fit the JSONB
column). The empty-ring failure surfaces only when a real `SecretBox` is built —
add a startup config check if/when desired (parked).
Commit(s): `feat(security): encrypt monitor header secrets at rest via SecretBox key-ring (S5a)`.
Resume hint: start S5b — write failing unit tests for the pure auth functions
(`build_token_request`, `build_oauth_token_request`, `extract_token` reusing the
S5.1 JSONPath resolver, `resolve_auth` use-cached-vs-refresh, `apply_injection`)
before the `AuthSource` entity/repo/`TokenStore` and the refresh endpoint; tokens
encrypt via `SecretBox` and decrypt only at injection in `_to_probe_request`.

### S5.2 — Probe adapter + CheckResult persistence + endpoint  · 2026-06-26
Done: `POST /api/v1/monitors/{id}/check` runs one probe immediately, evaluates the
monitor's assertions, persists a `CheckResult`, and returns it. The **`HttpxProbe`**
adapter (`infrastructure/probe.py`) is the only outbound-HTTP site: shared
`AsyncClient`, per-request `timeout`/`follow_redirects`, monotonic-clock latency, a
64 KB-capped body sample, `response_size_bytes`, best-effort HTTPS TLS leaf
`notAfter` → `cert_expires_at`, and transport-failure **classification** into an
`ErrorKind` (timeout / dns via `socket.gaierror` cause / tls via `ssl.SSLError` /
connection / unknown) raised as `ProbeError`. The **`CheckService`** use case
(`application/check_service.py`) orchestrates: load monitor (→ `NotFoundError` 404 if
missing) → build `ProbeRequest` → `HttpProbe.send` → `evaluate_assertions` (S5.1) →
assemble + persist. A `ProbeError` is caught and recorded as a failed `CheckResult`
with its kind — **never** raised as an API error (endpoint stays 200 for a down
endpoint, SPEC §3.3); a failed assertion records `error=assertion`. New `CheckResult`
entity (SPEC §4), `CheckResultRepository` port (in-memory fake + `SqlCheckResultRepository`),
`check_results` table + Alembic migration `533b92f6…`. The persisted result stores
**no request headers/body sample** (only `assertion_results` + scalars), avoiding
secret leakage into samples pre-injection. `ProbeError` is a non-`DomainError` so the
§5 envelope never turns it into a 4xx/5xx.
Tests: `tests/integration/test_check_result_repository.py` (4×{memory,pg}=8 — all-
field round-trip incl. JSONB assertion_results/ErrorKind, nullable transport-failure
fields, per-monitor newest-first listing, limit); `tests/integration/test_probe_check_api.py`
(5 — pass, failing-assertion→assertion error, transport-failure→recorded-not-raised,
request-built-from-monitor, unknown→404; fake `HttpProbe` via `dependency_overrides`);
`tests/integration/test_httpx_probe.py` (8 — `respx` matrix over the real adapter: 200
pass / 200-fail-assertion / 500 / slow→timeout / malformed-JSON / connection-error /
response-size×2, asserting the persisted result); `tests/unit/infrastructure/test_probe_cert.py`
(2 — OpenSSL `notAfter` parse, incl. space-padded day). Suite: 162 passed / 10 skipped
(no DB), 172 passed with PG. `alembic upgrade head` verified on a fresh DB. mypy strict
+ ruff clean. App boots (`/api/v1/health` 200).
Decisions: **D17** (classify-and-raise in the adapter; record-never-raise in the use
case; CheckResult stores no request/body sample; manual check returns 200; `respx`
matrix + `FakeHttpProbe` API test; `col()` for typed columns) added to PLAN §7.
Files: `src/sentinel/infrastructure/probe.py` (new),
`src/sentinel/application/check_service.py` (new),
`src/sentinel/infrastructure/db/check_result_repository.py` (new),
`src/sentinel/domain/entities.py` (+`CheckResult`),
`src/sentinel/domain/ports.py` (+`CheckResultRepository`),
`src/sentinel/domain/errors.py` (+`ProbeError`),
`src/sentinel/infrastructure/db/models.py` (+`CheckResultRow`),
`alembic/versions/533b92f62713_create_check_results_table.py` (new),
`src/sentinel/interface/api/{schemas.py (+CheckResult DTOs),monitors.py (+check route),deps.py (+probe/check wiring)}`,
`tests/support/fakes.py` (+`InMemoryCheckResultRepository`,`FakeHttpProbe`),
`tests/integration/{test_check_result_repository,test_probe_check_api,test_httpx_probe}.py`,
`tests/unit/infrastructure/{__init__,test_probe_cert}.py`,
`backend/pyproject.toml` (+`respx` dev), `backend/uv.lock`.
Follow-ups / parked: monitor header/`auth` secrets still stored **plaintext** until
S5a (`SecretBox`); auth-source token injection + reactive 401-refresh is S5b; SSRF
guard around the probe URL is S10 (seam noted in `_to_probe_request`/`HttpProbe`
docstrings, not weakened). Live-TLS cert capture is best-effort and not asserted in
CI (no real TLS server in tests) — the parse + the cert-expiry assertion logic are
unit-tested; verify end-to-end against a real HTTPS host manually. `GET
/monitors/{id}/results` (history) + stats land in S7; `list_for_monitor` already
exists on the repo for it.
Commit(s): `feat(probe): httpx probe adapter, CheckResult persistence + manual check endpoint (S5.2)`.
Resume hint: start S5a — write failing unit tests for a `SecretBox` round-trip,
ciphertext-at-rest, and decrypt-after-key-rotation (`MultiFernet`) before adding the
port + impl, the `cryptography` dep, encrypt-on-persist / decrypt-at-probe wiring,
and `.env.example`.

### S5.1 — Assertion engine + probe value objects  · 2026-06-26
Done: The pure heart of the probe is in place (no I/O). `evaluate_assertions(
response, assertions, now) -> list[AssertionResult]` (`domain/logic/assertions.py`)
covers every SPEC §3.4 type — `status_code` (equals/in/range), `max_latency_ms`,
`body_contains`/`body_not_contains` (honours `case_sensitive`, default true),
`json_path_equals`/`json_path_exists`, `header_equals` (case-insensitive name), and
`cert_expiry_days` (`min_days`). Empty list → the §3.4 default (`status_code in
200–299`). The engine **never raises**: malformed JSON, missing/bad path, missing
params, and unknown assertion types each yield a failed `AssertionResult` with a
clear `detail`; `cert_expiry_days` on plain HTTP (no cert) is **skipped**
(`skipped=True, passed=True`) so it can't fail a non-TLS monitor. A small pure
JSONPath resolver (`domain/logic/json_path.py`) supports the SPEC subset (`$`,
dotted keys, `['k']`/`["k"]`, `[n]`/negative) and will be reused by S5b token
extraction. New `domain` value objects: `ProbeRequest`, `ProbeResponse` (incl.
`cert_expires_at`, bounded `body_sample`, `response_size_bytes`), `AssertionResult`,
`ErrorKind`. `HttpProbe` port defined in `domain/ports.py` (adapter is S5.2).
Tests: `tests/unit/domain/test_assertions.py` (37 — every type × pass/fail,
default-2xx parametrized, malformed-JSON-fails-cleanly, missing path, cert
near/far/expired + HTTP-skip, header case-insensitivity, multiple-in-order, and
unknown-type-no-raise). Suite: 143 passed / 6 skipped (no DB; 149 with PG). mypy
strict + ruff clean. App still boots (`/api/v1/health` 200).
Decisions: **D16** (assertion engine is one pure never-raising function with `now`
injected, default-2xx, cert-skip semantics, and a documented JSONPath subset; probe
VOs live in `domain`; `HttpProbe` port now, adapter + persistence in S5.2) added to
PLAN §7.
Files: `src/sentinel/domain/logic/{assertions,json_path}.py` (new),
`src/sentinel/domain/value_objects.py` (+probe VOs), `src/sentinel/domain/ports.py`
(+`HttpProbe`), `tests/unit/domain/test_assertions.py` (new).
Follow-ups / parked: full JSONPath (filters/wildcards/recursive descent) parked —
subset covers SPEC. `ErrorKind` is defined but unused until S5.2 wires it into
`CheckResult` + transport classification.
Commit(s): `feat(probe): pure assertion engine + probe value objects (S5.1)`.
Resume hint: start S5.2 — write the failing integration probe-matrix test
(`respx`: 200 / 200-with-failing-assertion / 500 / slow→timeout / malformed-JSON)
and the `POST /monitors/{id}/check` API test (fake `HttpProbe`) before building the
`HttpxProbe` adapter, `CheckResult` entity/repo/migration, and the probe use case.

### S4 — Postman import  · 2026-06-26
Done: `POST /api/v1/imports/postman` accepts a `multipart/form-data` upload of a
Postman v2.1 collection and returns `{"drafts": [...]}` (reviewable, nothing
persisted). Pure `parse_postman(collection: dict) -> list[MonitorDraft]` flattens
folders depth-first (one draft per request item), resolves `{{var}}` against the
collection's `variable` block (unresolved → one dedup'd per-draft warning, never a
failure), and extracts method (unknown → warn+GET), headers (skips `disabled`),
url (string or object `raw`, host/path fallback), and body (`raw` → JSON via
`options.raw.language` or shape; `urlencoded` → form `a=1&b=2`;
`formdata`/`file`/`graphql` → warn + drop). Request-level `auth` maps bearer/basic
→ an `Authorization` header (other types warn). Draft headers stay **unredacted**
(echo for review, D14). Shared `coerce_method`/`derive_name`/`infer_body_kind`
extracted to `domain/logic/import_common.py` and now back both importers (curl
behaviour unchanged). Route validates the upload: non-JSON / non-object → domain
`ValidationError` → SPEC §5 `validation_error` (422). `CurlImportResponse` renamed
`ImportResponse` (shared by both routes).
Tests: `tests/unit/domain/test_parse_postman.py` (27 — flattening incl. deep nest,
var resolution incl. undefined/dedup/no-block, method/headers/disabled/url-object,
body modes, bearer/basic/other auth, name derive, the §7 3-request acceptance
collection); `tests/integration/test_postman_import_api.py` (5 — §7 acceptance via
a real multipart upload of `tests/support/fixtures/postman_v21.json`, no-redaction,
malformed JSON → 422 envelope, non-object JSON → 422, missing file → 422). Suite:
106 passed / 6 skipped without a DB (112 with PG). mypy strict + ruff clean.
Decisions: **D15** (Postman import reuses the curl pipeline via `import_common`;
collection-`variable`-only var resolution; bearer/basic auth → header; faithful
body-mode handling with warn-and-drop for multipart/file/graphql; multipart
endpoint validates JSON object; `ImportResponse` rename) added to PLAN §7.
Files: `src/sentinel/domain/logic/{import_common,postman_import}.py` (new),
`src/sentinel/domain/logic/curl_import.py` (use shared helpers),
`src/sentinel/interface/api/{schemas.py (ImportResponse),imports.py (postman route)}`,
`backend/pyproject.toml` (+`python-multipart`), `backend/uv.lock`,
`tests/unit/domain/test_parse_postman.py`,
`tests/integration/test_postman_import_api.py`,
`tests/support/fixtures/postman_v21.json`.
Follow-ups / parked: query string still kept in `url` (not split to
`query_params`, same as curl); folder/environment-scoped variables not resolved
(collection `variable` block only, per SPEC); `formdata`/`file`/`graphql` bodies
are dropped with a warning rather than approximated; auth-block tokens land
plaintext in the `Authorization` header until S5a. Config export (monitor →
collection) remains parked (SPEC §8).
Commit(s): `feat(import): parse Postman v2.1 collections into drafts (S4)`.
Resume hint: start S5 — write failing unit tests for
`evaluate_assertions(response, assertions)` (status/latency/body/json_path/header/
`cert_expiry_days`, incl. HTTP-skips-cert) and define the `HttpProbe` port +
`ProbeResponse` before the httpx adapter and `POST /monitors/{id}/check`.

### S3 — curl import  · 2026-06-26
Done: `POST /api/v1/imports/curl` parses a raw curl command into one reviewable
`MonitorDraft` and returns `{"drafts": [...]}` — nothing is persisted. Pure
`parse_curl(command) -> MonitorDraft` handles `-X`/`--request` (incl. `-XPOST`
attached form), `-H`/`--header` (`-H` attached too), `-d`/`--data*` (multiple
joined with `&`, `-d` implies POST), `--url`/bare URL, `-u`/`--user`
(→ `Authorization: Basic <b64>`), `--compressed`, `-L`/`--location`
(→ follow_redirects). Body kind inferred from Content-Type then shape
(json/form/raw). Name derived as `"<METHOD> <path>"`. Unknown flags, unparseable
headers, missing URL, and unsupported methods surface as per-draft `warnings`
(parse never raises). Handles multi-line `\`-continuations and shlex quoting.
Draft headers are returned **unredacted** (review-before-save echo, SPEC §5).
Tests: `tests/unit/domain/test_parse_curl.py` (26 — table-driven: basics, method/
body, body-kind inference, the §7 acceptance curl, flags, robustness);
`tests/integration/test_curl_import_api.py` (5 — §5 shape, no-redaction,
JSON body, warning surfaced, missing `command` → 422 envelope). Suite: 74 passed
/ 6 skipped without a DB; 80 with PG. mypy strict + ruff clean.
Decisions: **D14** (import drafts unredacted + never persisted; `MonitorDraft` is
validation-free; `-u` → Basic header; pure parser called directly from the route,
no use case; documented v1 parser limits) added to PLAN §7.
Files: `src/sentinel/domain/value_objects.py` (+`MonitorDraft`),
`src/sentinel/domain/logic/curl_import.py`,
`src/sentinel/interface/api/{schemas.py (+import DTOs),imports.py}`,
`src/sentinel/interface/main.py` (wire imports router),
`tests/unit/domain/test_parse_curl.py`, `tests/integration/test_curl_import_api.py`.
Follow-ups / parked: query string kept in `url` (not split to `query_params`);
bundled short flags (`-fsSL`) treated as one unknown flag; `--data @file` kept
literally; basic-auth secret stored plaintext in the Authorization header until
S5a. All low-priority; surfaced via warnings where it matters.
Commit(s): `feat(import): parse curl into reviewable monitor drafts (S3)`.
Resume hint: start S4 — write the failing fixture-based unit test for
`parse_postman(collection) -> list[MonitorDraft]` (folder flatten + `{{var}}`
resolution + unresolved-var warning) before the `POST /imports/postman` multipart
endpoint; reuse the S3 draft DTO.

### S2 — Monitor CRUD API (+ header redaction)  · 2026-06-26
Done: Full CRUD over `/api/v1/monitors` — `POST` (201), `GET` list (bare array),
`GET /{id}`, `PATCH /{id}` (partial, re-validated), `DELETE /{id}` (204). Secret
header values are redacted in every response at the serialization boundary
(`Authorization: "Bearer ••••"`, `X-Api-Key: "••••"`), while the full value is
still stored. Domain `ValidationError` → 422 and `NotFoundError` → 404, plus
FastAPI request-validation → 422, all rendered as the SPEC §5 envelope
(`{"error": {"code","message","details?}}`). New `application/MonitorService`
orchestrates the `MonitorRepository`; `interface/api/deps.py` is the composition
root (lazy `lru_cache` session factory + real `SystemClock`), so importing the
app opens no DB connection.
Tests: `tests/unit/domain/test_redaction.py` (11 — scheme-preserving mask, name
set + `*token*/*secret*/*key*` heuristic, case-insensitive, non-mutating);
`tests/integration/test_monitor_api.py` (13 — create/redaction/persistence,
422 on bad bounds + malformed type, list/get/404, patch/422/404, delete/404)
via `httpx.ASGITransport` with the in-memory repo injected through
`dependency_overrides`. Suite: 43 passed / 6 skipped without a DB; 49 with PG.
mypy strict + ruff clean.
Decisions: **D12** (DTOs validate shape; the `Monitor` entity owns semantic
bounds; both validation failures map to one `validation_error` envelope) and
**D13** (API tested via fake repo through `dependency_overrides`; lazy DB wiring;
list = bare array, DELETE = 204, redaction only in `MonitorResponse.from_entity`)
added to PLAN §7. Implements the D5 principle (redaction at one boundary).
Files: `src/sentinel/domain/logic/{__init__,redaction}.py`,
`src/sentinel/domain/errors.py` (+`NotFoundError`),
`src/sentinel/application/{__init__,monitor_service}.py`,
`src/sentinel/infrastructure/clock.py` (`SystemClock`),
`src/sentinel/interface/api/{schemas,errors,deps,monitors}.py`,
`src/sentinel/interface/main.py` (wire router + handlers),
`tests/unit/domain/test_redaction.py`, `tests/integration/test_monitor_api.py`.
Follow-ups / parked: monitor `auth.secret` / header secrets still stored
**plaintext** until S5a (`SecretBox`). `auth.secret_ref` is serialized as-is (a
reference, not a secret value). No API auth gate yet (S9a). List has no
pagination/`?include=summary` yet (S7). SSRF guard on monitor URLs is S10.
Commit(s): `feat(api): Monitor CRUD endpoints with header redaction + error envelope (S2)`.
Resume hint: start S3 — write failing table-driven unit tests for
`parse_curl(command) -> MonitorDraft` (define the `MonitorDraft` value object)
before the `POST /api/v1/imports/curl` endpoint.

### S1 — Monitor entity + repository  · 2026-06-26
Done: `Monitor` domain entity with SPEC §4 invariants (interval ≥30, timeout
1–60, thresholds ≥1, non-blank name/url) + value objects (`HttpMethod`,
`BodyKind`, `AuthType`, `Auth`, `Assertion`). `MonitorRepository` + `Clock`
ports. In-memory fake and a Postgres `SqlMonitorRepository` (SQLModel) both pass
one parametrized contract (add/get/list/update/delete, full field round-trip
incl. JSONB headers/assertions/tags). Alembic (async) initialised; first
migration creates `monitors`; verified `upgrade head` on a fresh DB.
Tests: `tests/unit/domain/test_monitor.py` (12), `tests/integration/test_monitor_repository.py`
(13 = 6 cases × {memory, postgres}, +1). Suite: 19 passed / 6 skipped without a
DB; 25 passed against local PG. mypy strict + ruff clean.
Decisions: **D10** (timestamps stamped in repo via injected Clock, not
`datetime.now()`/server_default) and **D11** (one contract test over fake+PG; PG
skipped without `TEST_DATABASE_URL`; CI runs a `postgres:16` service + `alembic
upgrade head`) added to PLAN §7.
Files: `src/sentinel/domain/{errors,value_objects,entities,ports}.py`,
`src/sentinel/config.py`, `src/sentinel/infrastructure/db/{models,engine,monitor_repository}.py`,
`backend/alembic/**` (+ `versions/6518c1e84b71_create_monitors_table.py`),
`backend/alembic.ini`, `tests/support/fakes.py`,
`tests/integration/test_monitor_repository.py`, `.github/workflows/ci.yml` (PG service).
Follow-ups / parked: secrets in `headers`/`auth` are stored **plaintext** until
S5a adds `SecretBox` encryption (planned). `.env.example` ships in S5a. Contract
test sets up schema via `create_all` (fast) while CI separately proves `alembic
upgrade head` — an autogenerate-drift check could be added later.
Commit(s): `feat(domain): Monitor entity + repository, ports, first migration (S1)`.
Resume hint: start S2 — write the failing API test for `POST /api/v1/monitors`
(201 + Authorization header redacted) before adding the router/DTOs.

### S0 — Scaffold & green harness  · 2026-06-26
Done: `uv`-managed backend project boots and serves `GET /api/v1/health` →
`{"status":"ok"}`. Full gate green: `just test` (1 test), `just lint`
(ruff lint+format), `just types` (mypy strict). `just` installed locally (1.54).
Tests: `tests/integration/test_health.py` — health via `httpx.ASGITransport`.
Decisions: none new (no ADR forced). Notable setup choices: hatchling build
backend with src layout (editable install → `import sentinel` resolves for
pytest/mypy/uvicorn); ruff rule set `E,F,I,UP,B,ASYNC,S,C4,SIM` with `S101`
ignored under `tests/`; mypy `strict`. CI = GitHub Actions (`astral-sh/setup-uv`)
running sync → ruff → mypy → pytest.
Files: `backend/pyproject.toml`, `backend/.python-version`,
`backend/src/sentinel/{__init__,interface/{__init__,main},interface/api/{__init__,health}}.py`,
`backend/tests/integration/test_health.py`, `justfile`, `.github/workflows/ci.yml`,
`README.md`, `.gitignore`.
Follow-ups / parked: pre-commit hooks (ruff+mypy+fast unit) NOT added in S0 —
left in Parking lot to keep S0 minimal; revisit. Frontend toolchain (pnpm) and
docker not installed yet — only needed at S11/S13.
Commit(s): `chore(backend): scaffold S0 green harness — health endpoint, gate, CI`.
Resume hint: start S1 — define the `Monitor` entity in
`backend/src/sentinel/domain/entities.py` and write its invariant unit tests
first (see sentinel-architecture recipe step 1).

---

## Parking lot (cross-slice deferrals & open questions)

- Confirm Fly.io vs Railway/Render as the managed target before S13.
- Single-tenant auth shape (static API token vs basic) — decide by S14.
- Decide retention defaults (age vs row cap) with real data volume in mind.
- Auth source: confirm whether v1 UI surfaces a single shared source or many
  (model supports many; a monitor links to one — see SPEC §3.9).
- **Quick win (recommend in S0):** pre-commit hooks running ruff + mypy + the
  fast unit suite, so "never commit red" is mechanical, not just documented.
- **Quick win (parked):** config export — monitor → curl / Postman collection
  (round-trips the importers); SPEC §8.
- (from SPEC §8) OpenAPI/HAR import, public status pages, maintenance windows.
- **Frontend design spec** committed at `docs/design/` (hi-fi handoff:
  dashboard + add-monitor flows, design tokens, copy, client-side parser specs) —
  source-of-truth for S11–S12.
