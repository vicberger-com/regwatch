"""Source, capture job and run routes; mounted under /api/v1. Stubs answer 501 until M3."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter

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
from regwatch.core.routing import Paging, not_implemented, spec
from regwatch.core.schemas import Page

router = APIRouter(tags=["capture"])
READ, MANAGE = "sources.read", "sources.manage"


@router.get("/sources", **spec(Page[Source], desc="Sources", perm=READ))
async def list_sources(
    paging: Paging,
    kind: SourceKind | None = None,
    health: str | None = None,
    q: str | None = None,
) -> NoReturn:
    not_implemented()


@router.post(
    "/sources",
    **spec(Source, status=201, desc="Created with its capture job", perm=MANAGE, errors=(422,),
           error_desc={422: "Config failed the connector schema or the URL is not allowed"}),
)  # fmt: skip
async def create_source(body: SourceWrite) -> NoReturn:
    not_implemented()


@router.get("/sources/{id}", **spec(Source, desc="Source", perm=READ))
async def get_source(id: UUID) -> NoReturn:
    not_implemented()


@router.patch("/sources/{id}", **spec(Source, desc="Updated", perm=MANAGE))
async def update_source(id: UUID, body: SourceWrite) -> NoReturn:
    not_implemented()


@router.delete(
    "/sources/{id}", **spec(status=204, desc="Disabled and archived; items are kept", perm=MANAGE)
)
async def delete_source(id: UUID) -> NoReturn:
    not_implemented()


@router.post(
    "/sources/{id}/test", **spec(SourceTestResult, desc="Dry run; first candidates", perm=MANAGE)
)
async def test_source(id: UUID) -> NoReturn:
    not_implemented()


@router.get("/sources/{id}/health", **spec(SourceHealth, desc="Health", perm=READ))
async def source_health(id: UUID) -> NoReturn:
    not_implemented()


@router.get("/capture-jobs", **spec(list[CaptureJob], desc="Jobs", perm=READ))
async def list_capture_jobs(source_id: UUID | None = None) -> NoReturn:
    not_implemented()


@router.patch("/capture-jobs/{id}", **spec(CaptureJob, desc="Updated", perm=MANAGE))
async def update_capture_job(id: UUID, body: CaptureJobWrite) -> NoReturn:
    not_implemented()


@router.post(
    "/capture-jobs/{id}/run-now", **spec(CaptureRun, status=202, desc="Run queued", perm=MANAGE)
)
async def run_capture_job(id: UUID) -> NoReturn:
    not_implemented()


@router.get("/capture-runs", **spec(Page[CaptureRun], desc="Runs", perm=READ))
async def list_capture_runs(
    paging: Paging, job_id: UUID | None = None, status: str | None = None
) -> NoReturn:
    not_implemented()
