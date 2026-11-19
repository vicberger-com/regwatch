"""Celery tasks; names come from docs/contracts/registries.yaml.

``search.index_items`` writes the index documents of items that changed (ADR-0011): the M4
pipeline, reprocessing and tag changes queue it after their commit, and so do the admin changes
that alter documents (BL-120): a source's credibility, a jurisdiction's region, a term's key, a
term merge. ``search.reindex`` rebuilds every document from PostgreSQL: nightly through beat, as
the catch-up for anything missed, and in the foreground with ``python -m regwatch.search.tasks``.
Both do nothing while the index is not configured, so search stays on PostgreSQL.
"""

from __future__ import annotations

import uuid

import anyio
import structlog
from celery import shared_task
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.db import create_engine, session_factory
from regwatch.core.settings import get_settings
from regwatch.processing.models import Item
from regwatch.search import index

MAX_IDS = 2000  # one task; more are split
FULL_REINDEX_OVER = 50_000  # an admin change touching more items queues a full rebuild instead
_PUBLISHERS = anyio.CapacityLimiter(4)
_log = structlog.get_logger(__name__)


async def _index(ids: list[uuid.UUID]) -> int:
    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass_null=True)
    try:
        async with session_factory(engine)() as db:
            client = index.IndexClient()
            await index.ensure(client)
            return await index.index_items(db, ids, client)
    finally:
        await engine.dispose()


@shared_task(name="search.index_items", queue="process")  # type: ignore[untyped-decorator]
def index_items(item_ids: list[str]) -> None:
    if not index.configured():
        return
    ids = [uuid.UUID(i) for i in item_ids[:MAX_IDS]]
    anyio.run(_index, ids)


async def _reindex() -> int:
    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass_null=True)
    try:
        async with session_factory(engine)() as db:
            client = index.IndexClient()
            await index.ensure(client)
            await index.bulk_mode(client, True)
            try:
                return await index.rebuild(db, client)
            finally:
                await index.bulk_mode(client, False)
    finally:
        await engine.dispose()


@shared_task(name="search.reindex", queue="process")  # type: ignore[untyped-decorator]
def reindex() -> None:
    if index.configured():
        _log.info("reindexed", items=anyio.run(_reindex))


def _send(item_ids: list[str]) -> None:
    from regwatch.core.worker import celery_app

    celery_app().send_task("search.index_items", args=[item_ids], queue="process")


def _send_reindex() -> None:
    from regwatch.core.worker import celery_app

    celery_app().send_task("search.reindex", queue="process")


async def queue_index(ids: list[uuid.UUID]) -> None:
    """After a commit: queue the documents of ``ids``; never fails the caller (the next change
    or a reindex catches up)."""
    if not ids or not index.configured():
        return
    from regwatch.capture.tasks import PUBLISH_DEADLINE_S

    unique = list(dict.fromkeys(str(i) for i in ids))
    try:
        for at in range(0, len(unique), MAX_IDS):
            with anyio.fail_after(PUBLISH_DEADLINE_S):
                chunk = unique[at : at + MAX_IDS]
                await anyio.to_thread.run_sync(_send, chunk, limiter=_PUBLISHERS,
                                               abandon_on_cancel=True)  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - indexing never fails the change itself
        _log.warning("index_queue_failed", error=type(exc).__name__, items=len(unique))


async def queue_matching(db: AsyncSession, *conditions: ColumnElement[bool]) -> None:
    """After an admin change's commit (BL-120): queue the documents of the items matching any of
    ``conditions``, or one full rebuild when there are more than ``FULL_REINDEX_OVER``; never
    fails the caller (the nightly rebuild catches up)."""
    if not conditions or not index.configured():
        return
    from regwatch.capture.tasks import PUBLISH_DEADLINE_S

    try:
        ids = list((await db.scalars(select(Item.id).where(or_(*conditions))
                                     .limit(FULL_REINDEX_OVER + 1))).all())  # fmt: skip
        await db.commit()  # end the read (a rollback would expire the caller's objects)
        if len(ids) <= FULL_REINDEX_OVER:
            await queue_index(ids)
            return
        with anyio.fail_after(PUBLISH_DEADLINE_S):
            await anyio.to_thread.run_sync(_send_reindex, limiter=_PUBLISHERS,
                                           abandon_on_cancel=True)  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - indexing never fails the change itself
        _log.warning("index_queue_failed", error=type(exc).__name__)


if __name__ == "__main__":  # pragma: no cover - the operator's foreground reindex
    print(f"reindexed {anyio.run(_reindex)} items")
