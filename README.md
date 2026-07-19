# Sentinel

A lightweight, self-hostable **HTTP API monitoring** web app. Import a `curl`
command or Postman collection (or set one up by hand), probe endpoints on a
schedule, assert on status / latency / body / certs, and get alerted on
up↔down transitions.

- **What** it does → [`SPEC.md`](./SPEC.md)
- **How** it's built (architecture, stack, slice roadmap) → [`PLAN.md`](./PLAN.md)
- **Where** we are → [`PROGRESS.md`](./PROGRESS.md)
- **Build protocol** (read first if you're contributing) → [`CLAUDE.md`](./CLAUDE.md)

## Local development (backend)

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

The frontend (Vite SPA) runs separately with a dev proxy to the API:

```bash
just front-dev   # http://localhost:5173, proxies /api → localhost:8000
```

Run `just` (no args) to list all recipes.

---

## Deploy

> ⚠️ **Never expose Sentinel to a network without the auth gate (S9a).**
> With `AUTH_TOKEN` **empty**, every `/api/v1` route is open to any caller.
> Set `AUTH_TOKEN` (and `SECRET_KEY`) before binding to anything but localhost.

### Self-host with Docker Compose (recommended)

One command brings up Postgres, runs migrations, and starts the API, the
scheduler worker, and the nginx-served SPA — all on a single origin (nginx
proxies `/api` to the API, so there's no CORS and no token in any URL).

```bash
cp .env.example .env
# Generate the two required secrets and paste them into .env:
just gen-token   # -> AUTH_TOKEN  (random URL-safe string)
just gen-key     # -> SECRET_KEY  (a Fernet key)

docker compose up --build      # or: just up
```

Open the dashboard at **http://localhost:8080** (set the same `AUTH_TOKEN` in
the UI when prompted). The API is also published directly on
`http://localhost:8000` for debugging.

Services (see [`docker-compose.yml`](./docker-compose.yml)):

| Service    | Role                                                             |
|------------|-----------------------------------------------------------------|
| `db`       | Postgres 16 (data persisted in the `pgdata` volume)             |
| `migrate`  | one-shot `alembic upgrade head`, then exits                     |
| `web`      | FastAPI API (`uvicorn`), waits for `migrate`                    |
| `worker`   | scheduler runner, waits for `migrate`                           |
| `frontend` | nginx serving the SPA + reverse-proxying `/api` → `web`         |

Configuration lives in `.env` (see [`.env.example`](./.env.example) for every
key). Rotating the `SECRET_KEY` encryption key is a config change — see
[Rotating the encryption key](#rotating-the-encryption-key-secret_key) below.

### Fly.io (managed)

Fly runs the API and the worker as two process groups sharing one managed
Postgres, with migrations in the release command (see
[`backend/fly.toml`](./backend/fly.toml)). Requires
[`flyctl`](https://fly.io/docs/flyctl/).

```bash
cd backend

# 1. Create the app, reusing the committed fly.toml (pick your own app name when
#    prompted). --no-deploy so we can set secrets before the first release.
fly launch --no-deploy

# 2. Provision managed Postgres and attach it (the exact command depends on your
#    flyctl version / whether you use Fly Managed Postgres — the goal is just a
#    reachable Postgres whose URL you set as DATABASE_URL below).
fly postgres create --name sentinel-db
fly postgres attach sentinel-db

# 3. Set the required secrets. IMPORTANT: attach sets a bare `postgres://…` URL,
#    but the app + alembic need the asyncpg driver — re-set DATABASE_URL with the
#    `postgresql+asyncpg://` scheme (same host/creds as the attached string).
fly secrets set \
  DATABASE_URL="postgresql+asyncpg://<user>:<pass>@<host>:5432/<db>" \
  AUTH_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  SECRET_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"

# 4. Deploy. The release_command runs `alembic upgrade head` before the new
#    web + worker machines take traffic.
fly deploy
```

The invariants (whatever the CLI surface): two process groups (`web`, `worker`)
from `fly.toml`, a `DATABASE_URL` secret in `postgresql+asyncpg://` form,
`AUTH_TOKEN` + `SECRET_KEY` secrets, and migrations via `release_command`.

The SPA is served same-origin by the compose `frontend` image for self-host.
Deploying the SPA to Fly is a separate app (or any static host) pointing at the
API's public URL; serving it cross-origin would need a CORS pass — parked for
S14. For now the recommended full-stack path is Docker Compose above.

> **Live-updates caveat (S8 cross-process gap).** The dashboard's live SSE
> updates are emitted by the **API** process. Checks run by the **worker**
> process don't currently reach the API's in-memory event bus, so with the
> web/worker split above, live updates cover manual / API-triggered checks; the
> dashboard still shows scheduled results on the next refetch (or navigation).
> A shared bus (Redis) that closes this gap is a parked drop-in.

### Rotating the encryption key (`SECRET_KEY`)

`SECRET_KEY` is a **comma-separated Fernet key ring** that encrypts every secret
at rest — auth-source credentials, cached tokens, secret-bearing monitor headers,
and alert-channel configs. Encryption uses `MultiFernet`: the **first** key in the
ring encrypts new writes, and **any** key in the ring can decrypt. So rotation is a
config change — no re-encryption, no downtime, no bricked ciphertext.

**To rotate (prepend a fresh key):**

1. **Generate a new key** — `just gen-key` (prints one Fernet key; never reuse an
   old one).
2. **Prepend it, keep the old key** so the ring is `<new>,<old>`:
   - Compose: edit `.env` → `SECRET_KEY=<new>,<old>`.
   - Fly: `fly secrets set SECRET_KEY="<new>,<old>"`.
3. **Redeploy / restart** so `web` **and** `worker` load the new ring
   (`docker compose up -d --build`, or `fly deploy`). From this point new writes
   are encrypted under `<new>`; all data already stored under `<old>` still
   decrypts. A leaked `<old>` key alone can no longer read anything written after
   the rotation.

**Dropping the old key** is a *separate, later* step — and the part to get right:

- Sentinel does **not** re-encrypt data at rest automatically. Ciphertext written
  under `<old>` stays under `<old>` until that specific record is next saved, so
  you **cannot** safely remove `<old>` just by waiting.
- **Recommended:** leave the old key in the ring as a harmless **decrypt-only**
  key. A ring may hold many keys; keeping one costs nothing and keeps every stored
  secret readable.
- **Only remove `<old>`** (e.g. because it was compromised) once nothing is
  encrypted under it. There's no built-in re-encryption walker yet (parked
  follow-up), so force it first: re-save every secret-bearing record (monitors with
  secret headers, auth sources, alert channels) and trigger an auth-source refresh
  so cached tokens are rewritten under `<new>`. Then set `SECRET_KEY=<new>` and
  redeploy.
- **Verify** after dropping a key: the app boots (a malformed ring **fails fast**
  at startup) and a monitor / auth-source / channel that carried a secret still
  works. If any secret was missed it fails to decrypt at use — restore `<old>` to
  the ring, redeploy, and re-save the stragglers.

Never commit real keys; `SECRET_KEY` comes only from the environment.
