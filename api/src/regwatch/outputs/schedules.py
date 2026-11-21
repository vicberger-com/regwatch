"""Scheduled outputs (M8.3; REQ-15; acceptance 4).

A schedule is an ``output_job`` with ``scheduled_cron`` set: ``queued`` while it is active,
``failed`` once paused, ``cancelled`` when its owner removes it. Each time it falls due the tick
makes a child job (``parent_job_id``) that runs like any other output.

What it holds to (M8.1 review, BL-143 f):
- A valid five-field cron, at least an hour between runs (checked over a year, so clock changes
  too), in an IANA time zone (the owner's preference by default); at most ``MAX_SCHEDULES``
  active schedules a user, resumed ones included.
- Each run is checked against the owner's *current* account and rights; a schedule whose owner
  is no longer active, or whose report they can no longer see, is paused and audited; so is
  one whose run fails for a reason that would fail every run (``PAUSE_ON``).
- Due schedules are claimed with ``SKIP LOCKED`` and their next run is set in the same
  transaction, so none runs twice; scheduled runs count in the owner's hourly limit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture.schedule import CronError, next_run, parse_cron
from regwatch.core.errors import ProblemError
from regwatch.core.services import audit
from regwatch.outputs.models import OutputJob

MAX_SCHEDULES = 10
MIN_GAP = timedelta(hours=1)
TICK_BATCH = 50
CHECKED_SPAN = timedelta(days=366)  # every gap in a year, so both clock changes are in it
_MAX_RUNS = 9000  # an hourly schedule makes at most 8784 runs a year


def check(cron: str, timezone: str, now: datetime | None = None) -> datetime:
    """The first run of a valid schedule; a ``ValueError`` saying what is wrong."""
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("an IANA time zone, such as Europe/Berlin") from None
    try:
        parse_cron(cron)
    except CronError:
        raise ValueError("five cron fields, such as 0 7 * * 1 for Mondays at 07:00") from None
    start = now or datetime.now(UTC)
    runs: list[datetime] = []
    at = start
    for _ in range(_MAX_RUNS):
        nxt = next_run(cron, None, zone.key, at)
        if nxt is None or nxt > start + CHECKED_SPAN:
            break
        runs.append(nxt)
        at = nxt
    if not runs:
        raise ValueError("this schedule never runs")
    if any(b - a < MIN_GAP for a, b in zip(runs, runs[1:], strict=False)):
        raise ValueError("at least an hour between runs")
    return runs[0]


async def count_active(db: AsyncSession, user_id: Any) -> int:
    return await db.scalar(select(func.count()).select_from(OutputJob).where(
        OutputJob.requested_by == user_id, OutputJob.scheduled_cron.is_not(None),
        OutputJob.status == "queued")) or 0  # fmt: skip


# A run failing for one of these will fail every time: its schedule is paused (M8.3 review).
PAUSE_ON = frozenset(
    {
        "requester-inactive",
        "forbidden",
        "not-found",
        "recipient-refused",
        "conflict",
        "invalid-query",
        "printing-off",
        "printer-removed",
        "printer-address-refused",
    }
)  # a saved view no longer visible; a bad query


async def pause_parent(db: AsyncSession, child: OutputJob, error_class: str,
                       message: str) -> None:  # fmt: skip
    """Pause the schedule a run came from, when the run failed for a lasting reason."""
    if child.parent_job_id is None or error_class not in PAUSE_ON:
        return
    parent = await db.scalar(select(OutputJob).where(OutputJob.id == child.parent_job_id)
                             .with_for_update())  # fmt: skip
    if parent is not None and parent.status == "queued":
        _pause(db, parent, error_class, message)


def _pause(db: AsyncSession, job: OutputJob, error_class: str, message: str) -> None:
    job.status, job.error_class, job.error_message = "failed", error_class, message[:500]
    job.next_run_at = None
    audit(db, "output.schedule_paused", "output_job", job.id, actor=job.requested_by,
          after={"error_class": error_class})  # fmt: skip


async def tick(db: AsyncSession, now: datetime | None = None) -> list[Any]:
    """Start every due schedule once; the child jobs to hand to the workers."""
    from regwatch.outputs import services

    now = now or datetime.now(UTC)
    due = (await db.scalars(select(OutputJob).where(
        OutputJob.scheduled_cron.is_not(None), OutputJob.status == "queued",
        OutputJob.next_run_at <= now).order_by(OutputJob.next_run_at).limit(TICK_BATCH)
        .with_for_update(skip_locked=True))).all()  # fmt: skip
    children: list[OutputJob] = []
    for parent in due:
        cron, zone = str(parent.scheduled_cron), parent.schedule_timezone or "UTC"
        parent.next_run_at = next_run(cron, None, zone, now)  # moved in the same transaction
        principal = await services.current_principal(db, parent.requested_by)
        if principal is None:
            _pause(db, parent, "owner-inactive", "the owner's account is not active")
            continue
        if "outputs.schedule" not in principal.permissions:
            _pause(db, parent, "forbidden", "scheduled outputs need outputs.schedule")
            continue
        try:
            layout = await services.check_source(db, parent, principal)
            await services.limited(db, principal.user.id)
        except ProblemError as exc:
            if exc.status == 429:  # over the hourly limit: this run is skipped, not paused
                audit(db, "output.schedule_skipped", "output_job", parent.id,
                      actor=parent.requested_by, after={"reason": "rate-limited"})  # fmt: skip
                continue
            _pause(db, parent, exc.slug, exc.detail or exc.title)
            continue
        child = OutputJob(requested_by=parent.requested_by, kind=parent.kind,
                          report_layout_id=parent.report_layout_id,
                          report_template_key=parent.report_template_key,
                          saved_view_id=parent.saved_view_id, query=parent.query,
                          destination=dict(parent.destination or {}), status="queued",
                          parent_job_id=parent.id, layout_version=layout.version)  # fmt: skip
        db.add(child)
        await db.flush()  # counted by ``limited`` for the owner's next due schedule (review)
        children.append(child)
    for child in children:
        audit(db, "output.create", "output_job", child.id, actor=child.requested_by,
              after={"kind": child.kind, "scheduled": True,
                     "parent": str(child.parent_job_id)})  # fmt: skip
    await db.commit()
    return [(services.TASKS[c.kind], c.id) for c in children]
