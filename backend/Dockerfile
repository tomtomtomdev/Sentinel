# syntax=docker/dockerfile:1
# Multi-stage build for the Sentinel backend. One image runs both processes:
# the FastAPI web API (`uvicorn ...`) and the scheduler worker
# (`python -m sentinel.infrastructure.scheduler`). The process is selected by
# the container command in docker-compose.yml / fly.toml, not baked in here.

# ---- builder: resolve deps + install the project into a venv ----------------
FROM python:3.12-slim-bookworm AS builder

# uv drives dependency install. Copied from its official image; bump the tag
# deliberately. UV_PYTHON_DOWNLOADS=0 forces uv to use this base image's system
# Python 3.12, so the venv interpreter is identical to the runtime stage's.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Dependency layer first: this cache layer is reused until the lock changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Then the project source, and install the project itself into the venv.
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

# ---- runtime: slim image with just the venv + app, run as non-root ----------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Unprivileged user — never run the web/worker as root.
RUN useradd --create-home --uid 10001 sentinel

WORKDIR /app
COPY --from=builder --chown=sentinel:sentinel /app /app

USER sentinel
EXPOSE 8000

# Default command is the web API; the worker overrides it (compose / fly.toml).
CMD ["uvicorn", "sentinel.interface.main:app", "--host", "0.0.0.0", "--port", "8000"]
