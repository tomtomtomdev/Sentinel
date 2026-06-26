# Sentinel

A lightweight, self-hostable **HTTP API monitoring** web app. Import a `curl`
command or Postman collection (or set one up by hand), probe endpoints on a
schedule, assert on status / latency / body / certs, and get alerted on
up↔down transitions.

- **What** it does → [`SPEC.md`](./SPEC.md)
- **How** it's built (architecture, stack, slice roadmap) → [`PLAN.md`](./PLAN.md)
- **Where** we are → [`PROGRESS.md`](./PROGRESS.md)
- **Build protocol** (read first if you're contributing) → [`CLAUDE.md`](./CLAUDE.md)

## Quick start (backend)

Requires [`uv`](https://docs.astral.sh/uv/) and [`just`](https://just.systems/).

```bash
just setup    # install deps + pin Python 3.12 (uv)
just test     # run the suite
just run      # serve the API at http://127.0.0.1:8000
```

Then check liveness:

```bash
curl http://127.0.0.1:8000/api/v1/health
# {"status":"ok"}
```

Run `just` (no args) to list all recipes.

> ⚠️ **Do not expose the API to the internet without the auth gate** (slice S9a).
> Self-hosting on localhost is fine before then; public binding is not.
