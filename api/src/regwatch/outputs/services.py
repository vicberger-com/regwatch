"""Output jobs (M8; REQ-10, REQ-15). M8.1: PDF of a report layout or a stock report.

Rules (the M7 reviews' list for M8):
- What may be printed: a stock report with ``reports.print``; a layout the user can see with
  ``reports.build``, or their own with ``reports.print``.
- Each run re-checks the requester's *current* account, rights and the layout's and saved
  view's visibility (``current_principal``): never what was allowed when the job was made.
- At most ``outputs.rate_per_hour_per_user`` jobs an hour, counted in the database.
- Artifacts are fetched through a link signed for 10 minutes, by their owner (or
  ``outputs.read_all``), and every step is audited.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.core.schemas import Page, has_control
from regwatch.core.services import audit
from regwatch.core.settings import get_settings
from regwatch.identity.models import User
from regwatch.identity.services import Principal, roles_and_permissions
from regwatch.outputs.models import OutputJob
from regwatch.outputs.schemas import OutputJob as JobOut
from regwatch.outputs.schemas import OutputRequest

READ_ALL = "outputs.read_all"
LINK_S = 600  # a signed artifact link lasts 10 minutes (contract)
KINDS_NOW = {"pdf", "email", "csv"}  # M8.1, M8.2, M8.4; print follows
TASKS = {"pdf": "outputs.render_pdf", "email": "outputs.send_email",
         "csv": "outputs.export_csv"}  # fmt: skip
RECIPIENTS_PER_HOUR = 100  # email recipients a user may reach in an hour (M8.1 review)
MAX_ATTEMPTS = 3  # renders per job, first try and retries together (M8.1 review finding 3)
STALE_AFTER = timedelta(minutes=5)  # a render outlives its 90-second limit: interrupted


def _invalid(field: str, message: str) -> ProblemError:
    return ProblemError(422, "validation", "The output request is not valid.",
                        errors=[ProblemFieldError(field=field, message=message)])  # fmt: skip


def out(job: OutputJob) -> JobOut:
    deleted = (job.query or {}).get(DELETED)
    source = (f"layout {job.report_layout_id}" if job.report_layout_id
              else f"stock report {job.report_template_key}" if job.report_template_key
              else "saved view" if job.saved_view_id
              else f"deleted {deleted}" if deleted else "query")  # fmt: skip
    return JobOut(
        id=job.id, kind=job.kind, status=job.status, requested_by=job.requested_by,
        source_summary=source,
        destination_summary=(f"email to {len((job.destination or {}).get('emails', []))} "
                             "recipients" if job.kind == "email" else "download"),
        artifact_available=job.artifact_ref is not None, artifact_bytes=job.artifact_bytes,
        error_class=job.error_class, error_message=job.error_message,
        scheduled_cron=job.scheduled_cron, next_run_at=job.next_run_at,
        attempts=job.attempts, created_at=job.created_at, finished_at=job.finished_at,
    )  # fmt: skip


async def current_principal(db: AsyncSession, user_id: uuid.UUID) -> Principal | None:
    """The requester as they are now: None once disabled, locked or gone."""
    user = await db.get(User, user_id)
    if user is None or user.status != "active":
        return None
    roles, perms = await roles_and_permissions(db, user.id)
    return Principal(user=user, session_id=uuid.UUID(int=0), roles=roles, permissions=perms)


async def check_source(db: AsyncSession, job: OutputJob, principal: Principal) -> Any:
    """The layout (saved, or built from the stock report) the principal may print now; for a
    CSV, the query they may export now."""
    from regwatch.reports import services as reports
    from regwatch.reports.models import ReportLayout, ReportTemplate

    if job.kind == "csv":
        from regwatch.outputs import csv_out

        return await csv_out.source(db, job, principal)
    if job.report_template_key is not None:
        if "reports.print" not in principal.permissions:
            raise ProblemError(403, "forbidden", "Printing stock reports needs reports.print.")
        template = await db.scalar(select(ReportTemplate).where(
            ReportTemplate.key == job.report_template_key))  # fmt: skip
        if template is None:
            raise ProblemError(404, "not-found", "No such stock report.")
        return ReportLayout(id=uuid.UUID(int=0), user_id=principal.user.id, name=template.label,
                            layout=template.layout,
                            query=(template.query or {}).get("data_source", {}),
                            page_size="A4", orientation="portrait", shared=False,
                            version=template.version,
                            based_on_template_key=template.key)  # fmt: skip
    if job.report_layout_id is None:
        raise _invalid("source", "M8.1 prints a report layout or a stock report")
    layout = await reports.get_layout(db, job.report_layout_id, principal)  # 404 if hidden
    own = layout.user_id == principal.user.id
    if "reports.build" not in principal.permissions and not (
            own and "reports.print" in principal.permissions):  # fmt: skip
        raise ProblemError(403, "forbidden", "Printing this report needs reports.build, or "
                           "reports.print for your own reports.")  # fmt: skip
    return layout


async def limited(db: AsyncSession, user_id: uuid.UUID) -> None:
    from regwatch.admin.services import values

    per_hour = int((await values(db, ["outputs.rate_per_hour_per_user"]))
                   ["outputs.rate_per_hour_per_user"])  # fmt: skip
    since = datetime.now(UTC) - timedelta(hours=1)
    made = await db.scalar(select(func.count()).select_from(OutputJob).where(
        OutputJob.requested_by == user_id, OutputJob.created_at >= since)) or 0  # fmt: skip
    if made >= per_hour:
        raise ProblemError(429, "rate-limited", f"At most {per_hour} outputs an hour; try "
                           "again later.", headers={"Retry-After": "600"})  # fmt: skip


async def create_output(db: AsyncSession, body: OutputRequest, principal: Principal,
                        ip: str | None) -> JobOut:  # fmt: skip
    from regwatch.reports import templates

    if body.kind.value not in KINDS_NOW:
        raise _invalid("kind", "PDF, email and CSV for now; print comes next")
    planned = await _schedule(db, body, principal) if body.schedule is not None else None
    chosen = body.source.model_dump(exclude_unset=True)
    if len(chosen) != 1:
        raise _invalid("source", "exactly one of report_layout_id, report_template_key, "
                       "saved_view_id and query")  # fmt: skip
    params = body.params.model_dump() if "params" in body.model_fields_set else {}
    destination: dict[str, Any] = {"report_params": params}
    if body.kind.value == "email":
        destination.update(await _email_destination(db, body, principal))
    job = OutputJob(requested_by=principal.user.id, kind=body.kind.value,
                    report_layout_id=body.source.report_layout_id
                    if "report_layout_id" in chosen else None,
                    report_template_key=body.source.report_template_key
                    if "report_template_key" in chosen else None,
                    saved_view_id=None, query=None,
                    destination=destination, status="queued")  # fmt: skip
    if job.kind == "csv":  # a query or a saved view, as the search exports it (M8.4)
        if "saved_view_id" in chosen:
            job.saved_view_id = body.source.saved_view_id
        elif "query" in chosen:
            job.query = body.source.query.model_dump(mode="json", exclude_unset=True)
        else:
            raise _invalid("source", "a CSV exports a query or a saved view")
    elif "saved_view_id" in chosen or "query" in chosen:
        raise _invalid("source", "a PDF or email prints a report layout or a stock report")
    layout = await check_source(db, job, principal)
    if job.kind != "csv":
        from regwatch.search.schemas import Query

        await templates.apply(db, Query(), layout.based_on_template_key, params)  # 422 early
    await limited(db, principal.user.id)
    job.layout_version = layout.version
    if planned is not None and body.schedule is not None:
        job.scheduled_cron = body.schedule.cron
        job.next_run_at, job.schedule_timezone = planned
    db.add(job)
    await db.flush()
    await db.refresh(job)
    audit(db, "output.create", "output_job", job.id, actor=principal.user.id, ip=ip,
          after={"kind": job.kind, "source": out(job).source_summary,
                 "layout_version": job.layout_version})  # fmt: skip
    result = out(job)
    await db.commit()
    if job.scheduled_cron is None:  # a schedule runs from the tick, when it falls due
        from regwatch.outputs.tasks import enqueue

        await enqueue(TASKS[job.kind], job.id)
    return result


async def _schedule(db: AsyncSession, body: OutputRequest,
                    principal: Principal) -> tuple[datetime, str]:  # fmt: skip
    """A checked schedule's first run and its time zone (M8.3)."""
    from regwatch.outputs import schedules

    assert body.schedule is not None  # noqa: S101 - the caller checked
    if "outputs.schedule" not in principal.permissions:
        raise ProblemError(403, "forbidden", "Scheduled outputs need outputs.schedule.")
    zone = body.schedule.timezone if "timezone" in body.schedule.model_fields_set else (
        (principal.user.preferences or {}).get("timezone") or "UTC")  # fmt: skip
    if "cron" not in body.schedule.model_fields_set:
        raise _invalid("schedule.cron", "a cron expression is required")
    try:
        first = schedules.check(body.schedule.cron, str(zone))
    except ValueError as exc:
        raise _invalid("schedule", str(exc)) from None
    if await schedules.count_active(db, principal.user.id) >= schedules.MAX_SCHEDULES:
        raise ProblemError(409, "conflict", f"At most {schedules.MAX_SCHEDULES} schedules; "
                           "remove one first.")  # fmt: skip
    return first, str(zone)


async def _email_destination(db: AsyncSession, body: OutputRequest,
                             principal: Principal) -> dict[str, Any]:  # fmt: skip
    """Checked recipients, subject and message for an email output (M8.2)."""
    from regwatch.admin.services import values
    from regwatch.outputs import mail

    if "outputs.email" not in principal.permissions:
        raise ProblemError(403, "forbidden", "Sending outputs by email needs outputs.email.")
    given = body.destination.model_dump(exclude_unset=True) \
        if "destination" in body.model_fields_set else {}  # fmt: skip
    domains = (await values(db, ["outputs.allowed_recipient_domains"]))[
        "outputs.allowed_recipient_domains"] or []  # fmt: skip
    try:
        emails = mail.check_recipients(list(given.get("emails", [])), list(domains))
    except ValueError as exc:
        raise _invalid("destination.emails", str(exc)) from None
    try:
        subject = mail.plain_line(str(given.get("subject") or "regwatch report"), 200)
    except ValueError:
        raise _invalid("destination.subject", "one line of plain text") from None
    message = str(given.get("message") or "")
    if any(has_control(line) for line in message.splitlines()):
        raise _invalid("destination.message", "plain text; no control characters")
    since = datetime.now(UTC) - timedelta(hours=1)
    recent = (await db.scalars(select(OutputJob.destination).where(
        OutputJob.requested_by == principal.user.id, OutputJob.kind == "email",
        OutputJob.created_at >= since))).all()  # fmt: skip
    if sum(len(d.get("emails", [])) for d in recent) + len(emails) > RECIPIENTS_PER_HOUR:
        raise ProblemError(429, "rate-limited", f"At most {RECIPIENTS_PER_HOUR} recipients an "
                           "hour; try again later.", headers={"Retry-After": "600"})  # fmt: skip
    return {"emails": emails, "subject": subject, "message": message[:5000]}


def _visible(principal: Principal) -> list[Any]:
    """Conditions for the jobs ``principal`` may see: their own, or all with read_all."""
    return [] if READ_ALL in principal.permissions else [
        OutputJob.requested_by == principal.user.id]  # fmt: skip


async def list_outputs(db: AsyncSession, principal: Principal, page: int, page_size: int,
                       scope: str, kind: str | None = None, status: str | None = None,
                       scheduled: bool | None = None) -> Page[JobOut]:  # fmt: skip
    if scope == "all" and READ_ALL not in principal.permissions:
        raise ProblemError(403, "forbidden", "Everyone's outputs need outputs.read_all.")
    where = _visible(principal) if scope == "all" else [
        OutputJob.requested_by == principal.user.id]  # fmt: skip
    if kind is not None:
        where.append(OutputJob.kind == kind)
    if status is not None:
        where.append(OutputJob.status == status)
    if scheduled is not None:  # the schedules themselves, or everything else (their runs too)
        where.append(OutputJob.scheduled_cron.is_not(None) if scheduled
                     else OutputJob.scheduled_cron.is_(None))  # fmt: skip
    total = await db.scalar(select(func.count()).select_from(OutputJob).where(*where)) or 0
    rows = (await db.scalars(select(OutputJob).where(*where)
                             .order_by(OutputJob.created_at.desc(), OutputJob.id)
                             .offset((page - 1) * page_size).limit(page_size))).all()  # fmt: skip
    return Page[JobOut](items=[out(r) for r in rows], total=total, page=page,
                        page_size=page_size)  # fmt: skip


async def get_job(db: AsyncSession, job_id: uuid.UUID, principal: Principal) -> OutputJob:
    job = await db.scalar(select(OutputJob).where(OutputJob.id == job_id,
                                                  *_visible(principal)))  # fmt: skip
    if job is None:
        raise ProblemError(404, "not-found", "No such output.")
    return job


def _signature(job_id: uuid.UUID, expires: int) -> str:
    key = get_settings().secret_key.get_secret_value().encode()
    return hmac.new(key, f"artifact:{job_id}:{expires}".encode(), hashlib.sha256).hexdigest()


def signed_link(job_id: uuid.UUID, prefix: str) -> str:
    expires = int(time.time()) + LINK_S
    return f"{prefix}/outputs/{job_id}/artifact?exp={expires}&sig={_signature(job_id, expires)}"


def link_valid(job_id: uuid.UUID, exp: int, sig: str) -> bool:
    return exp >= int(time.time()) and hmac.compare_digest(_signature(job_id, exp), sig)


async def retry(db: AsyncSession, job_id: uuid.UUID, principal: Principal,
                ip: str | None) -> JobOut:  # fmt: skip
    job = await get_job(db, job_id, principal)
    if job.requested_by != principal.user.id:
        raise ProblemError(403, "forbidden", "Only the requester can retry an output.")
    if job.status != "failed":
        raise ProblemError(409, "conflict", "Only a failed output can be tried again.")
    if job.scheduled_cron is not None:  # a paused schedule: resume it from now (M8.3)
        from regwatch.capture.schedule import next_run
        from regwatch.outputs import schedules

        await check_source(db, job, principal)
        if "outputs.schedule" not in principal.permissions:
            raise ProblemError(403, "forbidden", "Scheduled outputs need outputs.schedule.")
        if await schedules.count_active(db, principal.user.id) >= schedules.MAX_SCHEDULES:
            raise ProblemError(409, "conflict", f"At most {schedules.MAX_SCHEDULES} schedules; "
                               "remove one first.")  # fmt: skip
        job.status, job.error_class, job.error_message = "queued", None, None
        job.next_run_at = next_run(job.scheduled_cron, None, job.schedule_timezone or "UTC",
                                   datetime.now(UTC))  # fmt: skip
        audit(db, "output.schedule_resumed", "output_job", job.id, actor=principal.user.id,
              ip=ip)  # fmt: skip
        resumed = out(job)
        await db.commit()
        return resumed
    if job.attempts >= MAX_ATTEMPTS:
        raise ProblemError(409, "conflict", f"This output was tried {job.attempts} times; "
                           "request a new one.")  # fmt: skip
    await check_source(db, job, principal)
    await limited(db, principal.user.id)
    job.status, job.error_class, job.error_message = "queued", None, None
    audit(db, "output.retry", "output_job", job.id, actor=principal.user.id, ip=ip)
    result = out(job)
    await db.commit()
    from regwatch.outputs.tasks import enqueue

    await enqueue(TASKS[job.kind], job.id)
    return result


async def cancel(db: AsyncSession, job_id: uuid.UUID, principal: Principal,
                 ip: str | None) -> None:  # fmt: skip
    await get_job(db, job_id, principal)  # visible, or 404
    # Locked, so a render finishing at the same moment cannot overwrite the cancel (finding 2).
    job = await db.scalar(select(OutputJob).where(OutputJob.id == job_id).with_for_update())
    if job is None or job.requested_by != principal.user.id:
        raise ProblemError(403, "forbidden", "Only the requester can cancel an output.")
    stale = job.status == "rendering" and job.updated_at < datetime.now(UTC) - STALE_AFTER
    if job.status not in ("queued", "failed") and not stale and job.scheduled_cron is None:
        raise ProblemError(409, "conflict", f"The output is already {job.status}.")
    job.status = "cancelled"
    audit(db, "output.cancel", "output_job", job.id, actor=principal.user.id, ip=ip)
    await db.commit()


RETENTION_BATCH = 500  # files removed a tick at most


async def sweep_retention(db: AsyncSession, now: datetime | None = None) -> int:
    """Remove output files older than ``outputs.artifact_retention_days`` (M8.7; 90 by
    default); the jobs and their history stay. How many."""
    from regwatch.admin.services import values
    from regwatch.core import objectstore

    days = int((await values(db, ["outputs.artifact_retention_days"]))
               ["outputs.artifact_retention_days"])  # fmt: skip
    limit = (now or datetime.now(UTC)) - timedelta(days=max(1, days))
    old = (await db.scalars(select(OutputJob).where(
        OutputJob.artifact_ref.is_not(None), OutputJob.finished_at < limit)
        .order_by(OutputJob.finished_at).limit(RETENTION_BATCH)
        .with_for_update(skip_locked=True))).all()  # fmt: skip
    for job in old:
        await objectstore.delete(str(job.artifact_ref))  # the file first: never a lost ref
        job.artifact_ref = None
    if old:
        audit(db, "output.artifacts_expired", "output_job", None,
              after={"days": max(1, days), "jobs": [str(j.id) for j in old]})  # fmt: skip
    await db.commit()
    return len(old)


DELETED = "deleted_source"  # in ``query`` of a job whose layout or saved view was deleted


async def detach(db: AsyncSession, column: Any, source_id: uuid.UUID, what: str,
                 actor: uuid.UUID) -> None:  # fmt: skip
    """Before a layout or saved view is deleted: its outputs keep their history (and their
    files) with the source marked deleted; any still to run, schedules too, are cancelled.
    ``output_job`` references its source without ON DELETE, and exactly one source is set."""
    from sqlalchemy import update

    stopped = await db.execute(update(OutputJob).where(
        column == source_id, OutputJob.status.in_(("queued", "rendering", "failed")))
        .values(status="cancelled", error_class="source-deleted",
                error_message=f"the {what} was deleted", next_run_at=None)
        .returning(OutputJob.id, OutputJob.requested_by))  # fmt: skip
    for job_id, owner in stopped.all():  # by whoever deleted it, for the job's owner (review)
        audit(db, "output.cancel", "output_job", job_id, actor=actor,
              after={"reason": "source-deleted", "source": what, "owner": str(owner)})  # fmt: skip
    await db.execute(update(OutputJob).where(column == source_id)
                     .values({column: None, OutputJob.query: {DELETED: what}}))  # fmt: skip


async def sweep_stale(db: AsyncSession, now: datetime | None = None) -> int:
    """Mark renders that a crashed or killed worker left ``rendering`` as failed, so they can be
    retried (M8.1 review finding 1); how many."""
    from sqlalchemy import update

    limit = (now or datetime.now(UTC)) - STALE_AFTER
    done = await db.execute(update(OutputJob).where(
        OutputJob.status == "rendering", OutputJob.updated_at < limit).values(
        status="failed", error_class="interrupted",
        error_message="the render did not finish; try again", finished_at=func.now())
        .returning(OutputJob.id))  # fmt: skip
    ids = done.scalars().all()
    for job_id in ids:
        audit(db, "output.failed", "output_job", job_id, after={"error_class": "interrupted"})
    await db.commit()
    return len(ids)
