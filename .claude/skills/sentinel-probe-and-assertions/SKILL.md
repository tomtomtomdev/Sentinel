---
name: sentinel-probe-and-assertions
description: >
  How to build and test Sentinel's HTTP probe and assertion engine. Use for slices
  S5/S6 and any work on issuing the monitored request with httpx (timeouts,
  redirects, error classification), evaluating assertions (status, latency,
  body, JSON path, header), recording CheckResults, or writing probe tests with
  respx or a local test server. Covers the test matrix: 200 / 5xx / slow /
  timeout / malformed JSON.
---

# Sentinel probe & assertions

The probe is the only place outbound HTTP happens. Keep the **request execution**
in an adapter and the **assertion evaluation** pure.

## HttpProbe (port + httpx adapter)

`HttpProbe.send(request: ProbeRequest, timeout, follow_redirects) -> ProbeResponse`.

- One shared `httpx.AsyncClient` (connection pooling); per-request `timeout`.
- Capture: `status_code`, `latency_ms` (monotonic clock around send),
  `headers`, a **bounded body sample** (cap bytes, e.g. 64 KB, enough for
  assertions — never store full large bodies), `response_size_bytes`, and for
  HTTPS the **TLS leaf certificate `notAfter`** → `ProbeResponse.cert_expires_at`
  (read from the connection's peer cert; `None` for plain HTTP).
- **Classify transport failures** into `ErrorKind`: `httpx.ConnectTimeout`/
  `ReadTimeout` → `timeout`; DNS/`ConnectError` → `dns`/`connection`; TLS →
  `tls`; anything else → `unknown`. A transport failure becomes a failed
  `CheckResult` with that `error` — it is **never raised** out of the probe loop.
- Respect the SSRF guard (sentinel-security) before sending.

`ProbeRequest` / `ProbeResponse` are plain value objects in `domain` so pure code
and tests don't depend on httpx.

## Assertion engine (pure — `domain/logic/assertions.py`)

`evaluate_assertions(response, assertions) -> list[AssertionResult]`. A check's
`success` is `all(r.passed for r in results)`. Implement each type from
`SPEC.md §3.4`:

- `status_code` (`equals` / `in` / `range`)
- `max_latency_ms`
- `body_contains` / `body_not_contains` (honour `case_sensitive`)
- `json_path_equals` / `json_path_exists` (parse the body sample; a malformed
  body fails the assertion with a clear reason, never throws out of the engine)
- `header_equals`
- `cert_expiry_days` (`min_days`): passes when `response.cert_expires_at` is ≥
  `min_days` away (uses `Clock`/`now` passed in); for plain HTTP there is no cert
  — treat as not-applicable (skip), not a failure.

No network, no clock — operates only on the `ProbeResponse`. Default when a
monitor lists no assertions: `status_code in 200–299`.

## Recording a check

The probe use case: build request (+ auth injection if linked — see
sentinel-auth-source) → `HttpProbe.send` → `evaluate_assertions` → assemble
`CheckResult` (success, error, assertion_results, latency, size, timestamps) →
persist via `CheckResultRepository`. **Redact** the request/response sample of
secret headers and any injected token before storing.

## Testing

**Unit (assertions):** table-driven over every type and both outcomes, plus the
malformed-JSON and missing-path cases. Pure, instant, no fixtures beyond a
`ProbeResponse` builder.

**Integration (probe):** two options —
- `respx` to mock httpx routes (fast, in-process), or
- a tiny local server fixture (FastAPI/Starlette app on an ephemeral port) with
  routes for `200`, `500`, a `slow` endpoint (sleep > timeout), and one returning
  invalid JSON.

Required matrix: **200 pass**, **200 with a failing assertion**, **500**, **slow
→ timeout** (assert `error=timeout`, `success=false`), **malformed JSON** (json
assertion fails cleanly). Assert the persisted `CheckResult` fields, not internal
calls.

Use a fake `Clock` only where the pipeline needs time; latency uses a monotonic
measurement, so in tests assert latency is recorded and non-negative rather than
an exact value.

## Scheduler runner (S6)

The runner is a thin loop over pure decisions; keep the decisions pure.

- **Due selection is pure:** `select_due_monitors(monitors, now, last_run_by_id)`
  and `next_run_at(monitor, last_run_at)` decide *what* and *when*. `next_run_at`
  adds **per-monitor jitter** (deterministic from the monitor id so tests are
  stable) so checks don't bunch on the minute boundary.
- **Skip, don't backfill:** if many intervals elapsed while the worker was down,
  schedule exactly one next run from `now` — never replay the missed ticks.
- **Bounded concurrency:** probe due monitors via an `asyncio` semaphore /
  task group so one hung endpoint can't starve the rest; never `await` a slow
  probe inline in the selection loop.
- **Dead-man's switch:** after each cycle, call the `Heartbeat` port (pings
  `HEARTBEAT_URL`); a no-op when unset. This is how a silent worker death gets
  noticed from outside — test that a cycle pings and that an unset URL is inert.
- **Multi-worker (future, documented not built):** claim due rows with
  `SELECT … FOR UPDATE SKIP LOCKED` so each monitor is taken by one worker.
- **Tests:** unit-test selection, jitter spread, and the gap-skip with a fake
  `Clock`; integration-test a single cycle with fakes asserting results are
  stored, `last_check_at` advanced, and the heartbeat fired.
