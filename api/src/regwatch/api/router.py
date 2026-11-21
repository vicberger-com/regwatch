"""System routes: ``/api/v1/health``, ``/ready`` (CP-34) and ``/version``; no session needed."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response

from regwatch.api import services
from regwatch.api.schemas import Health, Ready, Version
from regwatch.core.settings import Settings, get_settings

router = APIRouter(tags=["system"])

PUBLIC: dict[str, Any] = {"security": []}
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("/health", response_model=Health, openapi_extra=PUBLIC)
async def health(settings: SettingsDep) -> Health:
    db, queue = await asyncio.gather(
        services.probe_db(settings.database_url.get_secret_value()),
        services.probe_queue(settings.queue_url.get_secret_value()),
    )
    up = [db, queue].count("ok")
    status = "ok" if up == 2 else "degraded" if up == 1 else "down"
    return Health(
        status=status,
        version=services.app_version(),
        db=db,
        queue=queue,
        checked_at=datetime.now(UTC),
    )


@router.get(
    "/ready", response_model=Ready,
    responses={503: {"model": Ready, "description": "Not ready"}}, openapi_extra=PUBLIC,
)  # fmt: skip
async def ready(request: Request, response: Response, settings: SettingsDep) -> Ready:
    """CP-34 (M10.1): 200 when the database answers a query, the queue a PING and the object
    store is writable; 503 otherwise, for the orchestrator and the proxy's health check."""
    db, queue, store = await asyncio.gather(
        services.probe_db_query(request.app.state.db),
        services.probe_queue(settings.queue_url.get_secret_value()),
        services.probe_object_store(settings.object_store_path),
    )
    ok = db == queue == store == "ok"
    if not ok:
        response.status_code = 503
    return Ready(ready=ok, db=db, queue=queue, object_store=store, checked_at=datetime.now(UTC))


@router.get("/version", response_model=Version, openapi_extra=PUBLIC)
async def version() -> Version:
    return Version(version=services.app_version(), commit=services.BUILD_COMMIT)
