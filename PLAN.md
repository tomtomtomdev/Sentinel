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

