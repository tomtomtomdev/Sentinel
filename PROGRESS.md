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

- **Phase:** S2 complete — Monitor CRUD API (redaction + SPEC §5 error envelope).
- **Last green commit:** S2 (see detailed log below).
- **Test suite:** 49 tests. `just test` (no DB) → 43 passed, 6 skipped (PG params).
  With `TEST_DATABASE_URL` set → 49 passed (real Postgres contract).
- **Schema/migrations:** unchanged from S1 — CRUD uses the existing `monitors`
  table; no new migration. Alembic `6518c1e8…` still head.
- **Deployed:** no.

## Next action

➡️ **Begin S3 — curl import** (`PLAN.md §5`). Pure `parse_curl(command) ->
MonitorDraft` in `domain/logic/` (table-driven unit tests over many curl shapes:
`-X`, `-H`, `-d`/`--data*`, `--url`/bare URL, `-u`, `--compressed`, `-L`; unknown
flags → per-draft warning), then `POST /api/v1/imports/curl` returning unsaved
drafts (`{"drafts": [...]}`, never persisted). Treat the curl string as untrusted
data. Read **sentinel-architecture** first. (`MonitorDraft` value object is new.)

---

## Slice checklist (mirror of `PLAN.md §5`)

- [x] **S0** Scaffold & green harness
- [x] **S1** Monitor entity + repository (+ Alembic init)
- [x] **S2** Monitor CRUD API (+ header redaction)
- [ ] **S3** curl import
- [ ] **S4** Postman import
- [ ] **S5** Probe + assertions engine
- [ ] **S5a** Secret-at-rest (`SecretBox` / Fernet)
- [ ] **S5b** Auth source / token provider
- [ ] **S6** Scheduler runner
- [ ] **S7** State, stats & history
- [ ] **S7a** Rollups & long-window stats
- [ ] **S8** SSE live events
- [ ] **S9** Alert channels + notify (cooldown + flap damping)
- [ ] **S9a** Minimal API auth gate
- [ ] **S10** SSRF guard + retention
- [ ] **S11** Frontend scaffold
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
