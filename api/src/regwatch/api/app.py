"""FastAPI application factory."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from regwatch.admin.router import router as admin_router
from regwatch.api import services
from regwatch.api.middleware import RequestContextMiddleware
from regwatch.api.openapi import install_openapi
from regwatch.api.router import router as system_router
from regwatch.core.errors import install_problem_handlers
from regwatch.core.logging_setup import configure_logging
from regwatch.core.settings import Settings, get_settings
from regwatch.identity.router import router as identity_router

API_PREFIX = "/api/v1"

# Taxonomy, capture, items, search, reports and outputs are mounted by part 2 of #30.
MODULE_ROUTERS: tuple[APIRouter, ...] = (
    system_router,
    identity_router,
    admin_router,
)


def api_routes() -> list[tuple[str, BaseRoute]]:
    """Every module route with its full path under ``API_PREFIX``."""
    return [
        (API_PREFIX + r.path, r)
        for router in MODULE_ROUTERS
        for r in router.routes
        if isinstance(r, APIRoute)
    ]


def _operation_id(route: APIRoute) -> str:
    return route.name


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
        generate_unique_id_function=_operation_id,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.add_middleware(RequestContextMiddleware)
    for router in MODULE_ROUTERS:
        app.include_router(router, prefix=API_PREFIX)
    install_problem_handlers(app, api_routes())
    install_openapi(app, API_PREFIX)
    return app
