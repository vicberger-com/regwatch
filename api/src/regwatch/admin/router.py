"""Settings, feature flags, branding, legal page and audit routes; mounted under /api/v1.

Implemented in #32 except the logo upload and the rendered ``/legal`` page, which answer 501
until their sanitizer and Markdown renderer are registered (BL-68).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

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
from regwatch.identity.permissions import CurrentPrincipal
from regwatch.identity.services import client_ip

router = APIRouter()
ADMIN: Tags = ["admin"]
SYSTEM: Tags = ["system"]
SETTINGS = "settings.manage"
LOGO_BODY = raw_body(
    "multipart/form-data",
    {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}},
)


@router.get(
    "/branding", tags=SYSTEM,
    **spec(Branding, desc="Branding for authenticated users", stub=False),
)  # fmt: skip
async def get_branding(db: DbSession) -> Branding:
    return await services.branding(db)


@router.get("/legal", tags=SYSTEM, **spec(Legal, desc="Rendered legal page"))
async def get_legal() -> NoReturn:
    not_implemented()


@router.get(
    "/admin/settings", tags=ADMIN,
    **spec(list[Setting], desc="All settings with definitions", perm=SETTINGS, stub=False),
)  # fmt: skip
async def list_settings(db: DbSession) -> list[Setting]:
    return await services.list_settings(db)


@router.put(
    "/admin/settings/{key}",
    tags=ADMIN,
    **spec(Setting, desc="Updated", perm=SETTINGS, errors=(400,), stub=False),
)
async def put_setting(
    key: str, body: SettingWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Setting:
    return await services.put_setting(db, key, body.value, principal.user.id, client_ip(request))


@router.get(
    "/admin/feature-flags", tags=ADMIN,
    **spec(list[FeatureFlag], desc="Flags", perm=SETTINGS, stub=False),
)  # fmt: skip
async def list_feature_flags(db: DbSession) -> list[FeatureFlag]:
    return await services.list_flags(db)


@router.patch(
    "/admin/feature-flags/{key}", tags=ADMIN,
    **spec(FeatureFlag, desc="Updated", perm=SETTINGS, errors=(409,), error_desc={
        409: "Precondition unmet (for example hosted provider without data-processing basis)"},
        stub=False),
)  # fmt: skip
async def update_feature_flag(
    key: str,
    body: FeatureFlagWrite,
    principal: CurrentPrincipal,
    request: Request,
    db: DbSession,
) -> FeatureFlag:
    return await services.set_flag(db, key, body.enabled, principal.user.id, client_ip(request))


@router.put(
    "/admin/branding", tags=ADMIN, **spec(Branding, desc="Updated", perm=SETTINGS, stub=False)
)  # fmt: skip
async def put_branding(
    body: BrandingWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Branding:
    return await services.put_branding(db, body, principal.user.id, client_ip(request))


@router.post(
    "/admin/branding/logo", tags=ADMIN,
    **spec(Branding, desc="Stored (PNG or sanitized SVG, 1 MB cap)", perm=SETTINGS,
           errors=(415,), body=LOGO_BODY),
)  # fmt: skip
async def upload_logo() -> NoReturn:
    not_implemented()


@router.put(
    "/admin/legal", tags=ADMIN, **spec(status=204, desc="Saved", perm=SETTINGS, stub=False)
)  # fmt: skip
async def put_legal(
    body: LegalWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Response:
    await services.put_legal(db, body, principal.user.id, client_ip(request))
    return Response(status_code=204)


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
