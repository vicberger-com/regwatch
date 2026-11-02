"""Report template, field and layout routes; mounted under /api/v1. Stubs until M7."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter

from regwatch.core.routing import not_implemented, spec
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
    "/reports/templates", **spec(list[ReportTemplate], desc="Stock reports", perm="reports.print")
)
async def list_templates() -> NoReturn:
    not_implemented()


@router.post(
    "/reports/templates/{key}/instantiate",
    **spec(ReportLayout, status=201, desc="New layout copied from the template", perm=BUILD),
)
async def instantiate_template(key: str) -> NoReturn:
    not_implemented()


@router.get(
    "/reports/fields",
    **spec(list[ReportField], desc="Whitelisted fields for the builder", perm=BUILD),
)
async def list_fields() -> NoReturn:
    not_implemented()


@router.get(
    "/reports/layouts", **spec(list[ReportLayout], desc="Own and shared layouts", perm=BUILD)
)
async def list_layouts() -> NoReturn:
    not_implemented()


@router.post(
    "/reports/layouts", **spec(ReportLayout, status=201, desc="Created", perm=BUILD, errors=(422,))
)
async def create_layout(body: ReportLayoutWrite) -> NoReturn:
    not_implemented()


@router.get("/reports/layouts/{id}", **spec(ReportLayout, desc="Layout", perm=BUILD))
async def get_layout(id: UUID) -> NoReturn:
    not_implemented()


@router.patch(
    "/reports/layouts/{id}", **spec(ReportLayout, desc="Updated; version incremented", perm=BUILD)
)
async def update_layout(id: UUID, body: ReportLayoutWrite) -> NoReturn:
    not_implemented()


@router.delete("/reports/layouts/{id}", **spec(status=204, desc="Deleted", perm=BUILD))
async def delete_layout(id: UUID) -> NoReturn:
    not_implemented()


@router.post(
    "/reports/layouts/{id}/preview",
    **spec(desc="Server-rendered HTML identical to the PDF input", perm=BUILD, content="text/html"),
)
async def preview_layout(id: UUID, body: ReportParams | None = None) -> NoReturn:
    not_implemented()
