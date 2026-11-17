"""Integration: the schedule tick, run-now, runs and source health (M3; ADR-0006; REQ-02)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture import runs, tasks
from regwatch.capture.models import CaptureJob, CaptureRun, Source
from regwatch.core.db import create_engine, session_factory
from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import clear_limits, db_url
from tests.integration.test_sources import fixed_dns, rss

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db_url", "fixed_dns"]  # shared fixtures


class Queue:
    """Stands in for the broker: records hand-overs, or refuses them."""

    def __init__(self) -> None:
        self.sent: list[tuple[uuid.UUID, float]] = []
        self.down = False

    async def __call__(self, job_id: uuid.UUID, countdown: float) -> None:
        if self.down:
            raise ConnectionError("broker unavailable")
        self.sent.append((job_id, countdown))


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> Queue:
    q = Queue()
    monkeypatch.setattr(tasks, "enqueue_run", q)
    return q


@pytest.fixture
async def db(db_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_engine(db_url, poolclass_null=True)
    async with session_factory(engine)() as session:
        yield session
    await engine.dispose()


async def _job(db: AsyncSession, job_id: str) -> CaptureJob:
    db.expire_all()
    job = await db.scalar(select(CaptureJob).where(CaptureJob.id == uuid.UUID(job_id)))
    assert job is not None
    return job


async def test_run_now_queues_once_and_is_audited(admin: httpx.AsyncClient, queue: Queue) -> None:
    made = (await admin.post(_api("/sources"), json=rss())).json()
    jid = made["job"]["id"]
    first = await admin.post(_api(f"/capture-jobs/{jid}/run-now"))
    assert first.status_code == 202, first.text
    assert first.json()["status"] == "running" and first.json()["finished_at"] is None
    again = await admin.post(_api(f"/capture-jobs/{jid}/run-now"))
    assert again.json()["id"] == first.json()["id"]  # one run at a time per source
    assert [str(j) for j, _ in queue.sent] == [jid]
    audit = await admin.get(_api("/admin/audit"), params={"action": "capture_job.run_now"})
    assert audit.json()["items"][0]["after"]["run_id"] == first.json()["id"]

    viewer = await _as_new_user(admin, "rv@example.org", ["viewer"])
    assert (await viewer.post(_api(f"/capture-jobs/{jid}/run-now"))).status_code == 403
    missing = "00000000-0000-7000-8000-000000000000"
    assert (await admin.post(_api(f"/capture-jobs/{missing}/run-now"))).status_code == 404


async def test_run_now_refuses_disabled_sources_and_a_down_broker(
    admin: httpx.AsyncClient, queue: Queue, db: AsyncSession
) -> None:
    made = (await admin.post(_api("/sources"), json=rss())).json()
    jid = made["job"]["id"]
    queue.down = True
    down = await admin.post(_api(f"/capture-jobs/{jid}/run-now"))
    assert down.status_code == 503
    run = await db.scalar(select(CaptureRun).where(CaptureRun.job_id == uuid.UUID(jid)))
    assert run is not None and run.status == "failed" and run.error_class == "queue-unavailable"
    health = (await admin.get(_api(f"/sources/{made['id']}/health"))).json()
    assert health["health"] == "unknown" and health["consecutive_failures"] == 0  # ours, not its
    queue.down = False
    spaced = await admin.post(_api(f"/capture-jobs/{jid}/run-now"))  # within 60 s: no new run
    assert spaced.status_code == 202 and spaced.json()["id"] == str(run.id)
    assert queue.sent == []
    paused = await admin.patch(_api(f"/capture-jobs/{jid}"), json={"enabled": False})
    assert paused.status_code == 200
    assert (await admin.post(_api(f"/capture-jobs/{jid}/run-now"))).status_code == 409
    assert (
        await admin.patch(_api(f"/capture-jobs/{jid}"), json={"enabled": True})
    ).status_code == 200
    assert (await admin.delete(_api(f"/sources/{made['id']}"))).status_code == 204
    assert (await admin.post(_api(f"/capture-jobs/{jid}/run-now"))).status_code == 409


async def test_the_tick_starts_due_jobs_once(
    admin: httpx.AsyncClient, queue: Queue, db: AsyncSession
) -> None:
    due = (await admin.post(_api("/sources"), json=rss())).json()
    off = (await admin.post(_api("/sources"), json=rss(name="Off"))).json()
    assert (await admin.delete(_api(f"/sources/{off['id']}"))).status_code == 204
    later = datetime.now(UTC) + timedelta(seconds=5)

    assert await runs.tick(db, queue, now=later) == 1  # the disabled source is not started
    assert [str(j) for j, _ in queue.sent] == [due["job"]["id"]]
    assert all(0 <= c <= runs.JITTER_S for _, c in queue.sent)
    job = await _job(db, due["job"]["id"])
    assert job.next_run_at == later + timedelta(seconds=3600)  # one interval on
    assert await runs.tick(db, queue, now=later) == 0  # not due again

    # Due again while the first run is unfinished: moved on, no second run.
    await db.execute(update(CaptureJob).where(CaptureJob.id == job.id)
                     .values(next_run_at=later))  # fmt: skip
    await db.commit()
    assert await runs.tick(db, queue, now=later + timedelta(seconds=1)) == 0
    made = (await db.scalars(select(CaptureRun.id).where(CaptureRun.job_id == job.id))).all()
    assert len(made) == 1 and len(queue.sent) == 1
    assert (await _job(db, due["job"]["id"])).next_run_at > later


async def test_runs_fail_without_a_connector_and_move_health(
    admin: httpx.AsyncClient, queue: Queue, db: AsyncSession
) -> None:
    """Until a kind has a connector its runs fail and say so; five failures in a row make the
    source unhealthy, a success heals it, a skipped run changes nothing."""
    made = (await admin.post(_api("/sources"), json=rss())).json()
    sid, jid = made["id"], uuid.UUID(made["job"]["id"])
    assert await runs.execute(db, jid) is None  # nothing claimed: a duplicate message
    for n in range(1, 6):
        db.add(CaptureRun(job_id=jid, started_at=datetime.now(UTC)))
        await db.commit()
        assert await runs.execute(db, jid) == "failed"
        health = (await admin.get(_api(f"/sources/{sid}/health"))).json()
        assert health["consecutive_failures"] == n
        assert health["health"] == ("unhealthy" if n >= 5 else "degraded")
    last = (await admin.get(_api("/capture-runs"), params={"job_id": str(jid)})).json()
    assert last["items"][0]["error_class"] == "no-connector"
    assert (await _job(db, str(jid))).last_run_at is not None

    run = CaptureRun(job_id=jid, started_at=datetime.now(UTC))
    db.add(run)
    await db.commit()
    await runs.finish(db, run, "success")
    healed = (await admin.get(_api(f"/sources/{sid}/health"))).json()
    assert healed["health"] == "healthy" and healed["consecutive_failures"] == 0

    run = CaptureRun(job_id=jid, started_at=datetime.now(UTC))
    db.add(run)
    await db.commit()
    await db.execute(update(Source).where(Source.id == uuid.UUID(sid)).values(enabled=False))
    await db.commit()
    assert await runs.execute(db, jid) == "skipped"  # disabled after it was queued
    assert (await admin.get(_api(f"/sources/{sid}/health"))).json()["health"] == "healthy"


async def test_abandoned_runs_are_ended(
    admin: httpx.AsyncClient, queue: Queue, db: AsyncSession, db_url: str
) -> None:
    made = (await admin.post(_api("/sources"), json=rss())).json()
    jid = uuid.UUID(made["job"]["id"])
    long_ago = datetime.now(UTC) - timedelta(hours=3)
    old = CaptureRun(job_id=jid, created_at=long_ago, started_at=long_ago)
    held = CaptureRun(job_id=jid, created_at=long_ago, started_at=long_ago)
    fresh = CaptureRun(job_id=jid, started_at=datetime.now(UTC))
    db.add_all([old, held, fresh])
    await db.commit()
    old_id, held_id, fresh_id = old.id, held.id, fresh.id
    async with session_factory(create_engine(db_url, poolclass_null=True))() as worker:
        # A worker holds one stale run (its run is slow, not lost): the sweep leaves it alone.
        await worker.scalar(select(CaptureRun).where(CaptureRun.id == held_id)
                            .with_for_update())  # fmt: skip
        assert await runs.sweep(db) == 1
        await worker.rollback()
    db.expire_all()
    ended = await db.scalar(select(CaptureRun).where(CaptureRun.id == old_id))
    assert ended is not None and ended.status == "failed" and ended.error_class == "abandoned"
    still = await db.scalar(select(CaptureRun).where(CaptureRun.id == fresh_id))
    assert still is not None and still.finished_at is None
    kept = await db.scalar(select(CaptureRun).where(CaptureRun.id == held_id))
    assert kept is not None and kept.finished_at is None
    health = (await admin.get(_api(f"/sources/{made['id']}/health"))).json()
    assert health["consecutive_failures"] == 0  # abandoned is ours, not the source's

    # finish never overwrites a run that has already ended (review finding 7).
    assert ended is not None
    await runs.finish(db, ended, "success")
    db.expire_all()
    again = await db.scalar(select(CaptureRun).where(CaptureRun.id == old_id))
    assert again is not None and again.status == "failed"


async def test_a_broken_schedule_fails_alone(
    admin: httpx.AsyncClient, queue: Queue, db: AsyncSession
) -> None:
    """Review finding 3: a job whose schedule cannot be computed (a zone this image lacks)
    fails its own run and waits for an edit; every other due job still starts."""
    good = (await admin.post(_api("/sources"), json=rss())).json()
    bad = (await admin.post(_api("/sources"), json=rss(name="Bad"))).json()
    await db.execute(update(CaptureJob).where(CaptureJob.id == uuid.UUID(bad["job"]["id"]))
                     .values(cron="0 * * * *", interval_seconds=None,
                             timezone="Nowhere/Atlantis"))  # fmt: skip
    await db.commit()
    later = datetime.now(UTC) + timedelta(seconds=5)
    assert await runs.tick(db, queue, now=later) == 1
    assert [str(j) for j, _ in queue.sent] == [good["job"]["id"]]
    broken = (await admin.get(_api("/capture-runs"), params={"job_id": bad["job"]["id"]})).json()
    assert broken["items"][0]["error_class"] == "bad-schedule"
    assert (await _job(db, bad["job"]["id"])).next_run_at is None


async def test_lost_runs_are_handed_over_again_three_times(
    admin: httpx.AsyncClient, queue: Queue, db: AsyncSession
) -> None:
    """Review finding 4: a message lost from Valkey (a restart) is handed over again by the
    tick, as ADR-0006 says, at most three times, never while a worker holds the run."""
    made = (await admin.post(_api("/sources"), json=rss())).json()
    jid = uuid.UUID(made["job"]["id"])
    await db.execute(update(CaptureJob).where(CaptureJob.id == jid).values(next_run_at=None))
    created = datetime.now(UTC) - timedelta(minutes=11)
    lost = CaptureRun(job_id=jid, created_at=created, started_at=created)
    db.add(lost)
    await db.commit()
    lost_id = lost.id
    now = datetime.now(UTC)
    for n in range(runs.MAX_HANDOVERS):
        assert await runs.tick(db, queue, now=now) == 1, n
        now += runs.HANDOVER_AFTER + timedelta(seconds=1)
    assert len(queue.sent) == runs.MAX_HANDOVERS
    assert await runs.tick(db, queue, now=now) == 0  # out of hand-overs: the sweep ends it
    db.expire_all()
    run = await db.scalar(select(CaptureRun).where(CaptureRun.id == lost_id))
    assert run is not None and run.finished_at is None


async def test_concurrent_ticks_start_a_job_once(
    admin: httpx.AsyncClient, queue: Queue, db_url: str
) -> None:
    """Review finding 12: two ticks at once, on separate connections."""
    import asyncio

    made = (await admin.post(_api("/sources"), json=rss())).json()
    later = datetime.now(UTC) + timedelta(seconds=5)
    engines = [create_engine(db_url, poolclass_null=True) for _ in range(4)]
    try:

        async def one(n: int) -> int:
            async with session_factory(engines[n])() as session:
                return await runs.tick(session, queue, now=later)

        assert sum(await asyncio.gather(*(one(n) for n in range(4)))) == 1
    finally:
        for engine in engines:
            await engine.dispose()
    assert [str(j) for j, _ in queue.sent] == [made["job"]["id"]]
