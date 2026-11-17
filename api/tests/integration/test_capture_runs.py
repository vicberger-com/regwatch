"""Integration: the schedule tick, run-now, runs and source health (M3; ADR-0006; REQ-02)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

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
    retry = await admin.post(_api(f"/capture-jobs/{jid}/run-now"))  # "try again" works (16)
    assert retry.status_code == 202 and retry.json()["id"] != str(run.id)
    assert len(queue.sent) == 1
    await runs.execute(db, uuid.UUID(jid))  # that run ends (no connector yet)
    spaced = await admin.post(_api(f"/capture-jobs/{jid}/run-now"))  # within 60 s: no new run
    assert spaced.status_code == 202 and spaced.json()["id"] == retry.json()["id"]
    assert len(queue.sent) == 1
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
    # One unfinished run per job (CP-11), so each run has a source of its own.
    made = (await admin.post(_api("/sources"), json=rss())).json()
    jobs = [uuid.UUID(made["job"]["id"])]
    for name in ("Held", "Fresh"):
        other = (await admin.post(_api("/sources"), json=rss(name=name))).json()
        jobs.append(uuid.UUID(other["job"]["id"]))
    long_ago = datetime.now(UTC) - timedelta(hours=3)
    old = CaptureRun(job_id=jobs[0], created_at=long_ago, started_at=long_ago)
    held = CaptureRun(job_id=jobs[1], created_at=long_ago, started_at=long_ago)
    fresh = CaptureRun(job_id=jobs[2], started_at=datetime.now(UTC))
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

    async def busy() -> int:
        return 5

    # BL-90 (g): a run waiting behind a backlog is not lost, so nothing is handed over again.
    assert await runs.tick(db, queue, now=now, backlog=busy) == 0
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


async def test_every_tick_sweeps_abandoned_runs(
    admin: httpx.AsyncClient, queue: Queue, db: AsyncSession
) -> None:
    """Scheduler re-verification 14: a Beat restarted more often than hourly never fires the
    hourly check, so the tick ends abandoned runs too and the job can run again."""
    made = (await admin.post(_api("/sources"), json=rss())).json()
    jid = uuid.UUID(made["job"]["id"])
    long_ago = datetime.now(UTC) - timedelta(hours=3)
    db.add(CaptureRun(job_id=jid, created_at=long_ago, started_at=long_ago))
    await db.commit()
    later = datetime.now(UTC) + timedelta(seconds=5)
    await runs.tick(db, queue, now=later)  # sweeps the stuck run
    assert await runs.tick(db, queue, now=later + timedelta(hours=2)) == 1  # runs again


def _site(robots: str) -> Any:
    """A feed site: robots.txt as given, a two-entry feed, and pages."""
    import httpx

    feed = (b'<?xml version="1.0"?><rss version="2.0"><channel><title>N</title>'
            b"<item><title>One</title><link>https://feeds.example/1</link></item>"
            b"<item><title>Two</title><link>https://feeds.example/2</link></item>"
            b"</channel></rss>")  # fmt: skip

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, stream=httpx.ByteStream(robots.encode()))
        if request.url.path == "/rss":
            return httpx.Response(200, headers={"content-type": "application/rss+xml"},
                                  stream=httpx.ByteStream(feed))  # fmt: skip
        return httpx.Response(200, headers={"content-type": "text/html"},
                              stream=httpx.ByteStream(b"<p>page</p>"))  # fmt: skip

    return httpx.MockTransport(handler)


def _factory(transport: Any, stored: dict[str, bytes]) -> Any:
    from regwatch.capture.connectors.base import ConnectorContext, JobSettings
    from regwatch.capture.safe_fetch import CaptureFetcher, MemoryRateLimiter, SafeFetcher

    async def public(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    async def no_wait(seconds: float) -> None:
        return None

    async def store(key: str, body: bytes) -> None:
        stored[key] = body

    fetcher = SafeFetcher("regwatch-test", resolver=public, transport=transport)

    async def make(job: JobSettings) -> ConnectorContext:
        capture = CaptureFetcher(fetcher, MemoryRateLimiter(), rate_per_minute=6000,
                                 sleep=no_wait)  # fmt: skip
        return ConnectorContext(fetcher=capture, store=store, now=lambda: datetime.now(UTC))

    return make


@pytest.mark.parametrize(
    ("robots", "status", "decision", "new", "health"),
    [("User-agent: *\nAllow: /\n", "success", "allowed", 2, "healthy"),
     ("User-agent: *\nDisallow: /\n", "skipped", "disallowed", 0, "unknown")],
)  # fmt: skip
async def test_an_rss_source_runs_end_to_end(
    admin: httpx.AsyncClient,
    queue: Queue,
    db: AsyncSession,
    robots: str,
    status: str,
    decision: str,
    new: int,
    health: str,
) -> None:
    """M3 acceptance 1 (a run of an RSS source records its counts) and 4 (robots.txt that
    disallows the feed skips the run with the decision recorded)."""
    made = (await admin.post(_api("/sources"), json=rss())).json()
    jid = uuid.UUID(made["job"]["id"])
    assert (await admin.post(_api(f"/capture-jobs/{jid}/run-now"))).status_code == 202
    stored: dict[str, bytes] = {}
    assert await runs.execute(db, jid, _factory(_site(robots), stored)) == status
    run = (await admin.get(_api("/capture-runs"), params={"job_id": str(jid)})).json()["items"][0]
    assert (run["status"], run["robots_decision"], run["items_new"]) == (status, decision, new)
    assert (run["bytes_fetched"] > 0) == (new > 0)
    assert (await admin.get(_api(f"/sources/{made['id']}/health"))).json()["health"] == health
    if new:
        manifests = [k for k in stored if "/runs/" in k]
        assert manifests == [f"raw/{made['id']}/runs/{run['id']}.json"]


class FakeValkey:
    """Enough of redis.asyncio for the task wiring: a queue length and a slot script."""

    def __init__(self, backlog: int = 0) -> None:
        self.backlog, self.closed = backlog, False

    def register_script(self, source: str) -> Any:
        async def script(keys: list[str], args: list[int]) -> int:
            return 0

        return script

    async def llen(self, name: str) -> int:
        assert name == "capture"
        return self.backlog

    async def aclose(self) -> None:
        self.closed = True


async def test_the_worker_wiring(
    admin: httpx.AsyncClient, queue: Queue, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """capture.tasks builds runs from the settings: the user agent names the contact address,
    the body cap is the setting, and the tick and run close their Valkey client."""
    from regwatch.capture.connectors.base import JobSettings
    from regwatch.capture.connectors.config import ExtractionRules, RssConfig

    for key, value in (("general.contact_email", "ops@example.org"),
                       ("capture.max_body_bytes", 2_000_000)):  # fmt: skip
        put = await admin.put(_api(f"/admin/settings/{key}"), json={"value": value})
        assert put.status_code == 200, put.text
    monkeypatch.setattr(tasks, "_robots", {})
    valkey = FakeValkey()
    make = await tasks.context_factory(db, valkey)
    job = JobSettings(
        source_id="s",
        kind="rss",
        rules=ExtractionRules(),
        config=RssConfig(feed_url="https://feeds.example/rss"),
    )  # type: ignore[arg-type]
    ctx = await make(job)
    assert ctx.fetcher.fetcher.user_agent == "regwatch/0.1.0 (+ops@example.org)"
    assert ctx.fetcher.fetcher.limits.max_bytes == 2_000_000  # the setting, not the default
    assert ctx.now().tzinfo is not None
    put = await admin.put(_api("/admin/settings/general.contact_email"),
                          json={"value": "other@example.org"})  # fmt: skip
    assert put.status_code == 200
    await tasks.context_factory(db, valkey)
    assert list(tasks._robots) == ["regwatch/0.1.0 (+other@example.org)"]  # finding 10

    made = (await admin.post(_api("/sources"), json=rss())).json()
    clients: list[FakeValkey] = []

    def fresh() -> FakeValkey:
        clients.append(FakeValkey())
        return clients[-1]

    from regwatch.capture.safe_fetch import SafeFetcher

    async def private(host: str, port: int) -> list[str]:
        return ["10.0.0.5"]  # answered at once, and refused: no network in tests

    monkeypatch.setattr(tasks, "_valkey", fresh)
    monkeypatch.setattr(tasks, "enqueue_run", queue)

    def hermetic(agent: str, limits: Any) -> SafeFetcher:
        return SafeFetcher(agent, limits, resolver=private)

    monkeypatch.setattr(tasks, "SafeFetcher", hermetic)
    monkeypatch.setattr(tasks, "_robots", {})  # no robots cache built on another fetcher
    assert await tasks._tick(db) >= 1
    assert await tasks._run(db, uuid.UUID(made["job"]["id"])) == "failed"
    last = (await admin.get(_api("/capture-runs"), params={"job_id": made["job"]["id"]})).json()
    assert last["items"][0]["error_class"] == "private-address"
    assert len(clients) == 2 and all(c.closed for c in clients)


async def test_an_unexpected_failure_still_ends_the_run(
    admin: httpx.AsyncClient, queue: Queue, db: AsyncSession
) -> None:
    """Run review finding 2: a store that fails ends the run as internal-error, names only the
    kind of failure, and does not count against the source."""
    made = (await admin.post(_api("/sources"), json=rss())).json()
    jid = uuid.UUID(made["job"]["id"])
    assert (await admin.post(_api(f"/capture-jobs/{jid}/run-now"))).status_code == 202
    make = _factory(_site("User-agent: *\nAllow: /\n"), {})

    async def broken(job: Any) -> Any:
        ctx = await make(job)

        async def store(key: str, body: bytes) -> None:
            raise OSError("disk full at /data/objectstore/raw/secret")

        ctx.store = store
        return ctx

    assert await runs.execute(db, jid, broken) == "failed"
    run = (await admin.get(_api("/capture-runs"), params={"job_id": str(jid)})).json()["items"][0]
    assert run["error_class"] == "internal-error" and run["error_message"] == (
        "the run failed: OSError")  # fmt: skip
    assert (await admin.get(_api(f"/sources/{made['id']}/health"))).json()["health"] == "unknown"


async def test_execute_passes_the_last_successful_run(
    admin: httpx.AsyncClient, queue: Queue, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """API feed review 1: a newer failed run does not move the incremental window."""
    from regwatch.capture import execution

    made = (await admin.post(_api("/sources"), json=rss())).json()
    jid = uuid.UUID(made["job"]["id"])
    good = datetime.now(UTC) - timedelta(days=5)
    db.add(CaptureRun(job_id=jid, status="success", started_at=good, finished_at=good))
    bad = datetime.now(UTC) - timedelta(days=1)
    db.add(CaptureRun(job_id=jid, status="failed", started_at=bad, finished_at=bad))
    db.add(CaptureRun(job_id=jid, started_at=datetime.now(UTC)))  # the run to execute
    await db.commit()
    seen: list[Any] = []

    async def recording(run_id: Any, job: Any, source: Any, make: Any,
                        last_success: Any = None) -> Any:  # fmt: skip
        seen.append(last_success)
        return execution.Outcome("success")

    monkeypatch.setattr(runs, "run_connector", recording)
    assert await runs.execute(db, jid, _factory(_site(""), {})) == "success"
    assert seen and abs((seen[0] - good).total_seconds()) < 1


async def test_the_cursor_is_saved_and_cleared_by_new_settings(
    admin: httpx.AsyncClient, queue: Queue, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CP-14: a run's cursor is kept on the job; changing the source's settings clears it."""
    from regwatch.capture import execution

    made = (await admin.post(_api("/sources"), json=rss())).json()
    jid = uuid.UUID(made["job"]["id"])
    db.add(CaptureRun(job_id=jid, started_at=datetime.now(UTC)))
    await db.commit()

    async def moved(*args: Any) -> Any:
        return execution.Outcome("partial", "truncated", "x",
                                 cursor={"publication_date": "2026-11-10"})  # fmt: skip

    monkeypatch.setattr(runs, "run_connector", moved)
    assert await runs.execute(db, jid, _factory(_site(""), {})) == "partial"
    assert (await _job(db, str(jid))).cursor == {"publication_date": "2026-11-10"}

    rename = await admin.patch(_api(f"/sources/{made['id']}"), json={"name": "Renamed"})
    assert rename.status_code == 200
    assert (await _job(db, str(jid))).cursor == {"publication_date": "2026-11-10"}  # kept
    new_feed = {"config": {"feed_url": "https://feeds.example/other"}}
    assert (await admin.patch(_api(f"/sources/{made['id']}"), json=new_feed)).status_code == 200
    assert (await _job(db, str(jid))).cursor is None  # a new query starts from its own window

    # Re-verification R1: settings saved DURING a run (from a cursor, and from none). The run
    # must not write the old query's position back over the reset.
    for start in ({"publication_date": "2026-11-10"}, None):
        await db.execute(update(CaptureJob).where(CaptureJob.id == jid).values(cursor=start))
        db.add(CaptureRun(job_id=jid, started_at=datetime.now(UTC)))
        await db.commit()
        feed = f"https://feeds.example/{'a' if start else 'b'}"

        async def edited_during(*args: Any, _start: Any = start, _feed: str = feed) -> Any:
            patch = {"config": {"feed_url": _feed}}
            assert (
                await admin.patch(_api(f"/sources/{made['id']}"), json=patch)
            ).status_code == 200
            return execution.Outcome("success", cursor={"publication_date": "2026-11-12"},
                                     cursor_from=_start)  # fmt: skip

        monkeypatch.setattr(runs, "run_connector", edited_during)
        assert await runs.execute(db, jid, _factory(_site(""), {})) == "success"
        assert (await _job(db, str(jid))).cursor is None, start


async def test_the_test_button_runs_on_a_worker(
    admin: httpx.AsyncClient, queue: Queue, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CP-13: POST /sources/{id}/test publishes capture.dry_run, and answers with what the worker
    wrote; the API itself fetches nothing, and the request is audited."""
    from regwatch.capture import dryrun
    from tests.unit.test_capture_dryrun import FakeValkey

    made = (await admin.post(_api("/sources"), json=rss())).json()
    valkey = FakeValkey()
    valkey.aclose = lambda: _none()  # type: ignore[method-assign]
    stored: dict[str, bytes] = {}

    make = _factory(_site("User-agent: *\nAllow: /\n"), stored)

    async def worker(source_id: uuid.UUID, request_id: uuid.UUID) -> None:  # runs inline here
        await dryrun.run_on_worker(db, source_id, request_id, make, valkey)

    monkeypatch.setattr(tasks, "_valkey", lambda: valkey)
    monkeypatch.setattr(tasks, "publish_dry_run", worker)
    got = await admin.post(_api(f"/sources/{made['id']}/test"))
    assert got.status_code == 200, got.text
    body = got.json()
    assert [c["url"] for c in body["candidates"]] == ["https://feeds.example/1",
                                                      "https://feeds.example/2"]  # fmt: skip
    assert body["robots_decision"] == "allowed" and stored == {}  # nothing stored
    rows = (await admin.get(_api("/admin/audit"), params={"action": "source.test"})).json()
    assert rows["total"] == 1
    missing = "00000000-0000-7000-8000-000000000000"
    assert (await admin.post(_api(f"/sources/{missing}/test"))).status_code == 404
    viewer = await _as_new_user(admin, "dt@example.org", ["viewer"])
    assert (await viewer.post(_api(f"/sources/{made['id']}/test"))).status_code == 403


async def _none() -> None:
    return None
