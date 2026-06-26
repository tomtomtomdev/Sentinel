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

