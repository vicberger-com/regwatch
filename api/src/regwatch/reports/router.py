"""Report template, field and layout routes; mounted under /api/v1 (M7). Templates and the
preview are stubs until M7.2 and M7.3."""

from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from regwatch.core.db import DbSession
from regwatch.core.errors import ProblemError
from regwatch.core.routing import spec
from regwatch.identity.permissions import CurrentPrincipal
from regwatch.identity.services import client_ip
from regwatch.reports import fields, render, services, templates
from regwatch.reports.schemas import (
    ReportField,
    ReportLayout,
    ReportLayoutWrite,
    ReportParams,
    ReportTemplate,
)

router = APIRouter(tags=["reports"])
BUILD = "reports.build"


@router.get(
    "/reports/templates",
    **spec(list[ReportTemplate], desc="Stock reports", perm="reports.print", stub=False),
)
async def list_templates(db: DbSession) -> list[ReportTemplate]:
    return await templates.list_templates(db)


@router.post(
    "/reports/templates/{key}/instantiate",
    **spec(ReportLayout, status=201, desc="New layout copied from the template", perm=BUILD,
           stub=False),
)  # fmt: skip
async def instantiate_template(
    key: str, principal: CurrentPrincipal, request: Request, db: DbSession
) -> ReportLayout:
    return await templates.instantiate(db, key, principal, client_ip(request))


@router.get(
    "/reports/fields",
    **spec(list[ReportField], desc="Whitelisted fields for the builder", perm=BUILD, stub=False),
)
async def list_fields(db: DbSession) -> list[ReportField]:
    return await fields.report_fields(db)


@router.get(
    "/reports/layouts",
    **spec(list[ReportLayout], desc="Own and shared layouts", perm=BUILD, stub=False),
)
async def list_layouts(principal: CurrentPrincipal, db: DbSession) -> list[ReportLayout]:
    return await services.list_layouts(db, principal)


@router.post(
    "/reports/layouts",
    **spec(ReportLayout, status=201, desc="Created", perm=BUILD, errors=(422,), stub=False),
)
async def create_layout(
    body: ReportLayoutWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> ReportLayout:
    return await services.create_layout(db, body, principal, client_ip(request))


@router.get("/reports/layouts/{id}", **spec(ReportLayout, desc="Layout", perm=BUILD, stub=False))
async def get_layout(id: UUID, principal: CurrentPrincipal, db: DbSession) -> ReportLayout:
    return services.out(await services.get_layout(db, id, principal))


@router.patch(
    "/reports/layouts/{id}",
    **spec(ReportLayout, desc="Updated; version incremented", perm=BUILD, stub=False),
)
async def update_layout(
    id: UUID, body: ReportLayoutWrite, principal: CurrentPrincipal, request: Request,
    db: DbSession,
) -> ReportLayout:  # fmt: skip
    return await services.update_layout(db, id, body, principal, client_ip(request))


@router.delete("/reports/layouts/{id}", **spec(status=204, desc="Deleted", perm=BUILD, stub=False))
async def delete_layout(
    id: UUID, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Response:
    await services.delete_layout(db, id, principal, client_ip(request))
    return Response(status_code=204)


@router.post(
    "/reports/layouts/{id}/preview",
    **spec(desc="Server-rendered HTML identical to the PDF input", perm=BUILD, content="text/html",
           stub=False),
)  # fmt: skip
async def preview_layout(
    id: UUID, principal: CurrentPrincipal, db: DbSession, body: ReportParams | None = None
) -> Response:
    given = body.model_dump() if body is not None else {}
    layout = await services.get_layout(db, id, principal)
    html = await render.render_layout(db, layout, principal, given)
    return _preview_response(html)


def _preview_response(html: str) -> Response:
    # The HTML holds hostile captured text: no scripts, no external loads, its own sandbox;
    # framed by this site only (the proxies set DENY only where a response sets nothing).
    return Response(html, media_type="text/html; charset=utf-8", headers={
        "Content-Security-Policy": render.CSP, "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN", "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer"})  # fmt: skip


@router.get(
    "/reports/layouts/{id}/preview",
    **spec(desc="The preview as a page of its own, for a frame (CP-35)", perm=BUILD,
           content="text/html", stub=False),
)  # fmt: skip
async def preview_layout_page(
    id: UUID, principal: CurrentPrincipal, db: DbSession,
    params: Annotated[str, Query(max_length=2000)] = "{}",
) -> Response:  # fmt: skip
    """CP-35 (M10.3; BL-140 g): the same preview, loaded by URL into a frame, so it keeps its
    own CSP; a srcdoc frame inherits the page's, which in production blocks its styles."""
    try:
        given = ReportParams.model_validate(json.loads(params)).model_dump()
    except (ValueError, TypeError):
        raise ProblemError(422, "validation", "params is a JSON object of report settings.") \
            from None  # fmt: skip
    layout = await services.get_layout(db, id, principal)
    return _preview_response(await render.render_layout(db, layout, principal, given))
