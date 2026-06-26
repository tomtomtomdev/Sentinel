---
name: sentinel-architecture
description: >
  Clean Architecture conventions for the Sentinel API-monitoring backend (FastAPI +
  SQLModel + Postgres). Use whenever adding or changing an entity, a port
  (Protocol), a repository, a use case/service, an API route or DTO, or an
  Alembic migration — or whenever unsure which layer code belongs in. Encodes the
  dependency rule and the step-by-step recipe for adding a capability end to end.
---

# Sentinel architecture

Authoritative layering for `backend/src/sentinel/`. Keep dependencies pointing
inward. If a change would violate the dependency rule, the design is wrong — fix
the design, not the rule.

## Layers & the dependency rule

```
interface/        FastAPI routers, Pydantic DTO schemas, SSE, dependency wiring
application/       use cases (services) — orchestration only, no business rules
domain/            entities, value objects, PURE logic, ports (Protocols)
infrastructure/    adapters: SQLModel repos, httpx probe, notifiers, secrets, scheduler
```

- `domain/` imports **nothing** from `application`, `infrastructure`, `interface`,
  FastAPI, SQLModel, or httpx. Pure Python + typing only.
- `application/` imports only `domain/`.
- `infrastructure/` and `interface/` import inward; **never each other**.
- Outer layers depend on `domain` **ports** (Protocols), not on concrete classes.

## What goes where

- **Business rule / decision** (does this token need refresh? is this monitor
  due? did state flip?) → a **pure function** in `domain/logic/`. No I/O, no
  `datetime.now()` — take a `Clock` and inputs, return a value.
- **Orchestration** (load X, call probe, save result, emit event) → a **use
  case** in `application/`. It wires ports; it contains flow, not rules.
- **I/O / framework** (DB, HTTP, crypto, scheduling) → an **adapter** in
  `infrastructure/` implementing a `domain` port.
- **Transport** (request/response shapes, validation, status codes, redaction) →
  `interface/api/`. DTOs here never expose ORM models or secrets.

## Ports

Defined as `typing.Protocol` in `domain/ports.py`. Each has an in-memory **fake**
for tests and a real adapter in `infrastructure/`. Inject ports into use cases
via constructor args; wire concretes in `interface/api/deps.py`.

Existing ports: `MonitorRepository`, `CheckResultRepository`,
`MonitorStateRepository`, `AlertChannelRepository`, `NotificationLogRepository`,
`AuthSourceRepository`, `TokenStore`, `HttpProbe`, `Notifier`, `Clock`,
`SecretBox`.

## Recipe — add a capability end to end (TDD order)

1. **Domain entity / value object** in `domain/entities.py` or
   `domain/value_objects.py`. Add invariants; unit-test them first.
2. **Pure logic** (if the feature has a decision) in `domain/logic/<name>.py`.
   Write the failing unit tests first, covering edge cases; then implement. No I/O.
3. **Port** in `domain/ports.py` if the feature needs new I/O. Define the
   Protocol by behaviour, not by DB shape.
4. **Fake adapter** (in-memory) under `tests/` (or `domain`-adjacent test
   support). Use it to test use cases without a DB.
5. **Real adapter** in `infrastructure/`: SQLModel model + repository, or httpx
   client, etc. Then an **Alembic migration** (`uv run alembic revision
   --autogenerate -m "..."`; review the generated SQL).
6. **Use case** in `application/`: constructor takes ports; method runs the flow.
   Test with fakes — assert observable outcomes, not call counts.
7. **DTOs + router** in `interface/api/`: Pydantic request/response schemas,
   route, validation, error→envelope mapping, **redaction of secrets in
   responses**. Test via `httpx.ASGITransport`.
8. **Wire** the concrete adapters in `deps.py`. Run the full gate
   (`just test lint types`) and update `PROGRESS.md`.

## Conventions

- Async everywhere for I/O; never block the loop.
- Domain errors are typed (`domain/errors.py`); the API layer maps them to the
  `SPEC.md §5` error envelope (`422` validation, `404` not found). Probe transport
  failures are recorded as `CheckResult`s — never raised as API errors.
- Keep functions small and single-purpose; prefer early returns.
- Time is a dependency: pass `Clock`, never call `datetime.now()` in `domain`.
