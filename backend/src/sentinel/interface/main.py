from fastapi import FastAPI

from sentinel.interface.api import health

API_V1_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(title="Sentinel", version="0.1.0")
    app.include_router(health.router, prefix=API_V1_PREFIX)
    return app


app = create_app()
