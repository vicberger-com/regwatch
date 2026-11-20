"""Celery tasks; names come from docs/contracts/registries.yaml (M8)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import anyio
import structlog
from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.db import create_engine, session_factory
from regwatch.core.errors import ProblemError
from regwatch.core.settings import get_settings

_log = structlog.get_logger("regwatch.outputs")
PUBLISH_DEADLINE_S = 15.0
_PUBLISHERS = anyio.CapacityLimiter(4)


def _send(name: str, job_id: uuid.UUID) -> None:
    from regwatch.core.worker import celery_app

    celery_app().send_task(name, args=[str(job_id)], queue="outputs")


async def enqueue(name: str, job_id: uuid.UUID) -> None:
    """Hand a job to the outputs queue off the event loop (as capture's ``enqueue_run``)."""
    with anyio.fail_after(PUBLISH_DEADLINE_S):
        await anyio.to_thread.run_sync(_send, name, job_id, limiter=_PUBLISHERS,
                                       abandon_on_cancel=True)  # fmt: skip


@shared_task(name="outputs.render_pdf", queue="outputs")  # type: ignore[untyped-decorator]
def render_pdf(output_job_id: str) -> None:
    anyio.run(_run, uuid.UUID(output_job_id))


async def _run(job_id: uuid.UUID) -> None:
    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass_null=True)
    try:
        async with session_factory(engine)() as db:
            await run_pdf(db, job_id)
    finally:
        await engine.dispose()


async def run_pdf(db: AsyncSession, job_id: uuid.UUID) -> str:
    """Render one queued PDF job; its final status. Re-checks the requester's current rights."""
    from sqlalchemy import select

    from regwatch.admin.services import values
    from regwatch.core import objectstore
    from regwatch.core.services import audit
    from regwatch.outputs import pdf, services
    from regwatch.outputs.models import OutputJob
    from regwatch.reports.render import render_layout

    job = await db.scalar(select(OutputJob).where(OutputJob.id == job_id).with_for_update(
        skip_locked=True))  # fmt: skip
    if job is None or job.status != "queued":
        return "skipped"
    job.status, job.attempts = "rendering", job.attempts + 1
    await db.commit()

    async def fail(error_class: str, message: str) -> str:
        job.status, job.error_class, job.error_message = "failed", error_class, message[:500]
        job.finished_at = datetime.now(UTC)
        audit(db, "output.failed", "output_job", job.id, actor=job.requested_by,
              after={"error_class": error_class})  # fmt: skip
        await db.commit()
        return "failed"

    principal = await services.current_principal(db, job.requested_by)
    if principal is None:
        return await fail("requester-inactive", "the requester's account is not active")
    try:
        layout = await services.check_source(db, job, principal)
        html = await render_layout(db, layout, principal,
                                   (job.destination or {}).get("report_params", {}))  # fmt: skip
    except ProblemError as exc:
        return await fail(exc.slug, exc.detail or exc.title)
    limit = int((await values(db, ["outputs.attachment_max_bytes"]))
                ["outputs.attachment_max_bytes"])  # fmt: skip
    try:
        data, pages = await pdf.render(html, layout.name, limit)
    except pdf.PdfError as exc:
        return await fail(exc.error_class, exc.message)
    # Read again under a lock: a cancel during the render wins (M8.1 review finding 2).
    await db.refresh(job, with_for_update=True)
    if job.status != "rendering":
        await db.commit()
        return job.status
    key = f"outputs/{job.id}.pdf"
    await objectstore.put(key, data)
    job.status, job.artifact_ref, job.artifact_bytes = "sent", key, len(data)
    job.layout_version, job.finished_at = layout.version, datetime.now(UTC)
    job.error_class = job.error_message = None
    audit(db, "output.sent", "output_job", job.id, actor=job.requested_by,
          after={"kind": "pdf", "bytes": len(data), "pages": pages,
                 "layout_version": layout.version})  # fmt: skip
    await db.commit()
    _log.info("output_sent", job=str(job.id), pages=pages, bytes=len(data))
    return "sent"


@shared_task(name="outputs.schedule_tick", queue="outputs")  # type: ignore[untyped-decorator]
def schedule_tick() -> None:
    """Every minute (beat): renders interrupted by a crashed worker are failed, so they can be
    retried; scheduled outputs join this tick in M8.3."""
    anyio.run(_tick)


async def _tick() -> None:
    from regwatch.outputs import services

    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass_null=True)
    try:
        async with session_factory(engine)() as db:
            if swept := await services.sweep_stale(db):
                _log.info("outputs_swept", jobs=swept)
    finally:
        await engine.dispose()
