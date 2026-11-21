"""Output job and printer routes; mounted under /api/v1 (M8; printers from M8.5b, CP-33)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Request, Response

from regwatch.core.db import DbSession
from regwatch.core.errors import ProblemError
from regwatch.core.routing import Paging, Tags, spec
from regwatch.core.schemas import Page
from regwatch.identity.permissions import CurrentPrincipal
from regwatch.identity.services import client_ip
from regwatch.outputs import printers, services
from regwatch.outputs.schemas import (
    OutputJob,
    OutputKind,
    OutputRequest,
    Printer,
    PrinterChoice,
    PrinterWrite,
)

router = APIRouter()
OUTPUTS: Tags = ["outputs"]
ADMIN: Tags = ["admin"]
PDF, SETTINGS = "outputs.pdf", "settings.manage"


@router.get("/printers", tags=OUTPUTS,
            **spec(list[PrinterChoice], desc="Printers to choose from", perm="outputs.print",
                   stub=False))  # fmt: skip
async def list_printer_choices(db: DbSession) -> list[PrinterChoice]:
    return await printers.choices(db)


@router.get("/admin/printers", tags=ADMIN,
            **spec(list[Printer], desc="Printers", perm=SETTINGS, stub=False))  # fmt: skip
async def list_printers(db: DbSession) -> list[Printer]:
    return await printers.list_printers(db)


@router.post(
    "/admin/printers", tags=ADMIN,
    **spec(Printer, status=201, desc="Created", perm=SETTINGS, errors=(422,), stub=False),
)  # fmt: skip
async def create_printer(body: PrinterWrite, principal: CurrentPrincipal, request: Request,
                         db: DbSession) -> Printer:  # fmt: skip
    return await printers.create_printer(db, body, principal, client_ip(request))


@router.patch(
    "/admin/printers/{id}", tags=ADMIN,
    **spec(Printer, desc="Updated", perm=SETTINGS, errors=(422,), stub=False),
)  # fmt: skip
async def update_printer(id: UUID, body: PrinterWrite, principal: CurrentPrincipal,
                         request: Request, db: DbSession) -> Printer:  # fmt: skip
    return await printers.update_printer(db, id, body, principal, client_ip(request))


@router.delete(
    "/admin/printers/{id}", tags=ADMIN,
    **spec(status=204, desc="Deleted", perm=SETTINGS, stub=False),
)  # fmt: skip
async def delete_printer(id: UUID, principal: CurrentPrincipal, request: Request,
                         db: DbSession) -> Response:  # fmt: skip
    await printers.delete_printer(db, id, principal, client_ip(request))
    return Response(status_code=204)


@router.post(
    "/admin/printers/{id}/test-page", tags=ADMIN,
    **spec(OutputJob, status=202, desc="Test page queued", perm=SETTINGS, stub=False),
)  # fmt: skip
async def printer_test_page(id: UUID, principal: CurrentPrincipal, request: Request,
                            db: DbSession) -> OutputJob:  # fmt: skip
    from regwatch.outputs.tasks import enqueue

    job = await printers.test_page(db, id, principal, client_ip(request))
    await enqueue(services.TASKS["print"], job.id)
    return services.out(job, principal)


@router.get(
    "/outputs", tags=OUTPUTS,
    **spec(Page[OutputJob], desc="Output jobs (all requires outputs.read_all)", perm=PDF,
           stub=False),
)  # fmt: skip
async def list_outputs(
    paging: Paging, principal: CurrentPrincipal, db: DbSession,
    scope: Literal["mine", "all"] = "mine",
    kind: OutputKind | None = None,
    status: str | None = None,
    scheduled: bool | None = None,
) -> Page[OutputJob]:  # fmt: skip
    return await services.list_outputs(db, principal, paging.page, paging.page_size, scope,
                                       kind=kind.value if kind else None, status=status,
                                       scheduled=scheduled)  # fmt: skip


@router.post(
    "/outputs", tags=OUTPUTS,
    description="Permission checked per kind (outputs.email, outputs.print, outputs.csv, "
    "outputs.schedule when schedule is set).",
    **spec(OutputJob, status=202, desc="Queued", perm=PDF, errors=(422,),
           error_desc={422: "Destination rejected (recipient domain, printer, size)"},
           stub=False),
)  # fmt: skip
async def create_output(
    body: OutputRequest, principal: CurrentPrincipal, request: Request, db: DbSession
) -> OutputJob:
    return await services.create_output(db, body, principal, client_ip(request))


@router.get("/outputs/{id}", tags=OUTPUTS, **spec(OutputJob, desc="Job", perm=PDF, stub=False))
async def get_output(id: UUID, principal: CurrentPrincipal, db: DbSession) -> OutputJob:
    return services.out(await services.get_job(db, id, principal), principal)


@router.delete(
    "/outputs/{id}", tags=OUTPUTS,
    **spec(status=204, desc="Cancelled (schedule removed or queued job cancelled)", perm=PDF,
           stub=False),
)  # fmt: skip
async def cancel_output(
    id: UUID, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Response:
    await services.cancel(db, id, principal, client_ip(request))
    return Response(status_code=204)


def _with_file(route: dict[str, Any]) -> dict[str, Any]:
    """The artifact route's 200: the file itself, once the link is signed (CP-32)."""
    route.setdefault("responses", {})[200] = {"description": "The file", "content": {
        "application/pdf": {"schema": {"type": "string", "format": "binary"}},
        "text/csv": {"schema": {"type": "string"}}}}  # fmt: skip
    return route


@router.get(
    "/outputs/{id}/artifact", tags=OUTPUTS,
    **_with_file(spec(status=302, desc="Redirect to a signed URL valid for 10 minutes",
                      perm=PDF, errors=(404,), stub=False)),
)  # fmt: skip
async def get_output_artifact(
    id: UUID, principal: CurrentPrincipal, db: DbSession,
    exp: int | None = None, sig: str | None = None,
) -> Response:  # fmt: skip
    """Without ``exp`` and ``sig``: a redirect to this route, signed for 10 minutes. With them,
    valid and the caller still allowed: the file itself (CP-32)."""
    from regwatch.core import objectstore

    job = await services.get_job(db, id, principal)
    if job.artifact_ref is None:
        raise ProblemError(404, "not-found", "This output has no file.")
    if exp is None or sig is None:
        location = services.signed_link(job.id, "/api/v1")  # the API prefix (api/app.py)
        return Response(status_code=302, headers={"Location": location,
                                                  "Cache-Control": "no-store"})  # fmt: skip
    if not services.link_valid(job.id, exp, sig):
        raise ProblemError(403, "forbidden", "The link has expired or is not valid.")
    data = await objectstore.get(job.artifact_ref)
    if data is None:
        raise ProblemError(404, "not-found", "The file is no longer kept.")
    kind = "application/pdf" if job.artifact_ref.endswith(".pdf") else "text/csv"
    name = services.file_name(job, job.artifact_ref.rsplit(".", 1)[-1], principal)
    headers = {"Content-Disposition": f'attachment; filename="{name}"',
               "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
               "Content-Security-Policy": "default-src 'none'"}  # fmt: skip
    return Response(data, media_type=kind, headers=headers)


@router.post(
    "/outputs/{id}/retry", tags=OUTPUTS,
    **spec(OutputJob, status=202, desc="Requeued", perm=PDF, stub=False),
)  # fmt: skip
async def retry_output(
    id: UUID, principal: CurrentPrincipal, request: Request, db: DbSession
) -> OutputJob:
    return await services.retry(db, id, principal, client_ip(request))
