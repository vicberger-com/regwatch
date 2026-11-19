"""The OpenSearch index (ADR-0011, CP-22): the client, the mapping and item documents."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.settings import get_settings
from regwatch.processing.models import Item
from regwatch.processing.pipeline import process_manifest
from regwatch.search import index
from tests.integration.conftest import OpenSearch, opensearch
from tests.integration.test_admin import _api, admin
from tests.integration.test_auth import clear_limits, db_url
from tests.integration.test_capture_runs import db
from tests.integration.test_processing_pipeline import BSI, loader, made_source, manifest
from tests.integration.test_sources import fixed_dns
from tests.integration.test_valkey_rate import valkey

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db", "db_url", "fixed_dns", "opensearch", "valkey"]


@pytest.fixture
def index_env(opensearch: OpenSearch, db_url: str,
              monkeypatch: pytest.MonkeyPatch) -> Iterator[OpenSearch]:  # fmt: skip
    monkeypatch.setenv("REGWATCH_INDEX_URL", opensearch.url)
    monkeypatch.setenv("REGWATCH_INDEX_PASSWORD", opensearch.password)
    monkeypatch.setenv("REGWATCH_INDEX_CA_B64", opensearch.ca_b64)
    get_settings.cache_clear()
    yield opensearch
    get_settings.cache_clear()


async def test_items_are_indexed_from_postgresql_and_removed_with_them(
    index_env: OpenSearch, admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    sid = await made_source(admin)
    tag = uuid.uuid4().hex[:8]
    rows = [{"url": f"https://example.org/{tag}/{n}", "text": f"{n}. " + BSI,
             "title": f"{tag} Regel {n}", "summary": "Pflichten für Betreiber"}
            for n in range(3)]  # fmt: skip
    key, objects = manifest(sid, uuid.uuid4(), rows)
    await process_manifest(db, key, loader(objects))
    ids = list((await db.scalars(select(Item.id).where(Item.source_id == uuid.UUID(sid)))).all())
    client, reader = index_env.indexer(), index.IndexClient()
    await index.ensure(client)
    await index.ensure(client)  # idempotent
    assert await index.index_items(db, ids, client) == 3
    await client.call("POST", f"/{index.ALIAS}/_refresh")
    found = await reader.call("POST", f"/{index.ALIAS}/_search", {
        "query": {"term": {"source_id": sid}}, "size": 10})  # fmt: skip
    docs = {h["_id"]: h["_source"] for h in found["hits"]["hits"]}
    assert set(docs) == {str(i) for i in ids}
    one = next(iter(docs.values()))
    assert one["jurisdictions"] == ["DE"] and one["regions"] == ["155"]
    assert one["events"] and one["events"][0]["severity"] == "info"
    assert one["credibility"] == "official" and one["language"] == "de"
    await db.execute(delete(Item).where(Item.id == ids[0]))
    await db.commit()
    await index.index_items(db, ids, client)
    await client.call("POST", f"/{index.ALIAS}/_refresh")
    count = await reader.call("POST", f"/{index.ALIAS}/_count",
                              {"query": {"term": {"source_id": sid}}})  # fmt: skip
    assert count["count"] == 2


async def test_the_client_names_its_paths_and_trusts_only_the_stacks_ca(
    index_env: OpenSearch, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = index.IndexClient()
    with pytest.raises(ValueError):
        await client.call("GET", "/_cat/indices")
    with pytest.raises(ValueError):
        await client.call("DELETE", "/other-index")
    other_ca = index_env.ca_b64[:-8] + "AAAAAAA="  # not the stack's CA
    monkeypatch.setenv("REGWATCH_INDEX_CA_B64", other_ca)
    get_settings.cache_clear()
    with pytest.raises((index.IndexFailedError, ValueError, Exception)):
        await index.IndexClient().call("GET", "/_cluster/health")
    monkeypatch.setenv("REGWATCH_INDEX_URL", index_env.url.replace("https://", "http://"))
    monkeypatch.setenv("REGWATCH_INDEX_CA_B64", index_env.ca_b64)
    get_settings.cache_clear()
    with pytest.raises(index.IndexFailedError):
        index.IndexClient()
    monkeypatch.setenv("REGWATCH_INDEX_URL", index_env.url)
    monkeypatch.setenv("REGWATCH_INDEX_PASSWORD", "wrong")
    get_settings.cache_clear()
    with pytest.raises(index.IndexFailedError) as refused:
        await index.IndexClient().call("GET", "/_cluster/health")
    assert refused.value.detail == "the index answered HTTP 401"


async def test_the_api_reads_and_only_the_worker_writes(index_env: OpenSearch) -> None:
    """Review finding 2: two least-privilege users, and neither may delete an index."""
    writer, reader = index_env.indexer(), index.IndexClient()
    await index.ensure(writer)
    doc = index.bulk_body({uuid.uuid4(): {"title": "x", "summary": "y", "events": []}}, [])

    async def status(client: index.IndexClient, method: str, path: str, **kw: object) -> int:
        try:
            await client.call(method, path, **kw)  # type: ignore[arg-type]
        except index.IndexFailedError as exc:
            assert exc.reason in ("index-auth", "index-status")
            return int(exc.detail.rsplit(" ", 1)[1])
        return 200

    assert await status(reader, "POST", f"/{index.ALIAS}/_search", body={"size": 0}) == 200
    assert await status(reader, "POST", f"/{index.INDEX}/_bulk", ndjson=doc) == 403
    assert await status(reader, "PUT", f"/{index.INDEX}/_settings",
                        body={"index": {"refresh_interval": "1s"}}) == 403  # fmt: skip
    assert await status(reader, "DELETE", f"/{index.INDEX}") == 403
    assert await status(writer, "POST", f"/{index.INDEX}/_bulk", ndjson=doc) == 200
    assert await status(writer, "POST", f"/{index.ALIAS}/_search", body={"size": 0}) == 403
    assert await status(writer, "DELETE", f"/{index.INDEX}") == 403
    await index.bulk_mode(writer, True)
    await index.bulk_mode(writer, False)
    index_env.wipe(index.INDEX)


async def test_without_an_index_nothing_is_queued(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from regwatch.search import tasks

    sent: list[object] = []
    monkeypatch.setattr(tasks, "_send", sent.append)
    monkeypatch.delenv("REGWATCH_INDEX_URL", raising=False)
    get_settings.cache_clear()
    await tasks.queue_index([uuid.uuid4()])
    assert sent == []


async def test_admin_changes_that_alter_documents_queue_them(
    valid_env: dict[str, str],
    admin: httpx.AsyncClient,
    db: AsyncSession,
    valkey: Any,  # noqa: ANN401 - redis.asyncio.Redis
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BL-120: credibility, a region, a term key and a merge reach the index, one coalesced task
    per changed object (review finding 1); the worker selects the items, and above
    FULL_REINDEX_OVER rebuilds everything, one rebuild at a time."""
    from regwatch.search import tasks
    from regwatch.taxonomy.models import Jurisdiction, Term

    for key, value in (("REGWATCH_INDEX_URL", "https://index:9200"),
                       ("REGWATCH_INDEX_PASSWORD", "unused"),
                       ("REGWATCH_INDEX_CA_B64", "dW51c2Vk"),
                       ("REGWATCH_QUEUE_URL", "valkey://127.0.0.1:"
                        f"{valkey.connection_pool.connection_kwargs['port']}/0")):  # fmt: skip
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(tasks, "_send_matching", lambda kind, key: sent.append((kind, key)))
    monkeypatch.setattr(tasks, "queue_index", _nothing)  # the tag edit below: not under test
    sid = await made_source(admin)
    rows = [{"url": f"https://example.org/bl120/{n}", "text": f"{n}. " + BSI,
             "title": f"Regel {n}", "summary": "Pflichten"} for n in range(2)]  # fmt: skip
    key, objects = manifest(sid, uuid.uuid4(), rows)
    await process_manifest(db, key, loader(objects))
    ids = set((await db.scalars(select(Item.id).where(Item.source_id == uuid.UUID(sid)))).all())
    de = await db.scalar(select(Jurisdiction.id).where(Jurisdiction.code == "DE"))
    term = await db.scalar(select(Term).where(Term.active.is_(True), Term.parent_id.is_(None))
                           .order_by(Term.key).limit(1))  # fmt: skip
    assert term is not None and de is not None and len(ids) == 2
    other = await db.scalar(select(Term.id).where(
        Term.facet_id == term.facet_id, Term.id != term.id, Term.active.is_(True)))  # fmt: skip
    term_id, term_key, item = term.id, term.key, next(iter(ids))
    await db.rollback()
    for kind, key in (("source", sid), ("jurisdiction", str(de)), ("term", str(term_id)),
                      ("term", str(other))):  # fmt: skip
        await _clear_pending(tasks, kind, key)

    await admin.patch(_api(f"/sources/{sid}"), json={"name": "renamed only"})
    assert sent == []  # nothing in the documents changed
    for credibility in ("secondary", "official", "secondary"):  # toggled: one task
        await admin.patch(_api(f"/sources/{sid}"), json={"credibility": credibility})
    assert sent == [("source", sid)]
    assert (await admin.patch(_api("/jurisdictions/DE"),
                              json={"region_code": "151"})).status_code == 200  # fmt: skip
    assert sent[-1] == ("jurisdiction", str(de))
    tagged = await admin.put(_api(f"/items/{item}/tags"), json={"add_term_ids": [str(term_id)]})
    assert tagged.status_code == 200
    assert (await admin.patch(_api(f"/taxonomy/terms/{term_id}"),
                              json={"key": f"{term_key}-renamed"})).status_code == 200  # fmt: skip
    assert sent[-1] == ("term", str(term_id))
    merged = await admin.post(_api(f"/taxonomy/terms/{term_id}/merge"),
                              json={"into_term_id": str(other)})  # fmt: skip
    assert merged.status_code == 200 and sent[-1] == ("term", str(other))

    # The worker: the items of the object, or a rebuild above the threshold, never two at once.
    written: list[set[uuid.UUID]] = []
    rebuilt: list[bool] = []

    async def fake_items(_db: object, got: list[uuid.UUID], _c: object = None) -> int:
        written.append(set(got))
        return len(got)

    async def fake_ensure(_c: object) -> None:
        return None

    async def fake_rebuild(_db: object, _c: object) -> int:
        rebuilt.append(True)
        return 0

    async def fake_bulk(_c: object, _on: bool) -> None:
        return None

    monkeypatch.setattr(index, "IndexClient", lambda: object())
    for name, fake in (("index_items", fake_items), ("ensure", fake_ensure),
                       ("rebuild", fake_rebuild), ("bulk_mode", fake_bulk)):  # fmt: skip
        monkeypatch.setattr(index, name, fake)
    monkeypatch.setenv("REGWATCH_DATABASE_URL", db_url)
    get_settings.cache_clear()
    assert await tasks._index_matching("source", uuid.UUID(sid)) == 2 and written == [ids]
    monkeypatch.setattr(tasks, "FULL_REINDEX_OVER", 0)
    await tasks._index_matching("source", uuid.UUID(sid))
    assert rebuilt == [True]
    async with db.bind.connect() as other_session:  # type: ignore[union-attr]
        async with other_session.begin():
            await other_session.execute(select(func.pg_advisory_xact_lock(tasks.REBUILD_LOCK)))
            assert await tasks._reindex() == 0  # another rebuild holds the lock
    assert rebuilt == [True]


async def _nothing(_ids: object) -> None:
    return None


async def _clear_pending(tasks: object, kind: str, key: str) -> None:
    from regwatch.capture.tasks import _valkey

    client = _valkey()
    try:
        await client.delete(tasks._pending(kind, key))  # type: ignore[attr-defined]
    finally:
        await client.aclose()
