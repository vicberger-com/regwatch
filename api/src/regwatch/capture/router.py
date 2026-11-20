"""Source, capture job and run routes; mounted under /api/v1.

Every route is implemented (M3); the dry run runs on a worker (CP-13).
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Request, Response
from starlette.datastructures import UploadFile

from regwatch.capture import catalogue, dryrun, manual, runs, services, tasks
from regwatch.capture.schemas import (
    CaptureJob,
    CaptureJobWrite,
    CaptureRun,
    CatalogueEntry,
    DocumentAccepted,
    Source,
    SourceHealth,
    SourceKind,
    SourceTestResult,
    SourceWrite,
)
from regwatch.core import objectstore
from regwatch.core.db import DbSession
from regwatch.core.errors import ProblemError
from regwatch.core.routing import Paging, spec
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
    "/sources/{id}/test",
    **spec(SourceTestResult, desc="Dry run; first candidates", perm=MANAGE, stub=False),
)
async def test_source(
    id: UUID, principal: CurrentPrincipal, request: Request, db: DbSession
) -> SourceTestResult:
    # Run on a worker (architecture 3.1: the API never fetches); CP-13.
    valkey = tasks._valkey()
    try:
        return await dryrun.request(db, id, principal, client_ip(request),
                                    tasks.publish_dry_run, valkey)  # fmt: skip
    finally:
        await valkey.aclose()


MAX_JSON_BYTES = 8 * 1024  # a URL and a title
# CP-17: a URL as JSON, or a file as multipart; the handler reads the body itself.
DOCUMENT_BODY = {"required": True, "content": {
    "application/json": {"schema": {
        "type": "object", "additionalProperties": False, "required": ["url"],
        "properties": {"url": {"type": "string", "format": "uri", "maxLength": 2048},
                       "title": {"type": "string", "maxLength": 500}}}},
    "multipart/form-data": {"schema": {
        "type": "object", "required": ["file"],
        "properties": {"file": {"type": "string", "format": "binary"},
                       "title": {"type": "string", "maxLength": 500}}}}}}  # fmt: skip


@router.post(
    "/sources/{id}/documents",
    **spec(DocumentAccepted, status=202, desc="Accepted; the run that adds the document",
           perm=MANAGE, errors=(409, 413, 415), body=DOCUMENT_BODY, stub=False,
           error_desc={409: "The source is not a manual source, or a run is already in progress",
                       413: "The file is larger than 10 MB",
                       415: "Not HTML, PDF or plain text"}),
)  # fmt: skip
async def add_source_document(id: UUID, principal: CurrentPrincipal, request: Request,
                              db: DbSession) -> DocumentAccepted:  # fmt: skip
    url, data, title = await _document_body(request)
    run_id = await manual.add_document(db, id, principal, client_ip(request), url=url,
                                       data=data, title=title, store=objectstore.put,
                                       enqueue=tasks.enqueue_run)  # fmt: skip
    return DocumentAccepted(run_id=run_id)


async def _document_body(request: Request) -> tuple[str | None, bytes | None, str | None]:
    """(url, file bytes, title) from a JSON or a multipart body; one file part at most."""
    kind = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if kind == "application/json":
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_JSON_BYTES:  # before reading it (R3)
            raise ProblemError(413, "payload-too-large", "A JSON body is at most 8 KB.")
        raw = await request.body()
        if len(raw) > MAX_JSON_BYTES:  # the 10 MB cap is for files (manual review finding 2)
            raise ProblemError(413, "payload-too-large", "A JSON body is at most 8 KB.")
        try:
            body = json.loads(raw)
        except (ValueError, RecursionError):  # deep nesting too (finding 2)
            raise ProblemError(422, "validation", "The body is not JSON.") from None
        if (not isinstance(body, dict) or set(body) - {"url", "title"}
                or not isinstance(body.get("url"), str) or len(body["url"]) > 2048
                or not isinstance(body.get("title", ""), str)):  # fmt: skip
            raise ProblemError(422, "validation", 'Send {"url": ..., "title": ...}.')
        return body["url"], None, body.get("title")
    if kind == "multipart/form-data":
        async with request.form(max_files=1, max_fields=1,
                                max_part_size=manual.MAX_FILE_BYTES + 1) as form:  # fmt: skip
            upload = form.get("file")
            title = form.get("title")
            if not isinstance(upload, UploadFile) or (title is not None
                                                      and not isinstance(title, str)):  # fmt: skip
                raise ProblemError(415, "unsupported-media-type", "Send the document as a file "
                                   "part named file.")  # fmt: skip
            data = await upload.read(manual.MAX_FILE_BYTES + 1)
        return None, data, title
    raise ProblemError(415, "unsupported-media-type", "Send JSON with a url, or a multipart file.")


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
    "/capture-jobs/{id}/run-now",
    **spec(CaptureRun, status=202, desc="Run queued", perm=MANAGE, stub=False),
)
async def run_capture_job(
    id: UUID, principal: CurrentPrincipal, request: Request, db: DbSession
) -> CaptureRun:
    # Looked up at call time, so tests can replace the broker hand-over.
    return await runs.queue_now(db, id, principal, client_ip(request), tasks.enqueue_run)


@router.get("/capture-runs", **spec(Page[CaptureRun], desc="Runs", perm=READ, stub=False))
async def list_capture_runs(
    paging: Paging, db: DbSession, job_id: UUID | None = None, status: str | None = None
) -> Page[CaptureRun]:
    return await services.list_runs(db, paging.page, paging.page_size, job_id, status)


# The feed catalogue (CP-25): every user who reads items may follow its sources.
@router.get(
    "/catalogue",
    **spec(list[CatalogueEntry], desc="The curated feed catalogue", perm="items.read",
           stub=False),
)  # fmt: skip
async def list_catalogue(principal: CurrentPrincipal, db: DbSession) -> list[CatalogueEntry]:
    return await catalogue.list_catalogue(db, principal.user.id)


@router.put(
    "/catalogue/{id}/follow",
    **spec(status=204, desc="Following", perm="items.read", stub=False),
)  # fmt: skip
async def follow_source(
    id: UUID, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Response:
    await catalogue.set_following(db, id, principal.user.id, True, client_ip(request))
    return Response(status_code=204)


@router.delete(
    "/catalogue/{id}/follow",
    **spec(status=204, desc="Not following", perm="items.read", stub=False),
)  # fmt: skip
async def unfollow_source(
    id: UUID, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Response:
    await catalogue.set_following(db, id, principal.user.id, False, client_ip(request))
    return Response(status_code=204)
