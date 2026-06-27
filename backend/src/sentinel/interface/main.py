from fastapi import FastAPI

from sentinel.interface.api import auth_sources, health, imports, monitors
from sentinel.interface.api.errors import register_exception_handlers

API_V1_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(title="Sentinel", version="0.1.0")
    register_exception_handlers(app)
    app.include_router(health.router, prefix=API_V1_PREFIX)
    app.include_router(monitors.router, prefix=API_V1_PREFIX)
    app.include_router(imports.router, prefix=API_V1_PREFIX)
    app.include_router(auth_sources.router, prefix=API_V1_PREFIX)
    return app


app = create_app()
