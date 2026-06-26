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

- **Phase:** S4 complete — Postman import (`parse_postman` + `POST /imports/postman`).
- **Last green commit:** S4 (see detailed log below).
- **Test suite:** 112 tests. `just test` (no DB) → 106 passed, 6 skipped (PG params).
  With `TEST_DATABASE_URL` set → 112 passed (real Postgres contract).
- **Schema/migrations:** unchanged from S1 — imports persist nothing; CRUD uses
  the existing `monitors` table. Alembic `6518c1e8…` still head.
- **New dep:** `python-multipart` (FastAPI file uploads). `uv.lock` updated.
- **Deployed:** no.

## Next action

➡️ **Begin S5 — Probe + assertions engine** (`PLAN.md §5`). Add the `HttpProbe`
port + an httpx async adapter (timeouts, redirects, error classification; capture
TLS leaf `notAfter` on HTTPS); a pure `evaluate_assertions(response, assertions)
-> list[AssertionResult]` covering status / latency / body / json_path / header /
`cert_expiry_days`; and `POST /monitors/{id}/check` that probes once and persists a
`CheckResult` (transport failures become a recorded result, **never** an API
error). Unit-test assertions exhaustively (incl. cert expiry + HTTP-skips-cert);
integration-probe a local test server / `respx` across 200 / 5xx / slow / timeout /
malformed-JSON. **Probe URLs are untrusted; SSRF guard wiring is S10 but don't
weaken it.** Read **sentinel-probe-and-assertions** (and skim **sentinel-security**)
first.

---

## Slice checklist (mirror of `PLAN.md §5`)

- [x] **S0** Scaffold & green harness
- [x] **S1** Monitor entity + repository (+ Alembic init)
- [x] **S2** Monitor CRUD API (+ header redaction)
- [x] **S3** curl import
- [x] **S4** Postman import
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
