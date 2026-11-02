"""Output job and printer routes; mounted under /api/v1. Stubs answer 501 until M8."""

from __future__ import annotations

from typing import Literal, NoReturn
from uuid import UUID

from fastapi import APIRouter

from regwatch.core.routing import Paging, Tags, not_implemented, spec
from regwatch.core.schemas import Page
from regwatch.outputs.schemas import OutputJob, OutputKind, OutputRequest, Printer, PrinterWrite

router = APIRouter()
OUTPUTS: Tags = ["outputs"]
ADMIN: Tags = ["admin"]
PDF, SETTINGS = "outputs.pdf", "settings.manage"


@router.get("/admin/printers", tags=ADMIN, **spec(list[Printer], desc="Printers", perm=SETTINGS))
async def list_printers() -> NoReturn:
    not_implemented()


@router.post(
    "/admin/printers", tags=ADMIN, **spec(Printer, status=201, desc="Created", perm=SETTINGS)
)
async def create_printer(body: PrinterWrite) -> NoReturn:
    not_implemented()


@router.patch("/admin/printers/{id}", tags=ADMIN, **spec(Printer, desc="Updated", perm=SETTINGS))
async def update_printer(id: UUID, body: PrinterWrite) -> NoReturn:
    not_implemented()


@router.delete(
    "/admin/printers/{id}", tags=ADMIN, **spec(status=204, desc="Deleted", perm=SETTINGS)
)
async def delete_printer(id: UUID) -> NoReturn:
    not_implemented()


@router.post(
    "/admin/printers/{id}/test-page", tags=ADMIN,
    **spec(OutputJob, status=202, desc="Test page queued", perm=SETTINGS),
)  # fmt: skip
async def printer_test_page(id: UUID) -> NoReturn:
    not_implemented()


@router.get(
    "/outputs", tags=OUTPUTS,
    **spec(Page[OutputJob], desc="Output jobs (all requires outputs.read_all)", perm=PDF),
)  # fmt: skip
async def list_outputs(
    paging: Paging,
    scope: Literal["mine", "all"] = "mine",
    kind: OutputKind | None = None,
    status: str | None = None,
    scheduled: bool | None = None,
) -> NoReturn:
    not_implemented()


@router.post(
    "/outputs", tags=OUTPUTS,
    description="Permission checked per kind (outputs.email, outputs.print, outputs.csv, "
    "outputs.schedule when schedule is set).",
    **spec(OutputJob, status=202, desc="Queued", perm=PDF, errors=(422,),
           error_desc={422: "Destination rejected (recipient domain, printer, size)"}),
)  # fmt: skip
async def create_output(body: OutputRequest) -> NoReturn:
    not_implemented()


@router.get("/outputs/{id}", tags=OUTPUTS, **spec(OutputJob, desc="Job", perm=PDF))
async def get_output(id: UUID) -> NoReturn:
    not_implemented()


@router.delete(
    "/outputs/{id}", tags=OUTPUTS,
    **spec(status=204, desc="Cancelled (schedule removed or queued job cancelled)", perm=PDF),
)  # fmt: skip
async def cancel_output(id: UUID) -> NoReturn:
    not_implemented()


@router.get(
    "/outputs/{id}/artifact", tags=OUTPUTS,
    **spec(status=302, desc="Redirect to a signed URL valid for 10 minutes", perm=PDF,
           errors=(404,)),
)  # fmt: skip
async def get_output_artifact(id: UUID) -> NoReturn:
    not_implemented()


@router.post(
    "/outputs/{id}/retry", tags=OUTPUTS, **spec(OutputJob, status=202, desc="Requeued", perm=PDF)
)
async def retry_output(id: UUID) -> NoReturn:
    not_implemented()
