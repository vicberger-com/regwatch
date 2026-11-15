"""Settings, feature flags, branding, legal page and audit routes; mounted under /api/v1.

Implemented in #32; the rendered ``/legal`` page, the logo upload and the public logo route
(CP-07) in BL-68.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from starlette.datastructures import UploadFile

from regwatch.admin import logo, services
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
from regwatch.core.errors import ProblemError
from regwatch.core.routing import Paging, Tags, raw_body, spec
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


_LOGO_HEADERS = {
    # Even opened directly instead of through <img>, the file cannot run or load anything.
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    "X-Content-Type-Options": "nosniff",
    "Content-Disposition": 'inline; filename="logo"',
    "Cache-Control": "public, max-age=300",
}
_LOGO_SPEC = spec(desc="The current logo", public=True, errors=(404,), stub=False)
_LOGO_SPEC["responses"][200] = {
    "description": "The current logo",
    "content": {
        t: {"schema": {"type": "string", "format": "binary"}} for t in (logo.PNG, logo.SVG)
    },
}


@router.get("/branding/logo", tags=SYSTEM, **_LOGO_SPEC)
async def get_logo(request: Request, db: DbSession) -> Response:
    found = await services.logo_file(db)
    if found is None:
        raise services.not_found("logo")
    data, media_type, sha = found
    etag = f'"{sha}"'
    headers = {**_LOGO_HEADERS, "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(data, media_type=media_type, headers=headers)


@router.get("/legal", tags=SYSTEM, **spec(Legal, desc="Rendered legal page", stub=False))
async def get_legal(db: DbSession) -> Legal:
    return await services.legal(db)


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
           errors=(415,), body=LOGO_BODY, stub=False),
)  # fmt: skip
async def upload_logo(request: Request, principal: CurrentPrincipal, db: DbSession) -> Branding:
    # One file part and nothing else; the whole body is capped at 2 MB before this runs.
    async with request.form(max_files=1, max_fields=1) as form:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise ProblemError(
                415, "unsupported-media-type", "Send the logo as a file part named file."
            )
        data = await upload.read(logo.MAX_BYTES + 1)
    return await services.upload_logo(db, data, principal.user.id, client_ip(request))


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
