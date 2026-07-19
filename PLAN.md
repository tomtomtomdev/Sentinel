# Sentinel — Plan

> **How _and in what order_ we build what `SPEC.md` describes.** This file holds
> architecture, the tech-stack decision, the test strategy, and — most
> importantly — the **slice roadmap**: small, vertical, test-first increments
> that each end with a green build and a commit. `PROGRESS.md` tracks which
> slices are done.

---

## 1. Architecture — Clean Architecture, ports & adapters

Dependencies point **inward**. Inner layers know nothing about outer ones.

```
        ┌──────────────────────────────────────────────┐
        │  interface/  (FastAPI routers, DTO schemas)    │  ← HTTP, SSE
        ├──────────────────────────────────────────────┤
        │  application/  (use cases / services)          │  ← orchestration
        ├──────────────────────────────────────────────┤
        │  domain/  (entities + PURE logic + PORTS)      │  ← no I/O, no framework
        └──────────────────────────────────────────────┘
                          ▲ implements ports
        ┌──────────────────────────────────────────────┐
        │  infrastructure/  (DB repos, HTTP probe,       │
        │  notifiers, scheduler runtime, encryption)     │
        └──────────────────────────────────────────────┘
```

**Dependency rule:** `domain` imports nothing from `application`,
`infrastructure`, or `interface`. `application` imports only `domain`.
`infrastructure` and `interface` may import inward but not each other.

**Ports** (Protocols defined in `domain/ports.py`, implemented in `infrastructure/`):
`MonitorRepository`, `CheckResultRepository`, `CheckRollupRepository`,
`MonitorStateRepository`, `AlertChannelRepository`, `NotificationLogRepository`,
`AuthSourceRepository`, `TokenStore` (load/save cached `TokenState`),
`HttpProbe` (executes one request → `ProbeResponse`, incl. TLS cert),
`Notifier`, `Heartbeat` (ping an external watchdog), `Clock`,
`SecretBox` (encrypt/decrypt, key-ring aware).

**Pure domain functions** — the heart of the system and the richest TDD targets,
all with zero I/O:
- `parse_curl(command) -> MonitorDraft`
- `parse_postman(collection) -> list[MonitorDraft]`
- `evaluate_assertions(response, assertions) -> list[AssertionResult]`  (incl. `cert_expiry_days`)
- `select_due_monitors(monitors, now, last_run_at_by_id) -> list[Monitor]`
- `next_run_at(monitor, last_run_at) -> datetime`  (interval + per-monitor jitter; skip-don't-backfill)
- `derive_transition(state, latest_result, thresholds) -> StateTransition | None`
- `should_notify(transition, recent_transitions, policy, now) -> NotifyDecision`  (cooldown + flap damping)
- `compute_stats(results, window, now) -> Stats`  (short windows, from raw)
- `fold_results_into_rollup(rollup | None, results) -> CheckRollup`  (idempotent per bucket)
- `aggregate_rollups(rollups, window) -> Stats`  (long windows, from hourly buckets)
- `redact(headers) -> headers`
- `build_token_request(auth_source) -> ProbeRequest`  (custom mode → login probe)
- `build_oauth_token_request(oauth, grant, refresh_token?) -> ProbeRequest`  (oauth2 grants + refresh reuse)
- `extract_token(response, extractor, expiry, now) -> Token`  (token + refresh_token + expiry)
- `resolve_auth(auth_source, token_state, now) -> InjectionPlan | NeedsRefresh`
  (pure decision: use cached token or refresh) + `apply_injection(request, plan)`

Inject `Clock` everywhere time matters so scheduling/stats are deterministic in tests.

---

## 2. Tech stack (decision + rationale)

**Backend — Python 3.12 + FastAPI.** Monitoring is I/O-bound (many concurrent
outbound requests); FastAPI's async model + `httpx.AsyncClient` fit perfectly,
Pydantic v2 gives clean DTOs and import-parsing validation, and pytest+respx
make probe logic trivially testable. Matches the proven prior health-monitor
stack.

| Concern | Choice | Why / alternatives |
|---|---|---|
| Web framework | **FastAPI + Uvicorn** | async, SSE, Pydantic DTOs, fast tests |
| HTTP probe client | **httpx (async)** | timeouts, redirects; `respx` for tests |
| ORM / models | **SQLModel** (SQLAlchemy 2.0 + Pydantic) | one model shape; raw SQLAlchemy if SQLModel limits bite |
| Migrations | **Alembic** | standard, autogenerate |
| Database | **PostgreSQL 16** | percentiles, JSONB, concurrency |
| Scheduler | **custom asyncio runner** over the pure `select_due_monitors` | testable core; APScheduler(+PG jobstore) or Celery+Redis are the scale-up alternatives |
| Validation/DTO | **Pydantic v2** | shared with FastAPI |
| Secrets at rest | **cryptography (Fernet)** via `SecretBox` port | key from env/secret store |
| Tests | **pytest, pytest-asyncio, respx, coverage** | |
| Lint/format/types | **ruff (lint+format), mypy** | one fast tool + type gate |
| Pkg/runtime | **uv** | fast, lockfile, reproducible |

**Frontend — React 18 + TypeScript + Vite.** Built as a static SPA so it
deploys anywhere and the slice loop stays simple (no SSR infra to test/deploy).

| Concern | Choice |
|---|---|
| Build | Vite + TypeScript |
| Styling | Tailwind CSS |
| Server state | TanStack Query |
| Routing | React Router |
| Charts | Recharts |
| Live | native `EventSource` (SSE) |
| Tests | Vitest + Testing Library; Playwright (later e2e slice) |

> Next.js is a fine alternative if SSR/SEO is later wanted — but a dashboard
> behind auth gains little from it and costs deploy complexity. Decision: Vite SPA.

---

## 3. Repo layout (monorepo)

```
sentinel/
  CLAUDE.md  SPEC.md  PLAN.md  PROGRESS.md  README.md
  .claude/skills/              # Claude Code skill bundles (see §8)
    sentinel-architecture/SKILL.md
    sentinel-auth-source/SKILL.md
    sentinel-probe-and-assertions/SKILL.md
    sentinel-security/SKILL.md
  justfile                     # task runner: just test / run / lint / migrate
  docker-compose.yml           # app + worker + postgres for dev/self-host
  .github/workflows/ci.yml     # (or .gitlab-ci.yml — see §6)
  backend/
    pyproject.toml             # uv-managed
    alembic/
    src/sentinel/
      domain/        # entities.py, value_objects.py, ports.py, logic/*.py
      application/   # use cases (services)
      infrastructure/# db/, probe.py, notifiers/, auth_source.py, scheduler.py, secrets.py
      interface/     # api/ (routers, schemas, deps), sse.py, main.py
      config.py
    tests/
      unit/          # pure domain — no DB, no network
      integration/   # repos vs PG, api via ASGI transport, probe vs test server
  frontend/
    package.json     # pnpm
    src/  tests/
```

Backend and frontend are independently testable and deployable; they share only
the HTTP contract in `SPEC.md §5`.

---

## 4. Testing strategy (the pyramid)

- **Unit (fast, most numerous):** every pure function in `domain/logic/`. No DB,
  no network, no real clock — pass a fake `Clock`. This is where curl/postman
  parsing, assertions, due-selection, transitions, and stats are proven.
- **Integration (fewer):** repositories against a real Postgres (CI service
  container or testcontainers); API endpoints via `httpx.ASGITransport` against
  the app; the `HttpProbe` against a tiny local test server fixture (or `respx`).
- **Contract checks:** request/response shapes asserted against `SPEC.md §5`.
- **Frontend:** component tests (Vitest + Testing Library); one happy-path
  Playwright e2e once the UI stabilizes.
- **Discipline:** test-first. **Prefer fakes over mocks** (in-memory repo, fake
  probe, fake clock) — assert on observable behaviour, not call counts. Keep a
  meaningful coverage floor on `domain/` (target ≥ 90%) but don't chase 100%.

---

## 5. Slice roadmap

Each slice is a thin vertical increment. **Definition of Done per slice**
(full version in `CLAUDE.md`): tests written first and green · build runs ·
ruff + mypy clean · `PROGRESS.md` updated · one or more Conventional Commits ·
repo left green so context can be cleared safely. Pick the next unchecked slice;
don't batch.

- **S0 — Scaffold & green harness.** Repo, `uv` backend project, `pyproject`,
  ruff/mypy config, pytest, `justfile`, `GET /api/v1/health`, one passing test,
  CI workflow. _DoD: `just test` green on a fresh clone._
- **S1 — Monitor entity + repository.** `domain` entities + `MonitorRepository`
  port; in-memory fake + SQLModel impl; Alembic init + first migration.
  Unit tests on entity invariants; integration test on the PG repo.
- **S2 — Monitor CRUD API.** Routers + DTO schemas + validation; create/list/
  get/patch/delete; **header redaction at the serialization boundary**.
  API tests via ASGI transport; assert redaction.
- **S3 — curl import.** Pure `parse_curl` → `MonitorDraft`; `POST /imports/curl`.
  Table-driven unit tests over many curl shapes; endpoint test.
- **S4 — Postman import.** Pure `parse_postman` (folders flatten, `{{var}}`
  resolve, warnings); `POST /imports/postman` multipart. Fixture collections.
- **S5 — Probe + assertions engine.** `HttpProbe` port + httpx impl (captures
  TLS leaf `notAfter` on HTTPS); pure `evaluate_assertions` incl.
  `cert_expiry_days`; `POST /monitors/{id}/check` persists a `CheckResult`.
  Unit-test assertions exhaustively (incl. cert expiry, HTTP-skips-cert);
  integration-probe a local test server (200, 500, slow, timeout, bad-JSON).
- **S5a — Secret-at-rest (`SecretBox`, key-ring).** `SecretBox` port +
  **`MultiFernet`** impl (key ring from `SECRET_KEY`; encrypt with first,
  decrypt with any) so keys rotate without breaking stored ciphertext; encrypt
  monitor auth secrets on persist, decrypt only at probe time; ship
  `.env.example`. _Pulled ahead of the auth source, which caches live secrets._
  Unit-test round-trip, ciphertext-at-rest, and decrypt-after-rotation.
- **S5b — Auth source / token provider.** `AuthSource` entity (+ `mode`:
  custom / oauth2 grants) + repo + `TokenStore`; pure `build_token_request`,
  `build_oauth_token_request`, `extract_token`, `resolve_auth`,
  `apply_injection`; auth-source CRUD + `POST /auth-sources/{id}/refresh`;
  monitor gains `auth_source_id`; probe pipeline injects the token, refreshes
  proactively (expiry window) and reactively (one refresh + one retry on
  401/403), with **OAuth2 client-credentials build + refresh-token reuse** and a
  per-source single-flight lock. Credentials/tokens encrypted via `SecretBox`,
  redacted everywhere; token never in `CheckResult` samples. Unit-test the pure
  auth logic exhaustively; integration-test inject→probe, 401→refresh→retry, and
  refresh-token reuse against a local server.
- **S6 — Scheduler runner.** Pure `select_due_monitors` + `next_run_at`
  (interval + **per-monitor jitter**, **skip-don't-backfill**); async runner with
  bounded concurrency that loops, probes due monitors, stores results, updates
  `last_check_at`, and emits a **dead-man's-switch heartbeat** (`Heartbeat` port,
  `HEARTBEAT_URL`) each cycle. (Multi-worker path: claim due rows with
  `FOR UPDATE SKIP LOCKED` — documented, single-worker is the default.) Unit-test
  selection/jitter/gap-skip; integration-test one cycle + heartbeat with fakes.
- **S7 — State, stats & history.** `MonitorState`; pure `derive_transition` +
  `compute_stats` (raw, short windows); `GET /results`, `GET /stats`,
  `?include=summary`. Fixture-based stats tests; transition threshold tests.
- **S7a — Rollups & long-window stats.** `CheckRollup` entity + repo; pure
  `fold_results_into_rollup` (idempotent per hour bucket) written as checks
  complete; `aggregate_rollups` serves 7d/30d windows; rollup retention (13mo)
  separate from raw pruning. Unit-test fold idempotency + rollup-vs-raw parity;
  integration-test stats served from rollups.
- **S8 — SSE live events.** Event bus + `GET /events`; emit `check_completed`
  and `status_changed`. Test a client receives an event after a check.
- **S9 — Alert channels + notify (cooldown + flap).** Channel CRUD (secrets
  write-only via `SecretBox`); `Notifier` port + webhook & Telegram impls;
  pure `should_notify` (re-notify cooldown + flap damping over recent
  transitions); idempotent fire via `NotificationLog`. Test exactly-once per
  transition, cooldown suppression, and a flapping monitor → single summary.
- **S9a — Minimal API auth gate.** Static API token / basic-auth dependency
  guarding all `/api/v1/*` write (and optionally read) routes, `AUTH_TOKEN` env,
  `401` when missing/invalid. _Pulled forward so the API is never exposed
  unauthenticated; full hardening stays S14._ Test gated vs allowed requests.
- **S10 — SSRF guard + retention.** URL allow/deny (resolve-then-validate;
  applies to monitor _and_ auth-source URLs), raw result pruning job.
  Tests for blocked ranges and idempotent pruning.
- **S11 — Frontend scaffold.** Vite SPA, API client (sends the auth token),
  dashboard list with status + 24h uptime, monitor detail shell, create form,
  import UI, auth-source manage UI (create/edit/refresh, link a monitor to a
  source). Component tests. **Design source-of-truth:** `docs/design/`
  (hi-fi handoff — dashboard + add-monitor screens, tokens, copy, parser specs).
- **S12 — Frontend charts + live.** Latency chart (Recharts), recent runs table,
  live status via `EventSource`. Component tests.
- **S13 — Containerize & deploy.** Multi-stage Dockerfiles, `docker-compose.yml`
  (app + worker + postgres), Fly.io config + release migration step, README
  runbook **with a "do not expose without the S9a auth gate" warning**.
  Smoke-test the compose stack.
- **S14 — Hardening.** Rate limiting, structured logging, `/health` deepening,
  error-envelope consistency pass, key-rotation runbook. (Minimal auth gate
  already shipped in S9a.)

---

## 6. Deployment plan

Frontend slices (S11–S12) may proceed in parallel once the API contract is
stable (after S7), against a mock server if needed.

- **Local / self-host (primary path):** `docker-compose up` →
  `web` (FastAPI), `worker` (scheduler runner), `db` (Postgres). One command,
  one box. This is the target Tommy will most likely run.
- **Managed (recommended): Fly.io.** Suits a long-running process + background
  worker + Postgres better than serverless. Run web as the app process and the
  scheduler as a second process (Fly process group) sharing the DB; migrations
  in the release command. _Alternatives: Railway or Render (both handle a
  persistent worker + managed PG)._ Avoid Vercel/Lambda for the backend — the
  scheduler needs a long-lived process.
- **Frontend:** ship the Vite static build either served by the backend
  (simplest, one origin, no CORS) or on Vercel/Netlify/Cloudflare Pages.
- **CI:** GitHub Actions by default (`just test`, ruff, mypy, frontend tests on
  PR). A `.gitlab-ci.yml` equivalent is a drop-in for the self-hosted GitLab
  Runner if preferred — same `just` recipes either way.
- **Config:** 12-factor env vars — `DATABASE_URL`, `SECRET_KEY` (comma-separated
  key ring for `MultiFernet` rotation), `AUTH_TOKEN` (API gate), `HEARTBEAT_URL`
  (dead-man's switch, optional), `SSRF_GUARD_ENABLED` (default on), channel creds.
  Provide `.env.example`; no secrets in the repo.
- **⚠️ Do not expose the API to the internet without the S9a auth gate enabled.**
  The README runbook states this explicitly; self-host-on-localhost is fine
  pre-gate, public binding is not.

---

## 7. Decision log (ADR-lite)

- **D1 — Python/FastAPI over Node.** I/O-bound workload, Pydantic parsing,
  proven prior stack, strong async HTTP + test tooling.
- **D2 — Custom asyncio scheduler over Celery/APScheduler (for now).** Keeps the
  scheduling _decision_ a pure, testable function; defer heavy infra until scale
  demands it. Revisit at multi-instance / >a few thousand monitors.
- **D3 — Vite SPA over Next.js.** Dashboard behind auth doesn't need SSR;
  simpler to test and deploy as static assets within the slice loop.
- **D4 — Fakes over mocks; inject `Clock`.** Behaviour-first tests; deterministic
  time-dependent logic.
- **D5 — Redaction & encryption at boundaries, not scattered.** One serialization
  guard for redaction, one `SecretBox` port for at-rest crypto — auditable.
- **D6 — Auth source as a first-class resource, not a monitor flag.** Token
  generation has its own request, extractor, expiry, and injection config and is
  shared across many monitors; modelling it separately keeps one cached token
  per source and isolates secret handling. The token-use _decision_
  (`resolve_auth`) is a pure function so refresh timing is fully testable.
- **D7 — Hourly rollups for long-window stats.** Raw checks (~1.4M/day at 1k
  monitors @ 1-min) make 7d/30d percentile queries a scan cliff; fold into
  idempotent hourly buckets as checks complete, serve long windows from buckets,
  keep raw only for recent detail. (TimescaleDB is the alternative if rollups
  prove insufficient.)
- **D8 — External dead-man's switch.** A monitor that can't detect its own death
  is broken; the scheduler heartbeats an external watchdog each cycle so a silent
  worker crash is alerted from outside, not mistaken for "all green."
- **D9 — Minimal auth gate before any deploy (S9a), full hardening later (S14).**
  The API must never be internet-exposed unauthenticated; a static token gate is
  cheap and ships well before the deploy slice.

- **D10 — Audit timestamps stamped in the repository via an injected `Clock`,
  not by `datetime.now()` or DB `server_default`.** `Monitor.created_at/updated_at`
  are `None` until persisted; both the in-memory fake and the SQL repo stamp them
  from the injected `Clock` (`created_at` preserved on update, `updated_at` bumped).
  This keeps `domain` free of time calls (D4), makes the fake and real adapter
  behave identically under one contract test, and sidesteps SQLModel/`server_default`
  friction. Columns are `NOT NULL`. (S2's create use case will own the Clock wiring.)
- **D11 — One repository contract test, two backends.** Repo behaviour is asserted
  once and parametrized over the in-memory fake and real Postgres; the Postgres
  param `skip`s when `TEST_DATABASE_URL` is unset, so `just test` is green on a
  fresh clone without a DB while CI (a `postgres:16` service) runs it for real.
  CI also runs `alembic upgrade head` to prove migrations apply.

- **D12 — DTOs validate shape; the domain entity owns semantic bounds.** Pydantic
  request DTOs (`interface/api/schemas.py`) enforce only types/shape; numeric and
  business invariants (interval ≥30, timeout 1–60, thresholds ≥1, non-blank) live
  solely on the `Monitor` entity. Building the entity from a DTO is what enforces
  them, raising a domain `ValidationError`. Both a Pydantic `RequestValidationError`
  and a domain `ValidationError` map to the **same** SPEC §5 envelope with code
  `validation_error` (422); `NotFoundError` → `not_found` (404). One handler set,
  registered on the app — no per-router duplication. Avoids two competing sources
  of truth for the rules.
- **D13 — The API is tested via the in-memory repo injected through
  `dependency_overrides`.** `interface/api/deps.py` is the composition root; the
  real `SqlMonitorRepository` is built lazily (`lru_cache` session factory) so
  importing the app never opens a DB connection. API tests override
  `get_monitor_service` with a fake-backed `MonitorService`, keeping the suite
  DB-free and fast; the Postgres repository contract is proven separately (S1, D11).
  Conventions: list returns a bare JSON array of monitors; `DELETE` returns `204`;
  redaction is applied once in `MonitorResponse.from_entity` (the serialization
  boundary), never in routers.

- **D14 — Import drafts are returned UNREDACTED; importing never persists.**
  `parse_curl` (and later `parse_postman`) produce `MonitorDraft`s echoed back via
  `POST /imports/*` for review-before-save; nothing is stored. Unlike a saved
  `Monitor` (D5/D12), draft header values are **not** masked: the draft is an echo
  of the user's own pasted command, and masking would corrupt the value the client
  posts straight back to `POST /monitors` (it would save `"••••"`). This matches the
  SPEC §5 example (`"X-Api-Key": "k"`). Redaction still applies at the *persisted*
  monitor boundary; logging a command is still forbidden. `MonitorDraft` is a
  validation-free value object (a draft may be incomplete; the create endpoint
  enforces invariants). curl `-u user:pass` maps to an `Authorization: Basic …`
  header (consistent with header handling; no secret store exists until S5a). The
  pure parser is called directly from the route — no `application` use case, since
  there is no I/O to orchestrate. Known v1 limits (logged via warnings or parked):
  query string kept in `url` (not split into `query_params`), bundled short flags
  (`-fsSL`) treated as one unknown flag, `--data @file` kept literally.

- **D15 — Postman import reuses the curl pipeline and stays as faithful as the
  format allows.** `parse_postman(collection: dict) -> list[MonitorDraft]` is a pure
  function (the route does the file read + `json.loads`; the parser never touches
  I/O). Folders flatten depth-first to one draft per request item; `{{var}}`
  resolves **only** against the collection's `variable` block (per SPEC — folder/
  environment scopes are out), unresolved vars are left in place and surface as one
  dedup'd warning each (never a failure, SPEC §7). Shared parsing helpers
  (`coerce_method`, `derive_name`, `infer_body_kind`) were extracted to
  `domain/logic/import_common.py` and now back **both** importers (DRY; curl tests
  unchanged). Request-level `auth` maps bearer/basic → an `Authorization` header
  (consistent with D14's curl `-u`); other auth types warn rather than silently
  drop. Body modes: `raw` (JSON via `options.raw.language` or shape), `urlencoded`
  → form `a=1&b=2` (disabled pairs skipped); `formdata`/`file`/`graphql` can't be
  faithfully represented in one body string, so they warn and drop. Drafts stay
  **unredacted** (D14). The endpoint is `multipart/form-data` (`UploadFile`,
  requires `python-multipart`); a non-JSON upload or non-object JSON raises a domain
  `ValidationError` → the SPEC §5 `validation_error` (422) envelope. The shared
  import response model was renamed `CurlImportResponse` → `ImportResponse`.

- **D16 — The assertion engine is one pure function that never raises, with a
  documented JSONPath subset.** `evaluate_assertions(response, assertions, now) ->
  list[AssertionResult]` lives in `domain/logic/assertions.py`. `now` is passed in
  (not read from a `Clock`) so `cert_expiry_days` math is deterministic. A check's
  `success` is `all(r.passed)`. Robustness rules: an empty assertion list evaluates
  the SPEC §3.4 default (`status_code in 200–299`); a malformed body, a missing/
  bad JSON path, missing params, or an **unknown assertion type** all produce a
  failed `AssertionResult` with a clear `detail` rather than throwing — the engine
  is the pure heart of the probe loop and must never raise. `cert_expiry_days` on
  plain HTTP (no captured cert) is **skipped** (`skipped=True, passed=True`) so it
  never fails a non-TLS monitor. JSONPath is a deliberate **subset** (a small pure
  resolver in `domain/logic/json_path.py`: `$`, dotted keys, `['k']`/`["k"]`, and
  `[n]`/negative indices) covering the SPEC examples and reused later by auth-source
  token extraction (S5b); full JSONPath (filters/wildcards/recursive descent) is
  parked. `ErrorKind`, `ProbeRequest`, `ProbeResponse`, `AssertionResult` are plain
  `domain` value objects so pure code and tests never import httpx; the `HttpProbe`
  port is defined now, its httpx adapter + `CheckResult` persistence land in S5.2.

- **D17 — Probe adapter classifies-and-raises; the use case records-never-raises;
  CheckResult stores no request/body sample.** The `HttpxProbe` adapter
  (`infrastructure/probe.py`) is the only outbound-HTTP site: it measures latency
  with a monotonic clock, caps the body sample (64 KB), and **classifies** httpx
  transport errors into an `ErrorKind` (timeout / dns via `socket.gaierror` cause /
  tls via `ssl.SSLError` / connection / unknown), raising a `ProbeError`.
  `ProbeError` is intentionally **not** a `DomainError`, so it never reaches the
  SPEC §5 envelope as a 4xx/5xx. The `CheckService` use case
  (`application/check_service.py`) catches it and records a failed `CheckResult`
  with that kind; a successful transport whose assertions fail records
  `error=assertion`. `POST /monitors/{id}/check` therefore returns **200 with the
  CheckResult** even for a down endpoint (SPEC §3.3). The persisted `CheckResult`
  deliberately stores **no request headers and no body sample** (only
  `assertion_results` + scalar fields per SPEC §4), which sidesteps secret/injected-
  token leakage into stored samples until S5b adds injection. TLS leaf `notAfter`
  is read best-effort from the response's `network_stream`/`ssl_object` (None on
  plain HTTP or when unavailable, never raises); the OpenSSL date parse is extracted
  to `parse_cert_not_after` and unit-tested. Probe **integration** tests use
  `respx` (added as a dev dep) over the real adapter for the matrix (200 / 200-with-
  failing-assertion / 500 / slow→timeout / malformed-JSON / connection-error),
  asserting the persisted `CheckResult`; the API endpoint is tested with a scriptable
  `FakeHttpProbe` via `dependency_overrides` (D13). Typed column expressions in the
  SQL repo use SQLModel's `col()` to satisfy mypy strict.

- **D18 — Monitor secrets are encrypted transparently at the repository boundary,
  not at probe time.** S5a adds a `SecretBox` port (`encrypt(str) -> bytes`,
  `decrypt(bytes) -> str`) with a `FernetSecretBox` adapter over
  `cryptography.fernet.MultiFernet` (key ring from `SECRET_KEY`, comma-separated;
  **encrypt with the first key, decrypt with any** → rotation is prepend-and-
  redeploy). The `SqlMonitorRepository` is the single encryption boundary: it
  encrypts secret-bearing header values on write (`_encrypt_headers`) and decrypts
  them on read (`_decrypt_headers`), so the `Monitor` entity always carries
  plaintext (SPEC §4) and the DB row never does. This **refines** the earlier
  "decrypt only at probe time / `CheckService` is the decrypt point" note: doing it
  in the repo keeps `domain` and `application` crypto-free (the `CheckService` and
  `_to_probe_request` are unchanged), keeps the repository round-trip contract
  intact, and confines crypto to one auditable place (D5). It still fully satisfies
  SPEC §6 (ciphertext at rest + redaction at the API boundary + MultiFernet
  rotation). Which headers are secret is decided by the **same** `is_secret_header`
  classifier that drives redaction (exported from `domain/logic/redaction.py`), so
  encryption and redaction can never drift. Fernet tokens (ASCII base64) are stored
  as plain strings in the existing JSONB `headers` column — **no migration**, and no
  legacy data to convert. `auth.secret_ref` is a *reference*, not a secret value, so
  it is left untouched; actual auth-source credentials and **dynamically injected
  tokens** are encrypted and decrypted at the point of use in S5b (where
  decrypt-at-injection genuinely applies, since tokens never round-trip through an
  entity or DTO). The `SecretBox` is built lazily (`lru_cache`) in `deps.py`, so the
  app boots without `SECRET_KEY`; constructing it with an empty ring fails fast.
  Ships `backend/.env.example`. Unit tests cover the crypto (round-trip, ciphertext,
  rotation, encrypt-with-first, empty-ring) and the header mapping DB-free; a
  Postgres-only test asserts ciphertext in the raw row.

- **D19 — Auth source (S5b) is built bottom-up in four green sub-slices, pure
  logic first.** S5b is large, so it is split: **S5b.1** the pure, I/O-free auth
  logic + value objects/entities; **S5b.2** `AuthSource`/`TokenState` persistence
  (ports, fakes, rows, migration, SQL repos with `SecretBox`); **S5b.3** CRUD +
  manual-refresh API (redacted); **S5b.4** probe-pipeline injection + proactive/
  reactive refresh + single-flight. The pure layer (`domain/logic/auth.py`) holds
  the five SPEC §3.9 functions and **never raises except `TokenExtractionError`**;
  `now` is injected so the refresh-window decision is deterministic. Design choices
  baked into the value objects: `Token` carries `value`/`expires_at`/
  `refresh_token` but **not** `token_type` — the token *type* is governed by the
  auth-source config (`AuthSource.token_type`, default `Bearer`), so a login
  response's `token_type` field is not captured in v1 (parked). `OAuthConfig` gains
  optional `username`/`password` (secret) to back the `oauth2_password` grant,
  which SPEC §4's field list omitted but the mode requires. `build_oauth_token_request`
  follows RFC 6749: `client_auth=basic` puts identity in an `Authorization: Basic`
  header (not the body), `client_auth=body` puts `client_id`/`client_secret` in the
  form. `apply_injection` body-target sets a field in the JSON-object body (starting
  from `{}` when empty); non-JSON bodies for body injection raise. `extract_token`
  captures `refresh_token` best-effort from the JSON body regardless of extractor
  kind. `resolve_auth` returns `NeedsRefresh` when `now >= expires_at - window`
  (boundary inclusive). The dynamically injected token is decrypted only at the
  point of injection and never lands in a stored `CheckResult` (this is the
  decrypt-at-use case D18 deferred here).

- **D20 — Auth lives in `AuthTokenService`; the probe pipeline caps a check at one
  refresh.** All token behaviour — manual refresh, proactive (`ensure_fresh`) and
  reactive (`force_refresh`) refresh, OAuth refresh-token reuse, and a per-source
  single-flight `asyncio.Lock` — is owned by `AuthTokenService`; `CheckService`
  only resolves+injects and decides the one reactive retry. **One refresh per
  check:** `ensure_fresh` returns `(plan, did_refresh)` and the reactive path
  (status ∈ `refresh_on_status`) fires only when `not did_refresh`, so a check
  triggers at most one login + one retry — no loops; a persistent 401 evaluates to
  a normal failed `CheckResult` (`error=assertion` via the default 2xx assertion).
  **Single-flight:** `ensure_fresh` double-checks the cache inside the per-source
  lock, so a herd of due monitors triggers one login and the rest reuse it.
  **Refresh-token reuse:** `_grant_plan` returns an ordered list of token requests —
  the `refresh_token` grant first when a refresh token is cached, then the mode's
  primary grant as a fallback — and `_refresh_unlocked` tries them in order, so a
  failed refresh-token grant falls back to a full login (SPEC §3.9). A refresh that
  fails entirely is recorded as `last_refresh_error` and **preserves any existing
  valid token** (a transient IdP blip never drops a working token). The injected
  token is decrypted by the `TokenStore` and lives only in memory + the outbound
  request; `CheckResult` stores no request/body sample, so it never lands in a
  stored sample (the decrypt-at-use half of D18). `CheckService`'s `auth_sources`/
  `auth` deps are optional, so probe tests without auth and the manual-check path
  are unaffected.

- **D21 — Scheduler state is an in-memory last-run map seeded from persisted
  results; the runner is a thin loop over pure decisions reusing `CheckService`.**
  S6 keeps the scheduling *decisions* pure in `domain/logic/scheduling.py`:
  `select_due_monitors(monitors, now, last_run_by_id)` (enabled + never-run-or-due,
  in order) and `next_run_at(monitor, last_run_at)` (`last_run + interval + jitter`).
  **Jitter** (`jitter_seconds`) is **non-negative**, deterministic from the monitor
  id (`int.from_bytes(id.bytes) % window`, no RNG/clock so tests assert exact
  values), and bounded by `JITTER_FRACTION=0.1` of the interval — non-negativity
  preserves SPEC §7's "not before `interval`" guarantee while de-bunching the herd.
  **Skip-don't-backfill** falls out of boolean selection plus computing the next run
  from the *actual* run time: a monitor is returned at most once per cycle no matter
  how many ticks were missed. The async `SchedulerRunner`
  (`infrastructure/scheduler.py`) is intentionally thin — list → `select_due` →
  probe each due monitor via the **existing `CheckService.run_check`** (so auth
  injection, assertions, and persistence are reused, not reimplemented) under an
  `asyncio.Semaphore` (bounded concurrency, one hung endpoint can't starve the
  rest), then `Heartbeat.ping()`. A single check that raises is logged and skipped
  (its attempt time recorded to avoid a hot-loop) so the cycle **never crashes**;
  the heartbeat fires every cycle even when nothing is due. **Schedule state is the
  per-monitor last-run time, held in memory and seeded on startup from each
  monitor's most recent `CheckResult.finished_at`** (`seed_schedule`), so a restart
  resumes the cadence instead of re-probing everything at once (SPEC §6) — this
  deliberately avoids adding a `last_check_at` column now (an explicit `MonitorState`
  arrives in S7). New `Heartbeat` port + `NullHeartbeat`/`HttpxHeartbeat` adapters:
  the dead-man's switch (PLAN D8) GETs `HEARTBEAT_URL` each cycle, **never raises**
  (a watchdog outage can't crash the runner), and is a no-op when unset. The worker
  is a **second composition root** living in `infrastructure` (`build_runner`); it
  wires concrete adapters directly rather than importing `interface/api/deps.py`,
  keeping the dependency rule intact (infrastructure never imports interface) at the
  cost of a little wiring duplicated from `deps.py` (parked: extract a shared
  composition module). Config gains `heartbeat_url`, `scheduler_poll_seconds`,
  `scheduler_max_concurrency`.

- **D22 — S7 split into S7.1/S7.2/S7.3; the transition decision is a
  clean fold (`advance_state`) + a separate read (`transition_between`), not one
  `derive_transition`.** State (§3.8) and stats (§3.5) are large enough to violate
  the "couple hours per slice" rule together, so S7 is sequenced: **S7.1** pure
  logic + value objects/entity (done), **S7.2** `MonitorState` persistence + wiring
  the fold into `CheckService.run_check`, **S7.3** the `/results` + `/stats` +
  `?include=summary` endpoints. PLAN §5 tentatively named a single
  `derive_transition(state, result, thresholds) -> StateTransition | None`, but
  that name conflates two jobs: advancing the counters/`last_check_at`/status
  (needed every check, transition or not) and reporting whether a confirmed flip
  happened. Splitting them keeps each pure function single-purpose and avoids
  duplicating the counter-run logic: `advance_state` always returns the next
  `MonitorState` (counters + `last_check_at` bump every check; `status`/`since`
  move only on a threshold crossing, `since = result.finished_at`), and
  `transition_between(before, after)` reads the two statuses to emit the
  `StateTransition` (`at = after.since`) that S8/S9 consume. `compute_stats` uses
  **nearest-rank** percentiles (returns an observed integer ms, no interpolation —
  keeps values honest and JSON-clean), computes them over only the results that
  recorded a latency (transport failures excluded), and returns `uptime_pct = 0.0`
  on an empty window (there is no meaningful uptime without checks; callers read
  `checks == 0` as "no data"). `Stats` deliberately omits `status`/`since` — those
  belong to `MonitorState` and the §5 stats response is assembled from both at the
  endpoint (S7.3).

- **D23 — S7.3 read endpoints go through a `StatsService` read model;
  `list_for_monitor` gains a `[since, until]` window + unbounded `limit`; the list
  summary is richer than the SPEC minimum to feed the dashboard.** The three §3.5
  read endpoints (`GET /monitors/{id}/results`, `/stats`, `?include=summary`) are
  orchestration over existing ports, so they live in one application use case
  (`application/stats_service.py`) rather than in the routers: `history` (windowed,
  newest-first, 404 on unknown monitor), `stats` (a `StatsView` = pure
  `compute_stats` joined with `status`/`since` from `MonitorStateRepository`, since
  `Stats` omits those by D22), and `summaries` (a `MonitorSummary` per monitor).
  `CheckResultRepository.list_for_monitor` was extended with optional
  `since`/`until` (inclusive `finished_at` bounds) and `limit: int | None` where
  `None` means *no cap* — the stats path fetches the **whole window unbounded**
  (`window_start(window, now)`→`now`) and `compute_stats` re-filters; a public
  `window_start` helper in `domain/logic/stats.py` keeps the window math DRY. This
  is the documented S7 "compute from raw" behaviour; **S7a** replaces the unbounded
  7d/30d scan with hourly rollups (SPEC §6, D7). `?include=summary` is **N+1 by
  design** (one `MonitorState.get` + one 24h `compute_stats` per monitor) —
  acceptable at v1 scale and noted in code. The summary DTO carries `status`,
  `since`, `last_check_at`, 24h `uptime_pct`, 24h `latency_p95_ms`, and `checks`
  (SPEC §3.5 only mandates "status + 24h uptime", but the hi-fi dashboard cards in
  `docs/design/` render p95 latency + "last checked", so the extra fields are
  built now rather than bolted on in S11); `checks == 0` disambiguates "no data"
  from a genuine 0% uptime (the D22 empty-window convention). The stats `window`
  query param is typed as the `StatsWindow` enum, so an unknown value becomes a
  `RequestValidationError` → the §5 `validation_error` (422) via the existing
  handler (D12) — no bespoke validation. `results` returns a bare JSON array
  (D13); `from`/`to` map to `since`/`until` via a `Query(alias="from")` (avoids the
  `from` keyword); `limit` is bounded `1..1000`. Because the monitor **list** route
  now composes `StatsService` for the summary branch, its API tests override both
  `get_monitor_service` and `get_stats_service` (the real composition root builds a
  `SecretBox` and would fail fast without `SECRET_KEY`). The `StateTransition` from
  `advance_state` stays unconsumed until S8/S9.

- **D24 — Rollups recompute a bucket from raw (idempotent, per-bucket-exact);
  aggregation sums counts exactly and treats per-bucket percentiles as weighted
  sketches.** S7a serves long windows from hourly `CheckRollup`s (PLAN D7). The pure
  `fold_results_into_rollup(existing | None, results)` **recomputes** a single hour
  bucket's aggregate from its raw `CheckResult`s rather than incrementing the
  existing rollup — a pure function can only be idempotent by recomputing from the
  full input, so this is what guarantees "re-folding a bucket doesn't double-count"
  (SPEC §7) and makes the bucket's checks/failures/percentiles match `compute_stats`
  restricted to that hour **exactly** (nearest-rank, no sketch loss). It is viable
  because folding happens in `CheckService.run_check` right after the check lands,
  when the bucket's raw rows are always present (well inside the 30-day raw window);
  by the time raw is pruned (S10) the rollups are long since frozen. The bucket is
  taken from `existing.bucket_start` (update) or the first result's hour (create),
  and only results in that bucket are counted (so a caller may over-fetch); no
  existing + no results raises. `aggregate_rollups(rollups, window)` sums
  checks/failures/uptime **exactly** but can only **approximate** latency percentiles
  across buckets — it returns a **check-weighted mean of the per-bucket nearest-rank
  values** over buckets that recorded a latency (`None` when none). That is exact for
  homogeneous hourly distributions (the parity test's fixture) and drifts for
  heterogeneous ones — the accepted rollup trade-off ("within tolerance"). It takes
  no `now`: the caller (`StatsService`) fetches only the in-window buckets via
  `list_for_window`, so aggregation is a pure fold over what it's given.
  `latency_sum_ms` is persisted per SPEC §4 (reserved for a future weighted-mean) but
  the v1 aggregate weights by `checks` and doesn't read it. The nearest-rank helper
  (`nearest_rank_percentile`) and `uptime_pct` were promoted to public in
  `domain/logic/stats.py` and shared by both the raw and rollup paths so the two can
  never drift. `CheckService` gains a **second optional dep** `rollups` (mirrors
  `states`, D20) so the manual-check path and every existing call site stay green;
  it folds on every result incl. transport failures. `StatsService.stats` branches:
  **24h from raw** `compute_stats`, **7d/30d from** `aggregate_rollups`. The
  `check_rollups` table uses a **composite primary key** `(monitor_id, bucket_start)`
  for the one-row-per-hour upsert, carries no secrets (no `SecretBox`), and stamps
  `updated_at` via the injected `Clock` (D10). Rollup retention (13mo, distinct from
  raw pruning) is deferred to S10.
- **D25 — Live events go through an in-process `EventBus` port; `check_completed`
  fires every check, `status_changed` only on a confirmed transition; cross-process
  delivery is a deferred Redis drop-in.** S8 adds an `EventBus` Protocol
  (`publish(event)` + `subscribe() -> async ctx mgr yielding an AsyncIterator[Event]`)
  with an `InProcessEventBus` adapter (per-subscriber bounded `asyncio.Queue`; a full
  queue **drops its oldest** event so a slow SSE client stays current; `publish` never
  blocks or raises) and a `FakeEventBus` that records + fans out. `GET /api/v1/events`
  is a `text/event-stream` `StreamingResponse` that subscribes and serializes each
  event to an SSE frame (SPEC §5); the frame's event-name + JSON shape live in
  `interface` (transport), the event VOs in `domain`. Two event types: a new
  `CheckCompleted` VO (a **narrow, secret-free summary** — monitor_id/at/success/
  status_code/latency_ms/error, deliberately smaller than `CheckResult` so no probed/
  injected value can leak over the wire) and the existing `StateTransition` reused
  verbatim as `status_changed` (no duplicate VO). This is **where the `StateTransition`
  from `advance_state` is finally consumed**: `CheckService._advance_state` now returns
  it, `_publish_events` emits `check_completed` always and `status_changed` when the
  transition is non-None — so UNKNOWN→up/down (first confirmation) and up↔down both
  push, but a below-threshold check pushes only `check_completed`. `events` is a
  **third optional `CheckService` dep** (mirrors `states`/`rollups`, D20/D24) so the
  manual path and every existing call site stay green. The bus is **process-local**:
  it's wired into the **API** composition root only (`get_event_bus`, an `@lru_cache`
  singleton shared by the check pipeline and `/events`), so API-triggered checks reach
  their own SSE clients. The **scheduler worker is deliberately NOT wired** — an
  in-process bus can't cross to the API's clients, so wiring it would be a no-op that
  falsely implies delivery; scheduler→SSE needs a Redis-backed adapter behind the same
  port (parked). Tested in-process by driving the endpoint's `StreamingResponse.
  body_iterator` (the exact client-facing stream) rather than `httpx.ASGITransport`,
  which buffers a response to completion and so hangs on an infinite SSE stream;
  real-wire framing was smoke-tested against a live uvicorn.

- **D26 — S9 splits into S9.1/S9.2/S9.3; the notify decision is one pure function
  where flap damping beats cooldown; `AlertPolicy` is a global-config policy VO, not
  a per-monitor field.** S9 (channel CRUD + notifier + wiring + the pure decision) is
  too big for one slice, so it's sequenced: **S9.1** the pure, I/O-free
  `should_notify` + alert value objects (done); **S9.2** `AlertChannel`/
  `NotificationLog` persistence (entities, ports, fakes, rows, migration, SQL repos —
  channel `config` secrets encrypted via `SecretBox`) + channel CRUD API (secrets
  write-only/redacted); **S9.3** the `Notifier` port + webhook/telegram adapters + the
  `AlertService` that consumes the confirmed `StateTransition` **directly** (not via
  the S8 `EventBus`), runs `should_notify`, fires enabled channels exactly once
  (idempotent via `NotificationLog`), and logs. `should_notify(transition,
  recent_transitions, policy, now) -> NotifyDecision` is a single pure function (PLAN
  §1) over the current flip plus the monitor's prior transitions, `now` injected (D4).
  **Flap damping is evaluated first and wins over cooldown:** counting the current flip
  plus prior transitions still inside `flap_window_seconds`, the flip that first
  reaches `flap_threshold` emits one `flapping` summary and further flips above the
  threshold are `suppressed`, then normal `transition` alerts resume once old flips age
  out — one summary, not a storm (SPEC §7). `flap_threshold < 2` disables damping (a
  flip needs ≥2 transitions to flap) and the window boundary is **exclusive**
  (`t.at > now - window`). **Cooldown** (`renotify_after_seconds > 0`) suppresses a
  repeat alert for the *same* `to_status` within the window; the default (0) is
  "one alert per confirmed transition" (SPEC §3.7). `NotifyDecision.notify` is `True`
  iff `kind != suppressed`. **`AlertPolicy` lives in global config, not on the
  Monitor** — SPEC §4's Monitor carries `failure_threshold`/`recovery_threshold` but
  **no** flap/renotify fields, so the flap/cooldown tunables are system-wide for v1
  (S9.3 builds the policy from config); per-monitor overrides are parked. The genuine
  periodic **"still down" reminder** emitter (a scheduler-driven re-alert gated by the
  cooldown) is also parked: cooldown defaults off and §7 has no reminder acceptance
  test, so v1 cooldown is the transition-time repeat-suppression above. **Open for
  S9.3:** where `recent_transitions` come from — a `NotificationLog` records only
  *fired* notifications, so flap history (needs suppressed transitions too) requires a
  dedicated store or reconstruction; decided in S9.3.

- **D27 — Channel-config secrets use one shared key classifier for encryption + API
  masking (as headers do); `NotificationLog` gains `transition_at` as the idempotency
  key.** S9.2 persists alert channels + the notification log. **Config secrets:** an
  `AlertChannel.config` value is secret iff its **key** matches the new pure
  `is_secret_config_key` heuristic (`token`/`secret`/`key`/`password`/`passwd`
  substrings) — the same single classifier drives both at-rest encryption
  (`encrypt_secret_config`/`decrypt_secret_config` in `secret_mapping.py`, only string
  values) and API redaction (`redact_config` masks with `••••`, keeping the key so the
  user sees the setting exists), so the two can never drift — the exact pattern D18
  established for secret *headers* via `is_secret_header`. Secrets are therefore
  write-only over the API (accepted on create/update, masked in every response) and
  ciphertext at rest, satisfying SPEC §6. `AlertChannel` deliberately carries **no
  audit timestamps** (SPEC §4 lists none), so its SQL repo needs no `Clock` — unlike
  `Monitor`/`AuthSource` (D10). **Idempotency key:** SPEC §4's `NotificationLog`
  (`transition_to` + `fired_at`) could not identify *which* transition a row belongs to
  — a down→up→down sequence repeats `transition_to` and `fired_at≈now` — so exactly-once
  (SPEC §3.7) had no stable key. Added **`transition_at`** (the confirmed flip time =
  `StateTransition.at`, distinct from `fired_at` = send time) and a **unique
  `(channel_id, monitor_id, transition_at)`** constraint; the
  `NotificationLogRepository.exists(...)` idempotency check keys on it. SPEC §4 updated.
  The notification-log repo (add/`exists`/`list_for_monitor`) is built + contract-tested
  now but has no API surface and is wired into a composition root only in S9.3 (its sole
  consumer, `AlertService`). Route path is `/api/v1/channels`. Per-type config *schema*
  validation (webhook `url`, telegram `bot_token`+`chat_id`, email SMTP) is deferred to
  S9.3's notifier — the entity enforces only a non-blank name in v1.

- **D28 — S9.3 completes S9: `Notifier` adapters + `AlertService`; flap history from a
  dedicated persisted `state_transitions` store owned by `AlertService`.** The `Notifier`
  port (`send(channel, notification) -> NotifyResult`, **never raises**) has a webhook
  (POST JSON), telegram (bot `sendMessage`), and a **parked email stub** adapter
  (`infrastructure/notifiers.py`); SMTP is deferred, an email channel records a clear
  `ok=False`. `AlertService` (`application/alert_service.py`) consumes the confirmed
  `StateTransition` **directly** (not via the S8 `EventBus`), runs pure `should_notify`,
  and on notify fans out to all **enabled** channels **exactly once** — skipping any
  channel where `NotificationLogRepository.exists(channel_id, monitor_id, transition_at)`
  — sending via the notifier keyed by `channel.type` and recording a `NotificationLog`
  per attempt (`ok`/`detail`). Wired as a **4th optional `CheckService` dep** (`alerts`,
  mirroring `states`/`rollups`/`events`, D20/D24/D25) via a `maybe_notify(monitor,
  transition|None, last_error)` that no-ops on a `None` transition, so the manual path +
  every call site stay green; wired in `deps.py` + the scheduler `build_runner`.
  **Resolved the S9.2 open question — `recent_transitions` provenance = a dedicated,
  persisted `state_transitions` store** (option a): a new `StateTransitionRepository`
  port (`add` / `list_since(monitor_id, since)`), in-memory fake, `SqlStateTransition
  Repository` + `state_transitions` table (surrogate `id`; the `StateTransition` VO
  carries none; no secrets → no `SecretBox`) + migration `e7f8a9b0c1d2`. `AlertService`
  **owns** it: it reads the prior flips inside the flap window *before* appending the
  current flip (so the current one isn't double-counted) and appends **regardless of the
  notify decision**, so suppressed transitions still count toward future flap windows —
  which a `NotificationLog` (fired-only) can never provide, and which reconstructing from
  `CheckResult`s would duplicate the whole state machine to derive. It is naturally
  replay-safe: `CheckService` only invokes alerting when `advance_state` **confirms** a
  flip, and a replayed check yields no transition, so `on_transition` fires once per real
  flip. Two new value objects: `AlertNotification` (secret-free payload — monitor name,
  new status, `since`, last error, deep link, plus `kind` for transition-vs-flapping
  wording) and `NotifyResult` (`ok` + a **secret-free** `detail`). A pure
  `format_alert_message` renders the telegram/email text; the webhook sends the structured
  fields as JSON. **Secrets:** channel `config` reaches the notifier already decrypted
  (repo concern) and is used only to send; a `NotifyResult.detail` is a classification
  (`"HTTP 500"`, the exception class name) **never** the webhook URL or bot token (which
  can themselves be secrets, SPEC §6). `AlertPolicy` is built from **global config**
  (`ALERT_FLAP_THRESHOLD`/`ALERT_FLAP_WINDOW_SECONDS`/`ALERT_RENOTIFY_AFTER_SECONDS`); the
  deep link is built from `DASHBOARD_BASE_URL` (empty ⇒ no link). SSRF-guarding the
  user-supplied webhook URL is **S10** (the notifier currently trusts it).

- **D29 — S9a auth gate: one `require_auth` dependency, router-wide, everything gated
  except `/health`; empty `AUTH_TOKEN` = gate open (dev mode).** A single FastAPI
  dependency (`interface/api/auth.py`) checks `Authorization: Bearer <AUTH_TOKEN>`
  with `secrets.compare_digest` (constant-time) and raises an interface-level
  `UnauthorizedError` mapped to the SPEC §5 envelope (`401`, code `unauthorized`,
  `WWW-Authenticate: Bearer`) by the existing handler registry (extends D12). Applied
  in `create_app()` via `include_router(..., dependencies=[Depends(require_auth)])`
  on **every** router except `health` — reads and writes are both gated (no
  writes-only knob; the S11 client sends the token on every call), the SSE `/events`
  stream included, and a future router must opt **in** to being open rather than out
  of being gated. Settings reach the gate via `Depends(get_settings)` so tests
  override the token per-app. **Empty `AUTH_TOKEN` (the default) disables the gate**
  — chosen over fail-closed so local dev and the existing DB-less suite run without
  ceremony; the trade-off is documented in `.env.example` ("dev only; never expose
  without a token") and the S13 runbook must set it in compose/deploy. The
  dependency is the composability seam S14 layers rate limiting / multi-user auth
  onto. `UnauthorizedError` lives in `interface/` (not `domain/errors.py`): a static
  HTTP credential is a transport concern, not a domain rule.

- **D30 — S10.1 SSRF guard: pure classification in domain, resolve-then-validate in
  infrastructure, one guard instance wrapping the shared probe + injected into the
  webhook notifier; blocked = data, never a crash.** Two pure functions
  (`domain/logic/url_guard.py`): `invalid_url_reason` (non-http(s) scheme / no host)
  and `blocked_ip_reason` (loopback, link-local incl. `169.254.169.254`, private,
  unspecified, multicast, reserved; IPv4-mapped IPv6 unwrapped; unparseable = blocked,
  fail-closed). Reasons are secret-free — never the URL/host/IP — because they land in
  `NotificationLog.detail` and refresh errors, and a webhook URL is itself a secret.
  `SsrfUrlGuard` (`infrastructure/url_guard.py`) resolves via an **injected resolver**
  (default: the loop's `getaddrinfo`) and rejects if **any** resolved IP is blocked
  (defeats DNS rebinding deterministically in tests); a literal-IP host skips
  resolution; a guard-time resolution failure **passes** so the real send fails and is
  classified `dns`, keeping error kinds honest. `GuardedHttpProbe` decorates the
  `HttpProbe` port and raises `ProbeError(ErrorKind.BLOCKED)` pre-send — since the
  check pipeline and `AuthTokenService` share one probe instance, wrapping it at both
  composition roots guards monitor probes **and** auth-source logins with no call-site
  changes; the blocked probe becomes a failed `CheckResult` (`error=blocked`, new
  `ErrorKind` member + SPEC §4 update) and the blocked login a recorded
  `last_refresh_error`. `WebhookNotifier` takes the guard directly (`NotifyResult
  ok=False`); Telegram's host is fixed (no guard); the operator-supplied
  `HEARTBEAT_URL` is deliberately unguarded (config, not user input — a private
  watchdog is legitimate). `SSRF_GUARD_ENABLED` (default **on**) short-circuits
  `check` to pass. Parked: redirects are followed by httpx *inside* one send, so a
  public URL 302→private is not re-validated per hop (needs an httpx request hook;
  S14 hardening).

- **D31 — S10.2 retention: `prune_before(cutoff)` on the three history repos, a
  `RetentionService` owning the cutoffs, scheduled by the worker at most once per
  interval.** Each history store prunes itself: `CheckResultRepository` (by
  `finished_at`), `StateTransitionRepository` (by `at`), `CheckRollupRepository` (by
  `bucket_start`) gain `prune_before(cutoff) -> int` — strictly-older-than semantics
  (a row exactly at the cutoff is kept), one bulk DELETE across **all** monitors, no
  migration needed. `RetentionService` (`application/`) computes cutoffs from a
  `RetentionPolicy` VO (`raw_days=30` for raw results **and** transitions — flips
  older than the flap window have no reader; `rollup_days=396` ≈ 13 months so
  long-range stats survive raw pruning) via the injected `Clock`; naturally
  idempotent (age cutoff), so re-runs delete nothing. The policy VO is a plain
  dataclass like `AlertPolicy` (`value_objects` can't import `errors` — one-way
  invariant); the **service** constructor rejects a non-positive window with
  `ValidationError` so a misconfigured worker fails at boot rather than silently
  deleting everything. Scheduling lives in `SchedulerRunner` (`retention` optional
  dep + `retention_interval_seconds`, default 3600): `_maybe_prune(now)` runs on the
  first cycle then at most once per interval; a pruning failure is logged and
  retried next interval, never a crashed cycle. Worker-only wiring (the API root
  doesn't prune). SPEC's optional per-monitor row cap ("and/or") is parked —
  age-only in v1.

- **D32 — S11 split S11.1–S11.4; frontend scaffold conventions.** S11 (whole SPA)
  is several days of work, so: S11.1 scaffold + app shell + API client, S11.2
  dashboard, S11.3 add-monitor, S11.4 detail shell + auth-source UI. Conventions
  fixed in S11.1: **auth token** read from localStorage (`sentinel.auth_token`)
  with a `VITE_AUTH_TOKEN` env fallback for dev only — Vite env is baked into the
  public bundle, so a deployed build must use the localStorage path (a settings
  surface is a follow-up); one fetch wrapper (`src/lib/api.ts`) owns the S9a
  Bearer header and maps the SPEC §5 error envelope to a typed `ApiError`
  (non-envelope bodies → `http_<status>`), with the base URL resolved absolute
  against the page origin so a relative `/api/v1` works same-origin, under the
  dev proxy (`/api` → `localhost:8000`), and in jsdom tests. **Design tokens**
  live as Tailwind v4 `@theme` variables in `src/index.css` (single source for
  the docs/design palette/fonts). The design's Incidents/Alerts/Status-pages nav
  is **omitted** (v1 out-of-scope per SPEC §8) instead of rendered dead. Frontend
  tests live in `frontend/tests/` (PLAN §3 layout) on Vitest + Testing Library;
  React pinned to 18 per §2.

- **D33 — Live events read via a fetch-based SSE reader, not `EventSource`
  (S12.3).** `EventSource` cannot send an `Authorization` header, so consuming
  the S9a-gated `GET /api/v1/events` with it would have required accepting the
  token as a query parameter — putting a credential into URLs, access logs, and
  browser history (against sentinel-security's redaction posture). Instead the
  client reads the stream with `fetch` + an incremental SSE parser
  (`src/lib/sse.ts`), carrying the same Bearer header as every other API call.
  **Zero backend change** — the S8 endpoint and S9a gate are untouched.
  Trade-offs accepted: no browser-native auto-reconnect (the reader implements
  doubling backoff, reset after a healthy connection, capped at 30s) and no
  `Last-Event-ID` resume (the backend doesn't emit event ids; missed events are
  tolerable because every event triggers a query **invalidation** — a refetch of
  authoritative state — rather than a client-side patch, so the next event or
  refetch self-heals any gap). One app-wide subscription (`useLiveEvents` in
  `AppRoutes`) maps both event kinds to two invalidations: the monitor-list
  summary query and the `["monitors", <id>]` prefix (detail + stats + results →
  chart, runs table, sparkline).
- **D34 — S13 split S13.1–S13.3; containerization architecture.** S13
  (containerize & deploy) is split like S11/S12: **S13.1** backend image +
  compose (`db`→`migrate`→`web`+`worker`), **S13.2** frontend image + reverse
  proxy (single origin), **S13.3** Fly.io config + README runbook.
  - **One backend image, process chosen by command.** The web API and the
    scheduler worker share a single multi-stage image (`backend/Dockerfile`,
    uv builder → slim runtime, non-root uid 10001); the `CMD` defaults to
    `uvicorn`, and the worker/migrate services override it. Avoids two nearly
    identical images and guarantees web+worker run the same code.
  - **Migrations as a one-shot `migrate` service, not an entrypoint.** A
    dedicated compose service runs `alembic upgrade head` to completion; `web`
    and `worker` gate on `service_completed_successfully`. Keeps migration a
    single serialized step (no race between two booting app containers) and
    mirrors Fly's `release_command` (S13.3) so both paths migrate the same way.
    `db` gates the whole thing on a `pg_isready` healthcheck.
  - **`asyncpg` needs no `libpq`, so the runtime stays `python:3.12-slim`** with
    no apt build/runtime deps (cryptography/uvloop/httptools/asyncpg all ship
    cp312 manylinux wheels). `UV_PYTHON_DOWNLOADS=0` pins uv to the base image's
    Python so the copied venv's interpreter matches the runtime stage.
  - **Frontend served by nginx, single origin via `/api` reverse proxy
    (S13.2).** The SPA image (`frontend/Dockerfile`, node+pnpm build → nginx
    runtime) serves the static bundle with a history-fallback and proxies
    `/api/` → the `web` service. This keeps the app one origin — matching the
    dev proxy in `vite.config.ts` — so there's **no CORS to configure and the
    S9a Bearer token never appears in a URL** (D33's posture holds in prod). The
    SPA's default `VITE_API_BASE_URL=/api/v1` needs no build arg, and no token
    is baked into the public bundle (localStorage path only). nginx uses the
    variable+`resolver 127.0.0.11` `proxy_pass` form so it boots even if `web`
    isn't up yet, and sets `proxy_buffering off` + a long `proxy_read_timeout`
    so the S12.3 SSE stream (`/api/v1/events`) isn't buffered. The frontend is
    the entry point (`${FRONTEND_PORT:-8080}`); `web` stays published on 8000
    for debugging.
  - **Docker not available in the build environment** — the compose file is
    validated statically (YAML + anchor merge) and the migration command is
    already exercised by CI (`alembic upgrade head` on `postgres:16`); `pnpm
    build` (the frontend image's build stage) is run locally. But the end-to-end
    container boot is a smoke-test the operator runs on a Docker host
    (documented in the S13.3 runbook), not something verified in-repo.

_Append new decisions here as `Dn — <decision>: <why>` when slices force a choice._

---

## 8. Claude Code skills

Project skill bundles live in `.claude/skills/` and encode the non-obvious,
repeated conventions so every slice stays consistent. Read the one matching the
slice you're on (`CLAUDE.md` says when):

- **sentinel-architecture** — Clean Architecture layering, the dependency rule, and
  the end-to-end recipe for adding a capability (domain → port → fake → SQLModel
  repo + Alembic migration → use case → router/DTO → tests).
- **sentinel-auth-source** — the token-provider feature: entity shape, the pure
  `build_token_request`/`extract_token`/`resolve_auth`/`apply_injection`
  functions, proactive vs reactive refresh, and how tokens are kept out of
  responses, logs, and samples.
- **sentinel-probe-and-assertions** — writing the async `httpx` probe, the pure
  assertion engine, and testing both against `respx` / a local test server
  across 200 / 5xx / slow / timeout / malformed-JSON.
- **sentinel-security** — secret redaction at the serialization boundary, `SecretBox`
  encryption at rest, and the SSRF guard (resolve-then-validate).

