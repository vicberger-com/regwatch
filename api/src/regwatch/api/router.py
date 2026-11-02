"""System routes: ``GET /api/v1/health`` and ``GET /api/v1/version`` (no session required)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from regwatch.api import services
from regwatch.api.schemas import Health, Version
from regwatch.core.settings import Settings, get_settings

router = APIRouter(tags=["system"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("/health", response_model=Health)
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


@router.get("/version", response_model=Version)
async def version() -> Version:
    return Version(version=services.app_version(), commit=services.BUILD_COMMIT)
