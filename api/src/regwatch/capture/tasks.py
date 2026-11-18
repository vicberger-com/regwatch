"""Celery tasks; names come from docs/contracts/registries.yaml (M3, ADR-0006).

Each task runs its async service with a session of its own and no connection pool kept
between tasks. ``enqueue_run`` is how the API and the tick hand a run to a worker.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

import anyio
from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture import runs
from regwatch.capture.connectors.base import ConnectorContext, JobSettings
from regwatch.capture.execution import ContextFactory
from regwatch.capture.safe_fetch import (
    CaptureFetcher,
    FetchLimits,
    FetchRefusedError,
    RobotsPolicy,
    SafeFetcher,
    ValkeyRateLimiter,
)
from regwatch.core import objectstore
from regwatch.core.db import create_engine, session_factory
from regwatch.core.settings import get_settings

SETTING_KEYS = ["capture.user_agent", "capture.max_body_bytes", "general.contact_email"]
MAX_USER_AGENT = 200
_robots: dict[str, RobotsPolicy] = {}  # per worker process and user agent: one robots cache


async def _with_session[T](work: Callable[[AsyncSession], Awaitable[T]]) -> T:
    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass_null=True)
    try:
        async with session_factory(engine)() as db:
            return await work(db)
    finally:
        await engine.dispose()


# Publishes get threads of their own, so a broker that hangs cannot take the threads password
# hashing and file reads share (scheduler review finding 2).
_PUBLISHERS = anyio.CapacityLimiter(4)
PUBLISH_DEADLINE_S = 15.0  # longer than the broker timeouts and retries together


def _send(job_id: uuid.UUID, countdown: float) -> None:
    from regwatch.core.worker import celery_app

    celery_app().send_task("capture.run_job", args=[str(job_id)], queue="capture",
                           countdown=countdown)  # fmt: skip


async def enqueue_run(job_id: uuid.UUID, countdown: float) -> None:
    """Publish ``capture.run_job`` off the event loop, within ``PUBLISH_DEADLINE_S``."""
    with anyio.fail_after(PUBLISH_DEADLINE_S):
        await anyio.to_thread.run_sync(_send, job_id, countdown, limiter=_PUBLISHERS,
                                       abandon_on_cancel=True)  # fmt: skip


def user_agent(template: str, contact: str) -> str:
    """``capture.user_agent`` with ``{version}`` and ``{contact_email}`` filled in, as printable
    ASCII; without a contact address the ``(+...)`` part is left out."""
    from importlib.metadata import version

    text = template.replace("{version}", version("regwatch"))
    text = text.replace("(+{contact_email})", f"(+{contact})" if contact else "")
    text = text.replace("{contact_email}", contact)
    text = "".join(c for c in text if " " <= c <= "~")
    return " ".join(text.split())[:MAX_USER_AGENT] or "regwatch"


MIN_BODY = 64 * 1024
MAX_BODY = 50 * 1024 * 1024


def body_cap(value: Any) -> int:
    """``capture.max_body_bytes`` within 64 KiB to 50 MiB: zero would fail every run and a huge
    value would let one body exhaust a worker (finding 8)."""
    try:
        wanted = int(value)
    except (TypeError, ValueError):
        wanted = 10 * 1024 * 1024
    return min(max(wanted, MIN_BODY), MAX_BODY)


def _valkey() -> Any:
    import redis.asyncio as aioredis

    from regwatch.core.worker import BROKER_TIMEOUT_S, broker_url

    return aioredis.Redis.from_url(broker_url(get_settings()), socket_timeout=BROKER_TIMEOUT_S,
                                   socket_connect_timeout=BROKER_TIMEOUT_S)  # fmt: skip


OFFICIAL_KINDS = ("rss", "web_page", "web_crawl", "api_feed")
URL_FIELDS = ("feed_url", "page_url", "seed_urls", "endpoint_url")
PACE_MAX_WAIT_S = 120.0  # a query waits at most 2 minutes for its turn, in a worker process


async def _search_context(db: AsyncSession) -> tuple[Any, frozenset[str]]:
    """The search client, when the ``search.internet`` flag is on and ``search.provider`` is
    ``searxng`` (ADR-0010), and the hosts of enabled official sources (the official domains
    the search connector marks results by; ASSUMPTIONS)."""
    from sqlalchemy import select

    from regwatch.admin.models import FeatureFlag
    from regwatch.admin.services import values
    from regwatch.capture.models import Source
    from regwatch.core.internal import InternalClient

    flag = await db.scalar(select(FeatureFlag.enabled).where(FeatureFlag.key == "search.internet"))
    provider = (await values(db, ["search.provider"]))["search.provider"]
    client = (InternalClient(str(get_settings().search_url))
              if flag and provider == "searxng" else None)  # fmt: skip
    # Only sources whose addresses an admin chose: never search or manual sources, and only
    # their URL fields (search review finding 4).
    rows = await db.execute(select(Source.url, Source.config)
                            .where(Source.enabled, Source.credibility == "official",
                                   Source.kind.in_(OFFICIAL_KINDS)))  # fmt: skip
    hosts: set[str] = set()
    for url, config in rows:
        fields = [(config or {}).get(name) for name in URL_FIELDS]
        for value in [url, *fields]:
            for one in value if isinstance(value, list) else [value]:
                if isinstance(one, str) and one.startswith(("http://", "https://")):
                    host = urlsplit(one).hostname
                    if host:
                        hosts.add(host.lower())
    return client, frozenset(hosts)


async def context_factory(db: AsyncSession, valkey: Any) -> ContextFactory:
    """The real fetcher and store for runs, from the capture settings."""
    from datetime import UTC, datetime

    from regwatch.admin.services import values

    settings = await values(db, SETTING_KEYS)
    agent = user_agent(str(settings["capture.user_agent"]), str(settings["general.contact_email"]))
    limits = FetchLimits(max_bytes=body_cap(settings["capture.max_body_bytes"]))
    fetcher = SafeFetcher(agent, limits)
    if agent not in _robots:  # a new user agent: the old cache is of no further use (finding 10)
        _robots.clear()
        _robots[agent] = RobotsPolicy(fetcher)
    robots = _robots[agent]
    limiter = ValkeyRateLimiter(valkey)
    search, official = await _search_context(db)

    async def pace(key: str, interval_s: float, max_wait_s: float = PACE_MAX_WAIT_S) -> None:
        """One slot at a time per key across every worker, through the Valkey limiter; no slot
        is reserved when the wait would be longer than ``max_wait_s``."""
        wait = await limiter.take(f"internal:{key}", interval_s, max_wait_s)
        if wait is None:  # a skip, not a failure: it never counts against health (search R1)
            busy = "the search queue is busy; the next run tries"
            raise FetchRefusedError("rate-limited", busy)
        await asyncio.sleep(wait)

    async def make(job: JobSettings) -> ConnectorContext:
        capture = CaptureFetcher(fetcher, limiter, robots=robots,
                                 rate_per_minute=job.rate_per_minute)  # fmt: skip
        return ConnectorContext(fetcher=capture, store=objectstore.put, load=objectstore.get,
                                now=lambda: datetime.now(UTC), search=search,
                                official_hosts=official, pace=pace)  # fmt: skip

    return make


async def _run(db: AsyncSession, job_id: uuid.UUID) -> str | None:
    valkey = _valkey()
    try:
        return await runs.execute(db, job_id, await context_factory(db, valkey))
    finally:
        await valkey.aclose()


async def _tick(db: AsyncSession) -> int:
    valkey = _valkey()

    async def backlog() -> int:
        return int(await valkey.llen("capture"))

    try:
        return await runs.tick(db, enqueue_run, backlog=backlog)
    finally:
        await valkey.aclose()


def _send_dry_run(source_id: uuid.UUID, request_id: uuid.UUID) -> None:
    from regwatch.capture.dryrun import WAIT_S
    from regwatch.core.worker import celery_app

    # Expires when the API stops waiting: a queued test nobody waits for is dropped (finding 3).
    celery_app().send_task("capture.dry_run", args=[str(source_id), str(request_id)],
                           queue="capture", expires=WAIT_S)  # fmt: skip


async def publish_dry_run(source_id: uuid.UUID, request_id: uuid.UUID) -> None:
    """Publish ``capture.dry_run`` off the event loop, within ``PUBLISH_DEADLINE_S`` (CP-13)."""
    with anyio.fail_after(PUBLISH_DEADLINE_S):
        await anyio.to_thread.run_sync(_send_dry_run, source_id, request_id,
                                       limiter=_PUBLISHERS, abandon_on_cancel=True)  # fmt: skip


async def _dry_run(db: AsyncSession, source_id: uuid.UUID, request_id: uuid.UUID) -> None:
    from regwatch.capture import dryrun

    valkey = _valkey()
    try:
        try:
            factory = await context_factory(db, valkey)
        except Exception as exc:  # noqa: BLE001 - let run_on_worker answer it (re-verification R5)
            failure = exc

            async def factory(job: JobSettings) -> ConnectorContext:
                raise failure

        await dryrun.run_on_worker(db, source_id, request_id, factory, valkey)
    finally:
        await valkey.aclose()


@shared_task(name="capture.dry_run")
def dry_run(source_id: str, request_id: str) -> None:
    asyncio.run(_with_session(
        lambda db: _dry_run(db, uuid.UUID(source_id), uuid.UUID(request_id))))  # fmt: skip


@shared_task(name="capture.schedule_tick")
def schedule_tick() -> int:
    return asyncio.run(_with_session(_tick))


@shared_task(name="capture.run_job")
def run_job(job_id: str) -> str | None:
    return asyncio.run(_with_session(lambda db: _run(db, uuid.UUID(job_id))))


@shared_task(name="capture.health_check")
def health_check() -> int:
    return asyncio.run(_with_session(runs.sweep))
