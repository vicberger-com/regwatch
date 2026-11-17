"""Celery tasks; names come from docs/contracts/registries.yaml (M3, ADR-0006).

Each task runs its async service with a session of its own and no connection pool kept
between tasks. ``enqueue_run`` is how the API and the tick hand a run to a worker.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable

import anyio
from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture import runs
from regwatch.core.db import create_engine, session_factory
from regwatch.core.settings import get_settings


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


@shared_task(name="capture.schedule_tick")
def schedule_tick() -> int:
    return asyncio.run(_with_session(lambda db: runs.tick(db, enqueue_run)))


@shared_task(name="capture.run_job")
def run_job(job_id: str) -> str | None:
    return asyncio.run(_with_session(lambda db: runs.execute(db, uuid.UUID(job_id))))


@shared_task(name="capture.health_check")
def health_check() -> int:
    return asyncio.run(_with_session(runs.sweep))
