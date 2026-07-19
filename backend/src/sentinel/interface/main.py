from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from sentinel.infrastructure.logging_config import configure_logging
from sentinel.interface.api import auth_sources, channels, events, health, imports, monitors
from sentinel.interface.api.auth import require_auth
from sentinel.interface.api.errors import register_exception_handlers
from sentinel.interface.api.middleware import RequestContextMiddleware

API_V1_PREFIX = "/api/v1"


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Configure structured JSON logging at server startup (not import time), so
    # test clients that don't run the lifespan keep their own log capture.
    configure_logging()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Sentinel", version="0.1.0", lifespan=_lifespan)
    # Request-context / structured access logging wraps every request (S14.2).
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    # The auth gate (S9a) guards every router except the /health liveness probe.
    # A new router must opt IN to being open, not out of being gated.
    gate = [Depends(require_auth)]
    app.include_router(health.router, prefix=API_V1_PREFIX)
    app.include_router(monitors.router, prefix=API_V1_PREFIX, dependencies=gate)
    app.include_router(imports.router, prefix=API_V1_PREFIX, dependencies=gate)
    app.include_router(auth_sources.router, prefix=API_V1_PREFIX, dependencies=gate)
    app.include_router(channels.router, prefix=API_V1_PREFIX, dependencies=gate)
    app.include_router(events.router, prefix=API_V1_PREFIX, dependencies=gate)
    return app


app = create_app()
