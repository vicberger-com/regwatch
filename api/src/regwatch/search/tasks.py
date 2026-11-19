"""Celery tasks; names come from docs/contracts/registries.yaml.

``search.index_items`` writes the index documents of items that changed (ADR-0011): the M4
pipeline, reprocessing and tag changes queue it after their commit.

``search.index_matching`` serves the admin changes that alter documents (BL-120): a source's
credibility, a jurisdiction's region, a term's key, a term merge. The API publishes only the
changed object; the worker selects its items, or rebuilds everything above
``FULL_REINDEX_OVER``. Requests for one object coalesce while one is pending (a Valkey key), so
toggling a setting queues one task, not one per toggle (review finding 1).

``search.reindex`` rebuilds every document from PostgreSQL: nightly through beat, as the
catch-up for anything missed, and in the foreground with ``python -m regwatch.search.tasks``.
At most one rebuild runs at a time (a PostgreSQL advisory lock); another exits at once.

All of them do nothing while the index is not configured, so search stays on PostgreSQL.
"""

from __future__ import annotations

import uuid

import anyio
import structlog
from celery import shared_task
from sqlalchemy import ColumnElement, func, or_, select

from regwatch.core.db import create_engine, session_factory
from regwatch.core.settings import get_settings
from regwatch.processing.models import ChangeEvent, Item, ItemJurisdiction, ItemTerm
from regwatch.search import index

MAX_IDS = 2000  # one task; more are split
FULL_REINDEX_OVER = 50_000  # an admin change touching more items rebuilds everything instead
REBUILD_LOCK = 0x5EA2C4  # one rebuild at a time; no other code takes this advisory lock
PENDING_S = 900  # a pending request for one object coalesces the next ones for this long
KINDS = ("source", "jurisdiction", "term")
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
    """Every document, unless another rebuild holds the lock (then 0)."""
    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass_null=True)
    try:
        async with session_factory(engine)() as db:
            if not await db.scalar(select(func.pg_try_advisory_xact_lock(REBUILD_LOCK))):
                _log.info("reindex_skipped", reason="a rebuild is running")
                return 0
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


def _send_matching(kind: str, key: str) -> None:
    from regwatch.core.worker import celery_app

    celery_app().send_task("search.index_matching", args=[kind, key], queue="process")


def _pending(kind: str, key: str) -> str:
    return f"regwatch:search:pending:{kind}:{key}"


def _conditions(kind: str, key: uuid.UUID) -> list[ColumnElement[bool]]:
    if kind == "source":
        return [Item.source_id == key]
    if kind == "jurisdiction":
        return [Item.id.in_(select(ItemJurisdiction.item_id)
                            .where(ItemJurisdiction.jurisdiction_id == key)),
                Item.id.in_(select(ChangeEvent.item_id)
                            .where(ChangeEvent.jurisdiction_id == key))]  # fmt: skip
    return [Item.id.in_(select(ItemTerm.item_id).where(ItemTerm.term_id == key))]


async def _index_matching(kind: str, key: uuid.UUID) -> int:
    from regwatch.capture.tasks import _valkey

    client = _valkey()
    try:  # changes from now on queue a new task
        await client.delete(_pending(kind, str(key)))
    finally:
        await client.aclose()
    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass_null=True)
    try:
        async with session_factory(engine)() as db:
            ids = list((await db.scalars(select(Item.id).where(or_(*_conditions(kind, key)))
                                         .limit(FULL_REINDEX_OVER + 1))).all())  # fmt: skip
            if len(ids) <= FULL_REINDEX_OVER:
                writer = index.IndexClient()
                await index.ensure(writer)
                return await index.index_items(db, ids, writer)
    finally:
        await engine.dispose()
    return await _reindex()


@shared_task(name="search.index_matching", queue="process")  # type: ignore[untyped-decorator]
def index_matching(kind: str, key: str) -> None:
    if kind in KINDS and index.configured():
        _log.info("indexed_matching", kind=kind, items=anyio.run(_index_matching, kind,
                                                                 uuid.UUID(key)))  # fmt: skip


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


async def queue_matching(kind: str, key: uuid.UUID) -> None:
    """After an admin change's commit (BL-120): one ``search.index_matching`` for the changed
    source, jurisdiction or term, unless one is already pending; never fails the caller (the
    nightly rebuild catches up)."""
    if kind not in KINDS or not index.configured():
        return
    from regwatch.capture.tasks import PUBLISH_DEADLINE_S, _valkey

    try:
        with anyio.fail_after(PUBLISH_DEADLINE_S):
            client = _valkey()
            try:
                fresh = await client.set(_pending(kind, str(key)), "1", nx=True, ex=PENDING_S)
            finally:
                await client.aclose()
            if fresh:
                try:
                    await anyio.to_thread.run_sync(_send_matching, kind, str(key),
                                                   limiter=_PUBLISHERS,
                                                   abandon_on_cancel=True)  # fmt: skip
                except BaseException:  # nothing was queued: let the next change try
                    retry = _valkey()
                    try:
                        await retry.delete(_pending(kind, str(key)))
                    finally:
                        await retry.aclose()
                    raise
    except Exception as exc:  # noqa: BLE001 - indexing never fails the change itself
        _log.warning("index_queue_failed", error=type(exc).__name__, kind=kind)


if __name__ == "__main__":  # pragma: no cover - the operator's foreground reindex
    print(f"reindexed {anyio.run(_reindex)} items")
