"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from regwatch.api import services
from regwatch.api.middleware import RequestContextMiddleware
from regwatch.api.router import router as system_router
from regwatch.core.logging_setup import configure_logging
from regwatch.core.settings import Settings, get_settings

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Reads settings first, so a missing required variable stops start-up."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="regwatch API",
        version=services.app_version(),
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs" if settings.env == "development" else None,
        redoc_url=None,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.add_middleware(RequestContextMiddleware)
    app.include_router(system_router, prefix=API_PREFIX)
    return app
