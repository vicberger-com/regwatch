"""Celery tasks; names come from docs/contracts/registries.yaml.

``process.extract`` takes the run manifest's object store key as its ``raw_document_ref``: a
capture run hands its whole manifest over once it has ended (M3 writes one per run).
"""

from __future__ import annotations

import uuid

import anyio
from celery import shared_task

from regwatch.core import objectstore
from regwatch.core.db import create_engine, session_factory
from regwatch.core.settings import get_settings
from regwatch.processing.pipeline import process_manifest, reprocess_item, sweep


async def _process(key: str) -> None:
    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass_null=True)
    try:
        async with session_factory(engine)() as db:
            await process_manifest(db, key, objectstore.get, objectstore.put)
    finally:
        await engine.dispose()


@shared_task(name="process.extract", queue="process")  # type: ignore[untyped-decorator]
def extract(raw_document_ref: str) -> None:
    anyio.run(_process, raw_document_ref)


async def _reprocess(item_id: str) -> None:
    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass_null=True)
    try:
        async with session_factory(engine)() as db:
            await reprocess_item(db, uuid.UUID(item_id))
    finally:
        await engine.dispose()


@shared_task(name="process.reprocess_item", queue="process")  # type: ignore[untyped-decorator]
def reprocess(item_id: str) -> None:
    anyio.run(_reprocess, item_id)


def enqueue_reprocess(item_id: str) -> None:
    """Queue ``process.reprocess_item`` (``POST /items/{id}/reprocess``)."""
    from regwatch.core.worker import celery_app

    celery_app().send_task("process.reprocess_item", args=[item_id], queue="process")


_PUBLISHERS = anyio.CapacityLimiter(4)


async def publish_reprocess(item_id: uuid.UUID) -> None:
    """``enqueue_reprocess`` off the event loop, as ``capture.tasks.enqueue_run`` publishes: its
    own threads and a deadline, so a hanging broker never holds the threads object store reads
    and diffs share (routes review finding 4)."""
    from regwatch.capture.tasks import PUBLISH_DEADLINE_S

    with anyio.fail_after(PUBLISH_DEADLINE_S):
        await anyio.to_thread.run_sync(enqueue_reprocess, str(item_id), limiter=_PUBLISHERS,
                                       abandon_on_cancel=True)  # fmt: skip


async def _sweep() -> int:
    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass_null=True)
    try:
        async with session_factory(engine)() as db:

            async def hand_over(key: str) -> None:
                await anyio.to_thread.run_sync(enqueue, key)

            return await sweep(db, objectstore.get, hand_over, store=objectstore.put)
    finally:
        await engine.dispose()


def sweep_unprocessed() -> int:
    """Run from the hourly ``capture.health_check``: manifests never processed."""
    return anyio.run(_sweep)


def enqueue(manifest_key: str) -> None:
    """Hand a run's manifest to the process queue."""
    from regwatch.core.worker import celery_app

    celery_app().send_task("process.extract", args=[manifest_key], queue="process")
