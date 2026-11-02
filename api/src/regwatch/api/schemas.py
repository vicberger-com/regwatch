"""Pydantic schemas for the system routes, matching openapi/regwatch.v1.yaml."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

DependencyState = Literal["ok", "unavailable"]


class Health(BaseModel):
    """``components.schemas.Health``."""

    status: Literal["ok", "degraded", "down"]
    version: str
    db: DependencyState
    queue: DependencyState
    checked_at: datetime


class Version(BaseModel):
    """Response of ``GET /version``."""

    version: str
    commit: str
