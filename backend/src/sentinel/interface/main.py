from fastapi import Depends, FastAPI

from sentinel.interface.api import auth_sources, channels, events, health, imports, monitors
from sentinel.interface.api.auth import require_auth
from sentinel.interface.api.errors import register_exception_handlers

API_V1_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(title="Sentinel", version="0.1.0")
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
