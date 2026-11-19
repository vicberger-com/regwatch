"""The OpenSearch index (ADR-0011, CP-22): the client, the mapping and item documents."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.settings import get_settings
from regwatch.processing.models import Item
from regwatch.processing.pipeline import process_manifest
from regwatch.search import index
from tests.integration.conftest import OpenSearch, opensearch
from tests.integration.test_admin import admin
from tests.integration.test_auth import clear_limits, db_url
from tests.integration.test_capture_runs import db
from tests.integration.test_processing_pipeline import BSI, loader, made_source, manifest
from tests.integration.test_sources import fixed_dns

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db", "db_url", "fixed_dns", "opensearch"]


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
