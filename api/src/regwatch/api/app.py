"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import structlog
from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.routing import BaseRoute

from regwatch.admin.router import router as admin_router
from regwatch.api import services
from regwatch.api.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from regwatch.api.openapi import install_openapi
from regwatch.api.router import router as system_router
from regwatch.capture.router import router as capture_router
from regwatch.core import metrics
from regwatch.core.db import audit_log_is_append_only, create_engine, session_factory
from regwatch.core.errors import install_problem_handlers
from regwatch.core.logging_setup import configure_logging
from regwatch.core.settings import Settings, get_settings
from regwatch.identity.permissions import authorize
from regwatch.identity.router import router as identity_router
from regwatch.outputs.router import router as outputs_router
from regwatch.processing.router import router as processing_router
from regwatch.reports.router import router as reports_router
from regwatch.search.router import router as search_router
from regwatch.taxonomy.router import router as taxonomy_router

API_PREFIX = "/api/v1"

# Mount order matters only where literal and templated paths overlap within one router.
MODULE_ROUTERS: tuple[APIRouter, ...] = (
    system_router,
    identity_router,
    admin_router,
    taxonomy_router,
    capture_router,
    processing_router,
    search_router,
    reports_router,
    outputs_router,
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


async def check_database_login(engine: AsyncEngine, settings: Settings) -> None:
    """Refuse to serve in production unless the API's login provably cannot alter audit rows
    and no owner URL is configured (BL-61); fail closed if that cannot be checked. Outside
    production, warn."""
    log = structlog.get_logger("regwatch.startup")
    production = settings.env == "production"
    if settings.migration_database_url is not None:
        if production:
            raise RuntimeError(
                "REGWATCH_MIGRATION_DATABASE_URL is set for the API; give the owner URL only to "
                "the migrate container (BL-61)"
            )
        log.warning("owner_database_url_in_api_environment", hint="see BL-61")
    try:
        append_only = await audit_log_is_append_only(engine)
    except Exception as exc:
        if production:
            raise RuntimeError(
                "cannot verify the database login (unreachable or unmigrated database); "
                "run make migrate first (BL-61)"
            ) from exc
        log.warning("database_login_unchecked", error=type(exc).__name__)
        return
    if append_only:
        return
    if production:
        raise RuntimeError(
            "REGWATCH_DATABASE_URL can alter audit_log; use a member of regwatch_app, and the "
            "owner only in REGWATCH_MIGRATION_DATABASE_URL for the migrate container (BL-61)"
        )
    log.warning("database_login_can_alter_audit_log", hint="see BL-61 and deploy/README.md")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Reads settings first, so a missing required variable stops start-up."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    engine = create_engine(settings.database_url.get_secret_value())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await check_database_login(engine, settings)
        async with anyio.create_task_group() as group:
            if settings.metrics_port is not None:  # M10.1b: an internal listener only
                metrics.serve(settings.metrics_port, settings.metrics_bind)
                group.start_soon(metrics.refresh_forever, session_factory(engine),
                                 metrics.queue_depths)  # fmt: skip
            yield
            group.cancel_scope.cancel()
        await engine.dispose()

    # The API description and docs are served outside production only (no session needed).
    exposed = settings.env != "production"
    app = FastAPI(
        title="regwatch API",
        version=services.app_version(),
        openapi_url=f"{API_PREFIX}/openapi.json" if exposed else None,
        docs_url=f"{API_PREFIX}/docs" if settings.env == "development" else None,
        redoc_url=None,
        generate_unique_id_function=_operation_id,
        # Every module route passes the session, permission and origin gate (#31).
        dependencies=[Depends(authorize)],
        lifespan=lifespan,
    )
    app.state.db = session_factory(engine)
    app.dependency_overrides[get_settings] = lambda: settings
    # Last added runs first: request ids are bound before the body limit can answer 413.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(metrics.MetricsMiddleware)  # outermost: times the whole request
    for router in MODULE_ROUTERS:
        app.include_router(router, prefix=API_PREFIX)
    install_problem_handlers(app, api_routes())
    install_openapi(app, API_PREFIX)
    return app
