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

- **Phase:** **S5b in progress — S5b.1+S5b.2+S5b.3 complete.** S5b is split into
  four green-ending sub-slices (PLAN D19): **S5b.1** pure logic ✅ · **S5b.2**
  `AuthSource`/`TokenState` persistence ✅ · **S5b.3** CRUD + manual-refresh API ✅ ·
  **S5b.4** probe-pipeline injection + proactive/reactive refresh + single-flight.
  S5b.3 added the auth-source API surface: `AuthSourceService` (CRUD) +
  `AuthTokenService` (refresh orchestration), DTOs, and the routes
  `POST/GET/GET{id}/PATCH/DELETE /api/v1/auth-sources` + `POST
  /api/v1/auth-sources/{id}/refresh`. Responses **redact every credential** (request
  body + secret headers + oauth `client_secret`/`password`); `GET/{id}` and refresh
  include a metadata-only `token_state` summary (`status` via the pure
  `token_status`, `obtained_at`, `expires_at`, `last_refresh_error`) — **never the
  token value**. Refresh builds the mode's token request → probes → `extract_token`
  → saves the cached `TokenState`; a transport/extraction failure is recorded as
  `status=error` (HTTP 200), keeping any previously valid token. `MonitorService`
  now validates `auth_source_id` exists (→ 422). S5b.1/.2 before it: pure logic +
  persistence.
- **Last green commit:** S5b.2 (`feat(auth): AuthSource/TokenState persistence…`);
  S5b.3 staged.
- **Test suite:** `just test` (no DB) → **235 passed, 23 skipped**. With
  `TEST_DATABASE_URL=…/sentinel_test` → **258 passed**. New:
  `tests/integration/test_auth_source_api.py` (12 — CRUD + redaction + refresh
  metadata-only + monitor-link validation) and 5 `token_status` unit tests.
- **Schema/migrations:** head **`a7c3f1e9d2b4`** (unchanged since S5b.2).
- **Deps:** unchanged.
- **Config:** unchanged.
- **Deployed:** no.

## Next action

➡️ **S5b.4 — Probe-pipeline injection + proactive/reactive refresh + single-flight.**
Wire the auth source into `CheckService.run_check`: when `monitor.auth_source_id`
is set, load the `AuthSource` + cached `TokenState`, call `resolve_auth`
(proactive: refresh on `NeedsRefresh`), `apply_injection` into the probe request,
then probe. **Reactive:** if the response status ∈ `refresh_on_status` (default
401/403), invalidate + refresh **once** + retry the probe **once** (no loops; a
persistent 401 is one recorded failed `CheckResult`). Reuse `AuthTokenService`'s
refresh for both, and **extend it for refresh-token reuse** (prefer the
`refresh_token` grant when one is cached, fall back to a full login on failure).
Add a **per-source single-flight lock** (`asyncio.Lock` keyed by source id) so a
herd of due monitors triggers one login. The injected token must never land in a
stored `CheckResult` sample (it stores none today — keep it that way; redact the
injection target if samples are ever added). Integration-test via `FakeHttpProbe`:
inject→probe, 401→one refresh+one retry, persistent-401→one failed check (no loop),
refresh-token reuse + fallback. This is the decrypt-at-use case from D18.

---

## Slice checklist (mirror of `PLAN.md §5`)

- [x] **S0** Scaffold & green harness
- [x] **S1** Monitor entity + repository (+ Alembic init)
- [x] **S2** Monitor CRUD API (+ header redaction)
- [x] **S3** curl import
- [x] **S4** Postman import
- [x] **S5** Probe + assertions engine (S5.1 pure engine + S5.2 adapter/persist/endpoint)
- [x] **S5a** Secret-at-rest (`SecretBox` / Fernet)
- [ ] **S5b** Auth source / token provider _(split — PLAN D19)_
  - [x] **S5b.1** Pure auth logic + value objects/entities
  - [x] **S5b.2** `AuthSource`/`TokenState` persistence (repo + `TokenStore` + migration)
  - [x] **S5b.3** Auth-source CRUD + manual-refresh API
  - [ ] **S5b.4** Probe-pipeline injection + proactive/reactive refresh + single-flight
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
