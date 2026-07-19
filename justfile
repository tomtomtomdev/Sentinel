# Sentinel task runner. Recipes wrap the raw commands in CLAUDE.md.
# Run `just` with no args to list recipes.

set shell := ["bash", "-uc"]

backend := "backend"
frontend := "frontend"

# list recipes
default:
    @just --list

# install / lock backend deps
setup:
    cd {{backend}} && uv sync

# run the web API with reload
run:
    cd {{backend}} && uv run uvicorn sentinel.interface.main:app --reload

# run the scheduler worker (after S6)
worker:
    cd {{backend}} && uv run python -m sentinel.infrastructure.scheduler

# full test suite
test:
    cd {{backend}} && uv run pytest

# fast pure-domain loop
test-unit:
    cd {{backend}} && uv run pytest tests/unit -q

# ruff lint + format check
lint:
    cd {{backend}} && uv run ruff check . && uv run ruff format --check .

# mypy type check
types:
    cd {{backend}} && uv run mypy src

# apply migrations (after S1)
migrate:
    cd {{backend}} && uv run alembic upgrade head

# re-encrypt every stored secret onto SECRET_KEY's first key (run after rotating a
# key, before dropping the old one from the ring — see README)
reencrypt:
    cd {{backend}} && uv run python -m sentinel.infrastructure.reencrypt

# generate a fresh Fernet key for SECRET_KEY (rotation: prepend it — see README)
gen-key:
    @cd {{backend}} && uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# generate a random API credential for AUTH_TOKEN
gen-token:
    @cd {{backend}} && uv run python -c "import secrets; print(secrets.token_urlsafe(32))"

# frontend tests (after S11)
front-test:
    cd {{frontend}} && pnpm test

# frontend dev server (after S11)
front-dev:
    cd {{frontend}} && pnpm dev

# frontend type-check + production build (after S11)
front-build:
    cd {{frontend}} && pnpm build

# whole stack via docker compose (after S13)
up:
    docker compose up --build
