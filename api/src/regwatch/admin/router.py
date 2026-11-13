"""Settings, feature flags, branding, legal page and audit routes; mounted under /api/v1.

``GET /admin/audit`` is implemented (#32); the other stubs answer 501 until #32 lands.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Query

from regwatch.admin import services
from regwatch.admin.schemas import (
    AuditEntry,
    Branding,
    BrandingWrite,
    FeatureFlag,
    FeatureFlagWrite,
    Legal,
    LegalWrite,
    Setting,
    SettingWrite,
)
from regwatch.core.db import DbSession
from regwatch.core.routing import Paging, Tags, not_implemented, raw_body, spec
from regwatch.core.schemas import Page

router = APIRouter()
ADMIN: Tags = ["admin"]
SYSTEM: Tags = ["system"]
SETTINGS = "settings.manage"
LOGO_BODY = raw_body(
    "multipart/form-data",
    {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}},
)


@router.get("/branding", tags=SYSTEM, **spec(Branding, desc="Branding for authenticated users"))
async def get_branding() -> NoReturn:
    not_implemented()


@router.get("/legal", tags=SYSTEM, **spec(Legal, desc="Rendered legal page"))
async def get_legal() -> NoReturn:
    not_implemented()


@router.get(
    "/admin/settings", tags=ADMIN,
    **spec(list[Setting], desc="All settings with definitions", perm=SETTINGS),
)  # fmt: skip
async def list_settings() -> NoReturn:
    not_implemented()


@router.put(
    "/admin/settings/{key}",
    tags=ADMIN,
    **spec(Setting, desc="Updated", perm=SETTINGS, errors=(400,)),
)
async def put_setting(key: str, body: SettingWrite) -> NoReturn:
    not_implemented()


@router.get(
    "/admin/feature-flags", tags=ADMIN, **spec(list[FeatureFlag], desc="Flags", perm=SETTINGS)
)
async def list_feature_flags() -> NoReturn:
    not_implemented()


@router.patch(
    "/admin/feature-flags/{key}", tags=ADMIN,
    **spec(FeatureFlag, desc="Updated", perm=SETTINGS, errors=(409,), error_desc={
        409: "Precondition unmet (for example hosted provider without data-processing basis)"}),
)  # fmt: skip
async def update_feature_flag(key: str, body: FeatureFlagWrite) -> NoReturn:
    not_implemented()


@router.put("/admin/branding", tags=ADMIN, **spec(Branding, desc="Updated", perm=SETTINGS))
async def put_branding(body: BrandingWrite) -> NoReturn:
    not_implemented()


@router.post(
    "/admin/branding/logo", tags=ADMIN,
    **spec(Branding, desc="Stored (PNG or sanitized SVG, 1 MB cap)", perm=SETTINGS,
           errors=(415,), body=LOGO_BODY),
)  # fmt: skip
async def upload_logo() -> NoReturn:
    not_implemented()


@router.put("/admin/legal", tags=ADMIN, **spec(status=204, desc="Saved", perm=SETTINGS))
async def put_legal(body: LegalWrite) -> NoReturn:
    not_implemented()


@router.get(
    "/admin/audit", tags=ADMIN,
    **spec(Page[AuditEntry], desc="Audit rows", perm="audit.read", stub=False),
)  # fmt: skip
async def list_audit(
    paging: Paging,
    db: DbSession,
    actor: UUID | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
) -> Page[AuditEntry]:
    return await services.list_audit(
        db, paging.page, paging.page_size, actor=actor, action=action,
        entity_type=entity_type, entity_id=entity_id, from_=from_, to=to,
    )  # fmt: skip
