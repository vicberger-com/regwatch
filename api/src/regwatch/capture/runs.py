"""Capture runs: the schedule tick, run-now, claiming and finishing runs, source health (M3).

ADR-0006: schedules live in PostgreSQL and Beat only fires ``capture.schedule_tick``. A run is
created as a ``capture_run`` row (status ``running``, no ``finished_at``) in the same
transaction that moves the job's ``next_run_at`` on, and only then is ``capture.run_job``
enqueued. A job has at most one unfinished run, checked under the job's row lock, so a source
never runs twice at once; this lock lives in PostgreSQL rather than Valkey, so a broker restart
cannot release it (ASSUMPTIONS M3). A message lost from Valkey leaves an unfinished run that the
hourly ``capture.health_check`` ends as ``abandoned``.

A source turns ``unhealthy`` after ``UNHEALTHY_AFTER`` failed runs in a row (M3 design notes),
``degraded`` after one, and ``healthy`` again after a success. Skipped runs change nothing.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture.models import CaptureJob, CaptureRun, Source
from regwatch.capture.schedule import next_run
from regwatch.capture.schemas import CaptureRun as RunOut
from regwatch.core.errors import ProblemError
from regwatch.core.services import audit
from regwatch.identity.services import Principal

Enqueue = Callable[[uuid.UUID, float], Awaitable[None]]

UNHEALTHY_AFTER = 5
TICK_BATCH = 200  # jobs claimed per tick; the rest wait a minute
JITTER_S = 30.0  # spread the jobs due in one minute over half of it (ADR-0006)
ABANDONED_AFTER = timedelta(hours=2)
MAX_ERROR = 500  # capture_run.error_message: at most 500 characters, never page content


async def _unfinished(db: AsyncSession, job_id: uuid.UUID) -> CaptureRun | None:
    run: CaptureRun | None = await db.scalar(
        select(CaptureRun).where(CaptureRun.job_id == job_id, CaptureRun.finished_at.is_(None))
        .order_by(CaptureRun.started_at).limit(1))  # fmt: skip
    return run


def _advance(job: CaptureJob, now: datetime) -> None:
    job.next_run_at = next_run(job.cron, job.interval_seconds, job.timezone, now)


async def tick(db: AsyncSession, enqueue: Enqueue, now: datetime | None = None) -> int:
    """``capture.schedule_tick``: start every due job of an enabled source; returns how many.

    Jobs are claimed with ``SKIP LOCKED``, so two ticks never start the same job, and a job
    whose last run has not finished is moved on without a new run (one at a time per source).
    """
    now = now or datetime.now(UTC)
    jobs = (await db.scalars(
        select(CaptureJob).join(Source, Source.id == CaptureJob.source_id)
        .where(CaptureJob.enabled, Source.enabled, CaptureJob.next_run_at <= now)
        .order_by(CaptureJob.next_run_at).limit(TICK_BATCH)
        .with_for_update(of=CaptureJob, skip_locked=True))).all()  # fmt: skip
    started: list[CaptureRun] = []
    for job in jobs:
        _advance(job, now)
        if await _unfinished(db, job.id) is None:
            run = CaptureRun(job_id=job.id, started_at=now)
            db.add(run)
            started.append(run)
    await db.commit()
    handed = 0
    for run in started:
        jitter = random.uniform(0, JITTER_S)  # noqa: S311 - spacing, not secrecy
        handed += await _handed_over(db, run, enqueue, jitter)
    return handed


async def queue_now(db: AsyncSession, job_id: uuid.UUID, principal: Principal,
                    ip: str | None, enqueue: Enqueue) -> RunOut:  # fmt: skip
    """``POST /capture-jobs/{id}/run-now``: the job's unfinished run if it has one, else a new
    run, audited and enqueued at once."""
    source_id = await db.scalar(select(CaptureJob.source_id).where(CaptureJob.id == job_id))
    if source_id is None:
        raise ProblemError(404, "not-found", "No such capture job.")
    source = await db.scalar(select(Source).where(Source.id == source_id).with_for_update())
    job = await db.scalar(select(CaptureJob).where(CaptureJob.id == job_id).with_for_update())
    if source is None or job is None:  # pragma: no cover - deleted between the two reads
        raise ProblemError(404, "not-found", "No such capture job.")
    if not source.enabled:
        raise ProblemError(409, "conflict", "The source is disabled; enable it to run it.")
    running = await _unfinished(db, job.id)
    if running is not None:
        out = RunOut.model_validate(running, from_attributes=True)
        await db.commit()
        return out
    run = CaptureRun(job_id=job.id, triggered_by=principal.user.id,
                     started_at=datetime.now(UTC))  # fmt: skip
    db.add(run)
    await db.flush()
    await db.refresh(run)
    audit(db, "capture_job.run_now", "capture_job", job.id, actor=principal.user.id, ip=ip,
          after={"run_id": str(run.id), "source_id": str(source.id)})  # fmt: skip
    out = RunOut.model_validate(run, from_attributes=True)
    await db.commit()
    if not await _handed_over(db, run, enqueue, 0.0):
        raise ProblemError(503, "queue-unavailable", "The run could not be queued; try again.")
    return out


async def _handed_over(db: AsyncSession, run: CaptureRun, enqueue: Enqueue,
                       countdown: float) -> bool:  # fmt: skip
    """Enqueue the run's job; if the broker cannot take it, end the run at once, so the source
    is not held for two hours by a run no worker will ever see."""
    try:
        await enqueue(run.job_id, countdown)
    except Exception:  # noqa: BLE001 - any broker failure means the same thing here
        await finish(db, run, "failed", error_class="queue-unavailable",
                     error_message="the run could not be handed to a worker")  # fmt: skip
        return False
    return True


async def claim(db: AsyncSession, job_id: uuid.UUID) -> CaptureRun | None:
    """The job's oldest unfinished run, locked for this worker; None if there is none (a
    message delivered twice) or another worker holds it."""
    run: CaptureRun | None = await db.scalar(
        select(CaptureRun).where(CaptureRun.job_id == job_id, CaptureRun.finished_at.is_(None))
        .order_by(CaptureRun.started_at).limit(1)
        .with_for_update(skip_locked=True))  # fmt: skip
    return run


async def finish(db: AsyncSession, run: CaptureRun, status: str, *,
                 error_class: str | None = None, error_message: str | None = None,
                 now: datetime | None = None) -> None:  # fmt: skip
    """End the run and update the job's last run and the source's health; commits."""
    now = now or datetime.now(UTC)
    run.status = status
    run.finished_at = now
    run.error_class = error_class
    run.error_message = error_message[:MAX_ERROR] if error_message else None
    job = await db.scalar(select(CaptureJob).where(CaptureJob.id == run.job_id))
    source = await db.scalar(select(Source).where(Source.id == job.source_id).with_for_update()
                             ) if job is not None else None  # fmt: skip
    if job is not None:
        job.last_run_at = now
    if source is not None and status != "skipped":
        if status == "failed":
            source.consecutive_failures += 1
            source.health = ("unhealthy" if source.consecutive_failures >= UNHEALTHY_AFTER
                             else "degraded")  # fmt: skip
        else:
            source.consecutive_failures = 0
            source.health = "healthy"
    await db.commit()


async def execute(db: AsyncSession, job_id: uuid.UUID) -> str | None:
    """``capture.run_job``: run the job's claimed run; returns its status, or None when there
    was nothing to run. Connectors land kind by kind; until a kind has one, its runs fail as
    ``no-connector`` rather than pretending to succeed."""
    run = await claim(db, job_id)
    if run is None:
        await db.commit()
        return None
    job = await db.scalar(select(CaptureJob).where(CaptureJob.id == job_id))
    source = await db.scalar(select(Source).where(Source.id == job.source_id)
                             ) if job is not None else None  # fmt: skip
    if job is None or source is None or not source.enabled or not job.enabled:
        await finish(db, run, "skipped", error_class="disabled",
                     error_message="the source or its job was disabled before the run")  # fmt: skip
        return "skipped"
    # Connector runs are wired with the first connector (RSS); until then every run ends here
    # as a failure that says why, so no source looks healthy without having been fetched.
    await finish(db, run, "failed", error_class="no-connector",
                 error_message=f"no connector runs {source.kind} sources yet")  # fmt: skip
    return "failed"


async def sweep(db: AsyncSession, now: datetime | None = None) -> int:
    """``capture.health_check``: end runs that never finished (a lost message, a killed
    worker) as ``abandoned``, so their sources can run again; returns how many."""
    now = now or datetime.now(UTC)
    stale = (await db.scalars(
        select(CaptureRun).where(CaptureRun.finished_at.is_(None),
                                 CaptureRun.started_at < now - ABANDONED_AFTER)
        .with_for_update(skip_locked=True))).all()  # fmt: skip
    for run in stale:
        await finish(db, run, "failed", error_class="abandoned",
                     error_message="the run did not finish within 2 hours", now=now)  # fmt: skip
    await db.commit()
    return len(stale)
