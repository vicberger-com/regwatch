"""GET /map/activity (M5 interfaces; acceptance 2)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.processing.models import ChangeEvent, Item
from regwatch.processing.pipeline import reprocess_item
from tests.integration.test_admin import _api, admin
from tests.integration.test_auth import ORIGIN, clear_limits, db_url
from tests.integration.test_capture_runs import db
from tests.integration.test_processing_classify import term
from tests.integration.test_search import TAG, clear_search_rate, corpus
from tests.integration.test_sources import fixed_dns

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "clear_search_rate", "db", "db_url", "fixed_dns"]


async def test_europes_map_rows_sum_to_the_search_total(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Acceptance 2: region Europe and a topic in the last 30 days, map against search."""
    sid = await corpus(admin, db)
    rule = await term(admin, {"keywords": ["NIS2"]})
    from regwatch.taxonomy.models import Term

    key = await db.scalar(select(Term.key).where(Term.id == rule))
    for item in (await db.scalars(select(Item).where(Item.source_id == uuid.UUID(sid)))).all():
        await reprocess_item(db, item.id)
    filters = {"sources": [sid], "terms": {"topic": [key]}}
    raw = quote(json.dumps(filters))
    got = await admin.get(_api(f"/map/activity?period_days=30&filters={raw}"))
    assert got.status_code == 200, got.text
    body = got.json()
    rows = {r["code"]: r for r in body["rows"]}
    assert rows["DE"]["count"] == 2 and rows["DE"]["max_severity"] == "info"
    assert rows["DE"]["breakdown"] == {"info": 2, "notable": 0, "major": 0}
    since = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    search = await admin.post(_api("/search"), json={"q": TAG, "filters": {
        **filters, "regions": ["150"], "changed": {"from": since}}})  # fmt: skip
    assert search.json()["total"] == sum(r["count"] for r in body["rows"])
    regions = await admin.get(_api(f"/map/activity?view_by=region&filters={raw}"))
    assert {r["code"]: r["count"] for r in regions.json()["rows"]} == {"155": 2}


async def test_the_period_bounds_events_and_severity(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    sid = await corpus(admin, db)
    item = await db.scalar(select(Item).where(Item.source_id == uuid.UUID(sid)).limit(1))
    assert item is not None
    await db.execute(update(ChangeEvent).where(ChangeEvent.item_id == item.id).values(
        severity="major", occurred_at=datetime(2020, 5, 1, tzinfo=UTC)))  # fmt: skip
    await db.commit()
    raw = quote(json.dumps({"sources": [sid]}))
    recent = (await admin.get(_api(f"/map/activity?filters={raw}"))).json()
    assert {r["code"]: r["count"] for r in recent["rows"]} == {"DE": 2}
    old = (await admin.get(_api("/map/activity?from=2020-04-01T00:00:00Z&to=2020-06-01T00:00:00Z"
                                f"&filters={raw}"))).json()  # fmt: skip
    assert [(r["code"], r["count"], r["max_severity"]) for r in old["rows"]] == [("DE", 1, "major")]


@pytest.mark.parametrize(
    "query",
    ["view_by=regulation", "filters=not-json", "filters=" + quote(json.dumps({"terms": {
        f"f{n}": ["t"] for n in range(11)}})), "filters=" + quote(json.dumps({"terms": {
        "no-such-facet": ["x"]}})), "from=2026-02-01T00:00:00Z&to=2026-01-01T00:00:00Z",
     "filters=" + "x" * 16_001],
)  # fmt: skip
async def test_bad_map_queries_are_400s(admin: httpx.AsyncClient, query: str) -> None:
    got = await admin.get(_api(f"/map/activity?{query}"))
    assert got.status_code == 400, got.text


async def test_an_anonymous_caller_sees_no_map(admin: httpx.AsyncClient) -> None:
    anonymous = httpx.AsyncClient(transport=admin._transport, base_url="https://localhost",
                                  headers=ORIGIN)  # fmt: skip
    async with anonymous:
        assert (await anonymous.get(_api("/map/activity"))).status_code == 401
