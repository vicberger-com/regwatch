"""Source, capture job and run routes; mounted under /api/v1.

Sources, capture jobs, source health and run history are implemented (M3); the dry run and
run-now answer 501 until the scheduler slice.
"""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Request, Response

from regwatch.capture import services
from regwatch.capture.schemas import (
    CaptureJob,
    CaptureJobWrite,
    CaptureRun,
    Source,
    SourceHealth,
    SourceKind,
    SourceTestResult,
    SourceWrite,
)
from regwatch.core.db import DbSession
from regwatch.core.routing import Paging, not_implemented, spec
from regwatch.core.schemas import Page
from regwatch.identity.permissions import CurrentPrincipal
from regwatch.identity.services import client_ip

router = APIRouter(tags=["capture"])
READ, MANAGE = "sources.read", "sources.manage"


@router.get("/sources", **spec(Page[Source], desc="Sources", perm=READ, stub=False))
async def list_sources(
    paging: Paging,
    db: DbSession,
    kind: SourceKind | None = None,
    health: str | None = None,
    q: str | None = None,
) -> Page[Source]:
    return await services.list_sources(db, paging.page, paging.page_size, kind, health, q)


@router.post(
    "/sources",
    **spec(Source, status=201, desc="Created with its capture job", perm=MANAGE, errors=(422,),
           error_desc={422: "Config failed the connector schema or the URL is not allowed"},
           stub=False),
)  # fmt: skip
async def create_source(
    body: SourceWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Source:
    return await services.create_source(db, body, principal, client_ip(request))


@router.get("/sources/{id}", **spec(Source, desc="Source", perm=READ, stub=False))
async def get_source(id: UUID, db: DbSession) -> Source:
    return await services.get_source(db, id)


@router.patch("/sources/{id}", **spec(Source, desc="Updated", perm=MANAGE, stub=False))
async def update_source(
    id: UUID, body: SourceWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Source:
    return await services.update_source(db, id, body, principal, client_ip(request))


@router.delete(
    "/sources/{id}",
    **spec(status=204, desc="Disabled and archived; items are kept", perm=MANAGE, stub=False),
)
async def delete_source(
    id: UUID, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Response:
    await services.disable_source(db, id, principal.user.id, client_ip(request))
    return Response(status_code=204)


@router.post(
    "/sources/{id}/test", **spec(SourceTestResult, desc="Dry run; first candidates", perm=MANAGE)
)
async def test_source(id: UUID) -> NoReturn:
    not_implemented()


@router.get("/sources/{id}/health", **spec(SourceHealth, desc="Health", perm=READ, stub=False))
async def source_health(id: UUID, db: DbSession) -> SourceHealth:
    return await services.source_health(db, id)


@router.get("/capture-jobs", **spec(list[CaptureJob], desc="Jobs", perm=READ, stub=False))
async def list_capture_jobs(db: DbSession, source_id: UUID | None = None) -> list[CaptureJob]:
    return await services.list_jobs(db, source_id)


@router.patch("/capture-jobs/{id}", **spec(CaptureJob, desc="Updated", perm=MANAGE, stub=False))
async def update_capture_job(
    id: UUID, body: CaptureJobWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> CaptureJob:
    return await services.update_job(db, id, body, principal, client_ip(request))


@router.post(
    "/capture-jobs/{id}/run-now", **spec(CaptureRun, status=202, desc="Run queued", perm=MANAGE)
)
async def run_capture_job(id: UUID) -> NoReturn:
    not_implemented()


@router.get("/capture-runs", **spec(Page[CaptureRun], desc="Runs", perm=READ, stub=False))
async def list_capture_runs(
    paging: Paging, db: DbSession, job_id: UUID | None = None, status: str | None = None
) -> Page[CaptureRun]:
    return await services.list_runs(db, paging.page, paging.page_size, job_id, status)
