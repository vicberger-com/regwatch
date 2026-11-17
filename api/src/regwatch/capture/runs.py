"""Capture runs: the schedule tick, run-now, claiming and finishing runs, source health (M3).

ADR-0006: schedules live in PostgreSQL and Beat only fires ``capture.schedule_tick``. A run is
created as a ``capture_run`` row (status ``running``, no ``finished_at``) in the same
transaction that moves the job's ``next_run_at`` on, and only then is ``capture.run_job``
enqueued. A job has at most one unfinished run, checked under the job's row lock, so a source
never runs twice at once; this lock lives in PostgreSQL rather than Valkey, so a broker restart
cannot release it (ADR-0006 amendment, proposed).

Every path that waits for a lock takes the source before the job. A run row is locked first
only by the worker that owns the run, and otherwise only with ``SKIP LOCKED``, which never
waits; so no two paths can wait on each other.

A run's ``created_at`` is when it was created and its ``started_at`` when it was last handed to
a worker. A worker holds its run's row lock for the whole run. A message lost from Valkey (a
restart: the broker keeps nothing) leaves an unfinished run that no worker holds; the tick
hands it over again after ``HANDOVER_AFTER``, at most ``MAX_HANDOVERS`` times, as ADR-0006
says lost messages are re-enqueued (scheduler review finding 4). The hourly
``capture.health_check`` ends runs older than ``ABANDONED_AFTER`` as ``abandoned``.

A source turns ``unhealthy`` after ``UNHEALTHY_AFTER`` failed runs in a row (M3 design notes),
``degraded`` after one, and ``healthy`` again after a success. Skipped runs, and failures that
are ours rather than the source's (``abandoned``, ``queue-unavailable``), change nothing.
"""

from __future__ import annotations

import random
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture.execution import ContextFactory, Outcome, run_connector
from regwatch.capture.models import CaptureJob, CaptureRun, Source
from regwatch.capture.schedule import CronError, next_run
from regwatch.capture.schemas import CaptureRun as RunOut
from regwatch.core.errors import ProblemError
from regwatch.core.services import audit
from regwatch.identity.services import Principal

Enqueue = Callable[[uuid.UUID, float], Awaitable[None]]

UNHEALTHY_AFTER = 5
TICK_BATCH = 200  # jobs claimed per tick; the rest wait a minute
JITTER_S = 30.0  # spread the jobs due in one minute over half of it (ADR-0006)
HANDOVER_AFTER = timedelta(minutes=10)
MAX_HANDOVERS = 3  # hand-overs after the first; then the sweep ends the run (finding 10)
ABANDONED_AFTER = timedelta(hours=2)
RUN_NOW_SPACING = timedelta(seconds=60)  # finding 9
MAX_ERROR = 500  # capture_run.error_message: at most 500 characters, never page content
NOT_THE_SOURCE = frozenset({"abandoned", "queue-unavailable"})


_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>]+")


def _origin(match: re.Match[str]) -> str:
    try:
        parts = urlsplit(match.group(0))
        host = parts.hostname or "?"
    except ValueError:
        return "<url>"
    return f"{parts.scheme}://{host}/…"


def clean_error(message: str | None) -> str | None:
    """One line of printable text, at most ``MAX_ERROR`` characters (finding 11). URLs keep only
    their scheme and host: no user name, password, path or query reaches the run record
    (BL-90 (h))."""
    if not message:
        return None
    text = _URL.sub(_origin, message)
    text = "".join(c if c.isprintable() else " " for c in text)
    return " ".join(text.split())[:MAX_ERROR] or None


async def _unfinished(db: AsyncSession, job_id: uuid.UUID) -> CaptureRun | None:
    run: CaptureRun | None = await db.scalar(
        select(CaptureRun).where(CaptureRun.job_id == job_id, CaptureRun.finished_at.is_(None))
        .order_by(CaptureRun.created_at).limit(1))  # fmt: skip
    return run


async def _source_of(db: AsyncSession, job_id: uuid.UUID) -> Source | None:
    source: Source | None = await db.scalar(
        select(Source).join(CaptureJob, CaptureJob.source_id == Source.id)
        .where(CaptureJob.id == job_id).with_for_update(of=Source))  # fmt: skip
    return source


async def _close(db: AsyncSession, run: CaptureRun, status: str, error_class: str | None,
                 error_message: str | None, now: datetime,
                 outcome: Outcome | None = None) -> None:  # fmt: skip
    """End the run and update the job's last run and the source's health, without committing.
    A run that has already ended is left alone (finding 7)."""
    if run.finished_at is not None:
        return
    run.status = status
    run.finished_at = now
    run.error_class = error_class
    run.error_message = clean_error(error_message)
    if outcome is not None:
        run.items_new = outcome.items_new
        run.bytes_fetched = outcome.bytes_fetched
        run.robots_decision = outcome.robots_decision
    source = await _source_of(db, run.job_id)
    job = await db.scalar(select(CaptureJob).where(CaptureJob.id == run.job_id))
    if job is not None:
        job.last_run_at = now
    if source is None or status == "skipped" or error_class in NOT_THE_SOURCE:
        return
    if status == "failed":
        source.consecutive_failures += 1
        source.health = ("unhealthy" if source.consecutive_failures >= UNHEALTHY_AFTER
                         else "degraded")  # fmt: skip
    else:
        source.consecutive_failures = 0
        source.health = "healthy"


async def finish(db: AsyncSession, run: CaptureRun, status: str, *,
                 error_class: str | None = None, error_message: str | None = None,
                 now: datetime | None = None) -> None:  # fmt: skip
    """End the run and update the job's last run and the source's health; commits."""
    await _close(db, run, status, error_class, error_message, now or datetime.now(UTC))
    await db.commit()


async def _handed_over(db: AsyncSession, run: CaptureRun, enqueue: Enqueue,
                       countdown: float) -> bool:  # fmt: skip
    """Enqueue the run's job; if the broker cannot take it, end the run at once, so the source
    is not held by a run no worker will ever see."""
    try:
        await enqueue(run.job_id, countdown)
    except Exception:  # noqa: BLE001 - any broker failure, a timeout included, means the same
        await finish(db, run, "failed", error_class="queue-unavailable",
                     error_message="the run could not be handed to a worker")  # fmt: skip
        return False
    return True


async def _lost(db: AsyncSession, now: datetime) -> list[CaptureRun]:
    """Unfinished runs no worker holds, last handed over ``HANDOVER_AFTER`` ago, with hand-overs
    left; each hand-over moves ``started_at`` on, so ``started_at - created_at`` counts them."""
    rows = await db.scalars(
        select(CaptureRun).where(
            CaptureRun.finished_at.is_(None),
            CaptureRun.started_at < now - HANDOVER_AFTER,
            CaptureRun.started_at - CaptureRun.created_at < HANDOVER_AFTER * MAX_HANDOVERS,
        ).limit(TICK_BATCH).with_for_update(skip_locked=True))  # fmt: skip
    return list(rows)


async def _no_backlog() -> int:
    return 0


async def tick(db: AsyncSession, enqueue: Enqueue, now: datetime | None = None,
               backlog: Callable[[], Awaitable[int]] = _no_backlog) -> int:  # fmt: skip
    """``capture.schedule_tick``: start every due job of an enabled source and hand lost runs
    over again; returns how many runs were handed to workers.

    Jobs are claimed with ``SKIP LOCKED``, so two ticks never start the same job, and a job
    whose last run has not finished is moved on without a new run (one at a time per source).
    A job whose schedule cannot be computed fails its own run and waits for an edit; the others
    still run (finding 3).
    """
    now = now or datetime.now(UTC)
    jobs = (await db.scalars(
        select(CaptureJob).join(Source, Source.id == CaptureJob.source_id)
        .where(CaptureJob.enabled, Source.enabled, CaptureJob.next_run_at <= now)
        .order_by(CaptureJob.next_run_at).limit(TICK_BATCH)
        .with_for_update(of=CaptureJob, skip_locked=True))).all()  # fmt: skip
    started: list[CaptureRun] = []
    broken: list[tuple[uuid.UUID, str]] = []
    for job in jobs:
        try:
            job.next_run_at = next_run(job.cron, job.interval_seconds, job.timezone, now)
        except (CronError, ZoneInfoNotFoundError, ValueError) as exc:
            job.next_run_at = None  # not due again until the schedule is saved anew
            broken.append((job.id, type(exc).__name__))
            continue
        if await _unfinished(db, job.id) is None:
            run = CaptureRun(job_id=job.id, started_at=now)
            db.add(run)
            started.append(run)
    # A run waiting behind a backlog is not lost: hand nothing over again while the capture
    # queue still holds messages (BL-90 (g)).
    lost = await _lost(db, now) if await backlog() == 0 else []
    for run in lost:
        run.started_at = now
    await db.commit()
    # Recorded after the job locks are released: _close locks the source, and every other path
    # takes the source before the job, so taking it here under job locks could deadlock.
    for job_id, reason in broken:
        bad = CaptureRun(job_id=job_id, started_at=now)
        db.add(bad)
        await db.flush()
        message = f"the schedule cannot be computed: {reason}"
        await finish(db, bad, "failed", error_class="bad-schedule", error_message=message, now=now)
    handed = 0
    for run in [*started, *lost]:
        jitter = random.uniform(0, JITTER_S)  # noqa: S311 - spacing, not secrecy
        handed += await _handed_over(db, run, enqueue, jitter)
    # Beat's in-memory scheduler first fires the hourly health check an hour after it starts,
    # so a Beat restarted more often would never end a stuck run; every tick sweeps too
    # (scheduler re-verification 14). The sweep is cheap: it skips locked rows and finds few.
    await sweep(db, now)
    return handed


async def queue_now(db: AsyncSession, job_id: uuid.UUID, principal: Principal,
                    ip: str | None, enqueue: Enqueue) -> RunOut:  # fmt: skip
    """``POST /capture-jobs/{id}/run-now``: the job's unfinished run, or its run of the last
    ``RUN_NOW_SPACING``, if it has one; else a new run, audited and enqueued at once."""
    source_id = await db.scalar(select(CaptureJob.source_id).where(CaptureJob.id == job_id))
    if source_id is None:
        raise ProblemError(404, "not-found", "No such capture job.")
    source = await db.scalar(select(Source).where(Source.id == source_id).with_for_update())
    job = await db.scalar(select(CaptureJob).where(CaptureJob.id == job_id).with_for_update())
    if source is None or job is None:  # pragma: no cover - deleted between the two reads
        raise ProblemError(404, "not-found", "No such capture job.")
    if not source.enabled or not job.enabled:
        raise ProblemError(409, "conflict", "The source or its job is disabled; enable it first.")
    recent = await db.scalar(
        select(CaptureRun).where(CaptureRun.job_id == job.id)
        .where((CaptureRun.finished_at.is_(None))
               | ((CaptureRun.created_at > datetime.now(UTC) - RUN_NOW_SPACING)
                  # a run the broker refused never ran: "try again" must queue a new one (16)
                  & (CaptureRun.error_class.is_distinct_from("queue-unavailable"))))
        .order_by(CaptureRun.created_at.desc()).limit(1))  # fmt: skip
    if recent is not None:
        out = RunOut.model_validate(recent, from_attributes=True)
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


async def claim(db: AsyncSession, job_id: uuid.UUID) -> CaptureRun | None:
    """The job's oldest unfinished run, locked for this worker until the run ends; None if there
    is none (a message delivered twice) or another worker holds it."""
    run: CaptureRun | None = await db.scalar(
        select(CaptureRun).where(CaptureRun.job_id == job_id, CaptureRun.finished_at.is_(None))
        .order_by(CaptureRun.created_at).limit(1)
        .with_for_update(skip_locked=True))  # fmt: skip
    return run


async def execute(db: AsyncSession, job_id: uuid.UUID,
                  make_context: ContextFactory | None = None) -> str | None:  # fmt: skip
    """``capture.run_job``: run the job's claimed run with its kind's connector; returns its
    status, or None when there was nothing to run. ``make_context`` builds the fetcher and the
    store (``capture.tasks`` gives the real ones)."""
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
    if make_context is None:
        outcome = Outcome("failed", "no-connector", "no fetcher was configured for this run")
    else:
        outcome = await run_connector(run.id, job, source, make_context)
    await _close(db, run, outcome.status, outcome.error_class, outcome.error_message,
                 datetime.now(UTC), outcome)  # fmt: skip
    await db.commit()
    return outcome.status


async def sweep(db: AsyncSession, now: datetime | None = None) -> int:
    """``capture.health_check``: end runs created over ``ABANDONED_AFTER`` ago that no worker
    holds as ``abandoned``, in one transaction, so the locks on all of them hold until every
    one is ended (finding 7); returns how many."""
    now = now or datetime.now(UTC)
    stale = (await db.scalars(
        select(CaptureRun).where(CaptureRun.finished_at.is_(None),
                                 CaptureRun.created_at < now - ABANDONED_AFTER)
        .with_for_update(skip_locked=True))).all()  # fmt: skip
    for run in stale:
        await _close(db, run, "failed", "abandoned",
                     "the run did not finish within 2 hours", now)  # fmt: skip
    await db.commit()
    return len(stale)
