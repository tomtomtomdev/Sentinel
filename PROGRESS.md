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

- **Phase:** not started — repository is being scaffolded.
- **Last green commit:** _none yet._
- **Test suite:** _not yet present._
- **Schema/migrations:** _none yet._
- **Deployed:** no.

## Next action

➡️ **Begin S0 — Scaffold & green harness** (`PLAN.md §5`). Create the `uv`
backend project, ruff/mypy/pytest config, `justfile`, `GET /api/v1/health` with
one passing test, and the CI workflow. Done when `just test` is green on a fresh
clone and the first Conventional Commit is made.

---

## Slice checklist (mirror of `PLAN.md §5`)

- [ ] **S0** Scaffold & green harness
- [ ] **S1** Monitor entity + repository (+ Alembic init)
- [ ] **S2** Monitor CRUD API (+ header redaction)
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

_(empty — first entry will be S0)_

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
