"""Search and map activity on the OpenSearch index (ADR-0011): the same meaning as PostgreSQL."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.settings import get_settings
from regwatch.processing.models import Item
from regwatch.search import index
from tests.integration.conftest import OpenSearch, opensearch
from tests.integration.test_admin import _api, admin
from tests.integration.test_auth import clear_limits, db_url
from tests.integration.test_capture_runs import db
from tests.integration.test_search import TAG, clear_search_rate, corpus
from tests.integration.test_sources import fixed_dns

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "clear_search_rate", "db", "db_url", "fixed_dns",
           "opensearch"]  # fmt: skip


@pytest.fixture
async def indexed(opensearch: OpenSearch, db_url: str,
                  monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[OpenSearch]:  # fmt: skip
    for key, value in (("REGWATCH_INDEX_URL", opensearch.url),
                       ("REGWATCH_INDEX_PASSWORD", opensearch.password),
                       ("REGWATCH_INDEX_CA_B64", opensearch.ca_b64)):  # fmt: skip
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    # Each test's database is new; so is its index (one node serves the whole session).
    await index.IndexClient().call("DELETE", f"/{index.INDEX}", allow=(404,))
    yield opensearch
    get_settings.cache_clear()


async def indexed_corpus(admin: httpx.AsyncClient, db: AsyncSession) -> str:
    sid = await corpus(admin, db)
    ids = list((await db.scalars(select(Item.id).where(Item.source_id == uuid.UUID(sid)))).all())
    client = index.IndexClient()
    await index.ensure(client)
    await index.index_items(db, ids, client)
    await client.call("POST", f"/{index.ALIAS}/_refresh")
    return sid


async def test_more_of_the_words_rank_first_on_the_index(
    indexed: OpenSearch, admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Acceptance 1 through the index."""
    await indexed_corpus(admin, db)
    got = (await admin.post(_api("/search"), json={"q": f"{TAG} NIS2 incident"})).json()
    titles = [i["title"] for i in got["items"]]
    assert titles[0].endswith("NIS2 incident reporting guidance") and got["total"] == 3
    assert "<mark>NIS2</mark>" in got["items"][0]["highlights"]["title"][0]
    assert {f["key"]: f["count"] for f in got["facets"]["jurisdiction"]} == {"DE": 3}
    phrase = (await admin.post(_api("/search"), json={"q": f'{TAG} "incident reporting"'})).json()
    assert [i["title"] for i in phrase["items"]] == [f"{TAG} NIS2 incident reporting guidance"]
    excluded = (await admin.post(_api("/search"), json={"q": f"{TAG} NIS2 -guidance"})).json()
    assert [i["title"] for i in excluded["items"]] == [f"{TAG} NIS2 scope clarified"]


async def test_filters_on_the_index(
    indexed: OpenSearch, admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    sid = await indexed_corpus(admin, db)
    soon = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    for filters, expected in [({"sources": [sid]}, 3), ({"sources": [str(uuid.uuid4())]}, 0),
                              ({"jurisdictions": ["de"]}, 3), ({"regions": ["150"]}, 3),
                              ({"regions": ["142"]}, 0), ({"severity": ["info"]}, 3),
                              ({"severity": ["major"]}, 0), ({"credibility": ["news"]}, 0),
                              ({"changed": {"from": soon}}, 0),
                              ({"status": ["new"]}, 3)]:  # fmt: skip
        got = await admin.post(_api("/search"), json={"q": TAG, "filters": filters})
        assert got.status_code == 200 and got.json()["total"] == expected, filters
    bad = await admin.post(_api("/search"), json={"filters": {"terms": {"nope": ["x"]}}})
    assert bad.status_code == 400  # facets are checked before the index is asked


async def test_the_map_from_the_index_sums_to_the_search_total(
    indexed: OpenSearch, admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Acceptance 2 through the index."""
    sid = await indexed_corpus(admin, db)
    raw = quote(json.dumps({"sources": [sid]}))
    rows = (await admin.get(_api(f"/map/activity?filters={raw}"))).json()["rows"]
    assert [(r["code"], r["count"], r["max_severity"]) for r in rows] == [("DE", 3, "info")]
    since = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    europe = {"sources": [sid], "regions": ["150"], "changed": {"from": since}}
    total = (await admin.post(_api("/search"), json={"filters": europe})).json()["total"]
    assert total == sum(r["count"] for r in rows)
    regions = (await admin.get(_api(f"/map/activity?view_by=region&filters={raw}"))).json()
    assert {r["code"] for r in regions["rows"]} == {"155"}


async def test_an_unreachable_index_falls_back_to_postgresql(
    indexed: OpenSearch,
    admin: httpx.AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await corpus(admin, db)  # not indexed
    monkeypatch.setenv("REGWATCH_INDEX_URL", "https://localhost:1")
    get_settings.cache_clear()
    got = await admin.post(_api("/search"), json={"q": TAG})
    assert got.status_code == 200 and got.json()["total"] == 3
