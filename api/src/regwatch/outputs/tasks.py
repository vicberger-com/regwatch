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


def _send(name: str, job_id: uuid.UUID, countdown: float) -> None:
    from regwatch.core.worker import celery_app

    celery_app().send_task(name, args=[str(job_id)], queue="outputs", countdown=countdown)


async def enqueue(name: str, job_id: uuid.UUID, countdown: float = 0) -> None:
    """Hand a job to the outputs queue off the event loop (as capture's ``enqueue_run``)."""
    with anyio.fail_after(PUBLISH_DEADLINE_S):
        await anyio.to_thread.run_sync(_send, name, job_id, countdown, limiter=_PUBLISHERS,
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
    """Render one queued PDF job; its final status."""
    return await run_job(db, job_id, "pdf")


async def run_email(db: AsyncSession, job_id: uuid.UUID) -> str:
    """Render one queued email job and send it; its final status (or "retrying")."""
    return await run_job(db, job_id, "email")


RETRY_AFTER_S = (30, 120)  # before the second and third attempts (acceptance 5: backoff)


async def run_job(db: AsyncSession, job_id: uuid.UUID, kind: str) -> str:
    """The shared run: claim the job, re-check the requester's current rights, render the PDF,
    then store it (pdf) or send it (email). A cancel or sweep during the work wins."""
    from sqlalchemy import select

    from regwatch.admin.services import values
    from regwatch.core import objectstore
    from regwatch.core.services import audit
    from regwatch.outputs import csv_out, mail, pdf, schedules, services
    from regwatch.outputs.models import OutputJob
    from regwatch.reports.render import render_layout

    job = await db.scalar(select(OutputJob).where(OutputJob.id == job_id, OutputJob.kind == kind)
                          .with_for_update(skip_locked=True))  # fmt: skip
    if job is None or job.status != "queued" or job.scheduled_cron is not None:
        return "skipped"  # a schedule itself never renders: its runs do (M8.3)
    job.status, job.attempts = "rendering", job.attempts + 1
    await db.commit()

    async def fail(error_class: str, message: str) -> str:
        job.status, job.error_class, job.error_message = "failed", error_class, message[:500]
        job.finished_at = datetime.now(UTC)
        audit(db, "output.failed", "output_job", job.id, actor=job.requested_by,
              after={"error_class": error_class})  # fmt: skip
        await schedules.pause_parent(db, job, error_class, message)
        await db.commit()
        return "failed"

    principal = await services.current_principal(db, job.requested_by)
    if principal is None:
        return await fail("requester-inactive", "the requester's account is not active")
    destination = job.destination or {}
    settings = await values(db, ["outputs.attachment_max_bytes",
                                 "outputs.allowed_recipient_domains"])  # fmt: skip
    try:
        layout = await services.check_source(db, job, principal)
        if kind == "email":  # the rights and the allowed domains as they are now
            if "outputs.email" not in principal.permissions:
                return await fail("forbidden", "sending by email needs outputs.email")
            recipients = mail.check_recipients(
                destination.get("emails", []),
                list(settings["outputs.allowed_recipient_domains"] or []))  # fmt: skip
        if kind == "csv":
            data, cut = await csv_out.build(
                db, layout, int(settings["outputs.attachment_max_bytes"])
            )
        else:
            html = await render_layout(db, layout, principal,
                                       destination.get("report_params", {}))  # fmt: skip
    except ProblemError as exc:
        return await fail(exc.slug, exc.detail or exc.title)
    except ValueError as exc:
        return await fail("recipient-refused", str(exc))
    pages: int | None = None
    if kind != "csv":
        try:
            data, pages = await pdf.render(
                html, layout.name, int(settings["outputs.attachment_max_bytes"])
            )
        except pdf.PdfError as exc:
            return await fail(exc.error_class, exc.message)
    if kind == "email":
        name = f"regwatch-{job.id}.pdf"
        done = set(destination.get("sent", []))  # those a failed attempt already reached
        try:
            for to in [r for r in recipients if mail.hashed(r) not in done]:
                now = await db.scalar(select(OutputJob.status).where(OutputJob.id == job.id))
                if now != "rendering":  # cancelled or swept meanwhile: stop sending
                    await db.commit()
                    return str(now)
                await mail.send(
                    [
                        (
                            mail.build(
                                to,
                                destination.get("subject", "regwatch report"),
                                destination.get("message", ""),
                                data,
                                name,
                            ),
                            to,
                        )
                    ]
                )
                done.add(mail.hashed(to))  # one at a time: a retry never sends twice (review)
                job.destination = {**destination, "sent": sorted(done)}
                await db.commit()
        except mail.MailError as exc:
            if job.attempts >= services.MAX_ATTEMPTS:
                return await fail(exc.error_class, exc.message)
            job.status, job.error_class, job.error_message = "queued", exc.error_class, exc.message
            await db.commit()
            wait = RETRY_AFTER_S[min(job.attempts, len(RETRY_AFTER_S)) - 1]
            await enqueue("outputs.send_email", job.id, countdown=wait)
            return "retrying"
    # Read again under a lock: a cancel during the work wins (M8.1 review finding 2).
    await db.refresh(job, with_for_update=True)
    if job.status != "rendering":
        await db.commit()
        return job.status
    key = f"outputs/{job.id}.{'csv' if kind == 'csv' else 'pdf'}"
    await objectstore.put(key, data)
    job.status, job.artifact_ref, job.artifact_bytes = "sent", key, len(data)
    job.layout_version, job.finished_at = layout.version, datetime.now(UTC)
    job.error_class = job.error_message = None
    after: dict[str, object] = {"kind": kind, "bytes": len(data), "pages": pages,
                                "layout_version": layout.version}  # fmt: skip
    if kind == "csv":
        after["columns"], after["truncated"] = list(layout.columns), cut
    if kind == "email":
        after["recipients"] = [mail.hashed(r) for r in recipients]  # never the addresses
        after["recipient_domains"] = sorted({mail.domain_of(r) for r in recipients})  # review
    audit(db, "output.sent", "output_job", job.id, actor=job.requested_by, after=after)
    await db.commit()
    _log.info("output_sent", job=str(job.id), kind=kind, pages=pages, bytes=len(data))
    return "sent"


@shared_task(name="outputs.send_email", queue="outputs")  # type: ignore[untyped-decorator]
def send_email(output_job_id: str) -> None:
    anyio.run(_run_email, uuid.UUID(output_job_id))


async def _run_email(job_id: uuid.UUID) -> None:
    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass_null=True)
    try:
        async with session_factory(engine)() as db:
            await run_email(db, job_id)
    finally:
        await engine.dispose()


@shared_task(name="outputs.export_csv", queue="outputs")  # type: ignore[untyped-decorator]
def export_csv(output_job_id: str) -> None:
    anyio.run(_run_csv, uuid.UUID(output_job_id))


async def _run_csv(job_id: uuid.UUID) -> None:
    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass_null=True)
    try:
        async with session_factory(engine)() as db:
            await run_csv(db, job_id)
    finally:
        await engine.dispose()


async def run_csv(db: AsyncSession, job_id: uuid.UUID) -> str:
    """Export one queued CSV job to the object store; its final status (M8.4)."""
    return await run_job(db, job_id, "csv")


@shared_task(name="outputs.schedule_tick", queue="outputs")  # type: ignore[untyped-decorator]
def schedule_tick() -> None:
    """Every minute (beat): renders interrupted by a crashed worker are failed, so they can be
    retried, and due schedules start their runs (M8.3)."""
    anyio.run(_tick)


async def _tick() -> None:
    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass_null=True)
    try:
        async with session_factory(engine)() as db:
            await tick_once(db)
    finally:
        await engine.dispose()


async def tick_once(db: AsyncSession, now: datetime | None = None) -> int:
    """One tick: sweep interrupted renders and expired files, start due schedules; how many
    runs started."""
    from regwatch.outputs import schedules, services

    # Each step on its own: a failing sweep must never keep due schedules from starting.
    for step, sweep in (("swept", services.sweep_stale), ("expired", services.sweep_retention)):
        try:
            if done := await sweep(db, now):
                _log.info(f"outputs_{step}", jobs=done)
        except Exception as exc:  # noqa: BLE001 - logged; the next tick tries again
            await db.rollback()
            _log.error(f"outputs_{step}_failed", error=type(exc).__name__)
    started = await schedules.tick(db, now)
    for name, job_id in started:
        await enqueue(name, job_id)
    return len(started)
