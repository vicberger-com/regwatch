"""POST /search (M5 acceptance 1; filters; DSL limits; SQL injection fixtures)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.processing.pipeline import process_manifest
from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import ORIGIN, clear_limits, db_url
from tests.integration.test_capture_runs import db
from tests.integration.test_processing_pipeline import BSI, loader, made_source, manifest
from tests.integration.test_sources import fixed_dns

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db", "db_url", "fixed_dns"]  # shared fixtures

TAG = uuid.uuid4().hex[:8]  # a word only this module's items carry


@pytest.fixture(autouse=True)
def clear_search_rate() -> None:
    from regwatch.search import services

    services.searches._hits.clear()
    services._facet_cache.clear()


async def corpus(admin: httpx.AsyncClient, db: AsyncSession) -> str:
    sid = await made_source(admin)
    rows = [
        {"url": f"https://example.org/{TAG}/both", "text": "Eins. " + BSI,
         "title": f"{TAG} NIS2 incident reporting guidance",
         "summary": "How operators report an incident under NIS2 <b>now</b>."},
        {"url": f"https://example.org/{TAG}/one", "text": "Zwei. " + BSI,
         "title": f"{TAG} NIS2 scope clarified", "summary": "Which entities are covered."},
        {"url": f"https://example.org/{TAG}/none", "text": "Drei. " + BSI,
         "title": f"{TAG} Annual report published", "summary": "Statistics for the year."},
    ]  # fmt: skip
    key, objects = manifest(sid, uuid.uuid4(), rows)
    await process_manifest(db, key, loader(objects))
    return sid


async def test_more_of_the_words_rank_first_with_highlights(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Acceptance 1: "NIS2 incident" ranks the item with both above items with one."""
    await corpus(admin, db)
    viewer = await _as_new_user(admin, f"viewer-{uuid.uuid4().hex[:8]}@example.org", ["viewer"])
    try:
        got = await viewer.post(_api("/search"), json={"q": f"{TAG} NIS2 incident"})
        assert got.status_code == 200, got.text
        body = got.json()
        titles = [i["title"] for i in body["items"]]
        assert titles[0].endswith("NIS2 incident reporting guidance")
        assert titles[1].endswith("NIS2 scope clarified") and body["total"] == 3
        first = body["items"][0]
        assert "<mark>NIS2</mark>" in first["highlights"]["title"][0]
        assert "<b>" not in first["highlights"]["summary"][0]  # tags never reach the summary
        assert first["jurisdictions"][0]["code"] == "DE" and first["severity"] == "info"
        assert isinstance(body["took_ms"], int)
    finally:
        await viewer.aclose()


async def test_filters_sort_and_paging(admin: httpx.AsyncClient, db: AsyncSession) -> None:
    sid = await corpus(admin, db)
    soon = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    cases: list[tuple[dict[str, Any], int]] = [
        ({"sources": [sid]}, 3), ({"sources": [str(uuid.uuid4())]}, 0),
        ({"jurisdictions": ["de"]}, 3), ({"jurisdictions": ["FR"]}, 0),
        ({"regions": ["150"]}, 3), ({"regions": ["155"]}, 3), ({"regions": ["142"]}, 0),
        ({"severity": ["major"]}, 0), ({"severity": ["info"]}, 3),
        ({"status": ["new"]}, 3), ({"credibility": ["news"]}, 0),
        ({"changed": {"from": past, "to": soon}}, 3), ({"changed": {"from": soon}}, 0),
        ({"needs_review": False}, 3), ({"terms": {"topic": ["no-such-term"]}}, 0),
    ]  # fmt: skip
    for filters, expected in cases:
        got = await admin.post(_api("/search"), json={"q": TAG, "filters": filters})
        assert got.status_code == 200, (filters, got.text)
        assert got.json()["total"] == expected, filters
    paged = await admin.post(_api("/search"), json={"q": TAG, "sort": "title_asc",
                                                    "page": 2, "page_size": 2})  # fmt: skip
    assert [i["title"] for i in paged.json()["items"]] == [f"{TAG} NIS2 scope clarified"]


@pytest.mark.parametrize(
    "q",
    ["'; DROP TABLE item; --", "NIS2 & | ! :* <-> (", "\\x00", "' OR 1=1 --", "%_%",
     "nis2:* & !incident", '"unterminated -', "a OR OR -", '""'],
)  # fmt: skip
async def test_hostile_queries_are_words_not_syntax(
    admin: httpx.AsyncClient, db: AsyncSession, q: str
) -> None:
    await corpus(admin, db)
    got = await admin.post(
        _api("/search"),
        json={
            "q": q,
            "filters": {"jurisdictions": ["DE' OR '1'='1"], "terms": {"topic": ["x' OR '1"]}},
        },
    )
    assert got.status_code == 200, got.text
    assert got.json()["total"] == 0
    hostile_facet = {"q": q, "filters": {"terms": {"topic' --": ["x"]}}}
    assert (await admin.post(_api("/search"), json=hostile_facet)).status_code == 400


@pytest.mark.parametrize(
    "body",
    [{"page_size": 201}, {"page": 0}, {"q": "x" * 501},
     {"filters": {"terms": {"topic": [f"t{n}" for n in range(21)]}}},
     {"filters": {"jurisdictions": [f"J{n}" for n in range(51)]}}, {"sort": "random"}],
)  # fmt: skip
async def test_the_dsl_limits(admin: httpx.AsyncClient, body: dict[str, Any]) -> None:
    assert (await admin.post(_api("/search"), json=body)).status_code == 422


async def test_an_anonymous_caller_searches_nothing(admin: httpx.AsyncClient) -> None:
    anonymous = httpx.AsyncClient(transport=admin._transport, base_url="https://localhost",
                                  headers=ORIGIN)  # fmt: skip
    async with anonymous:
        assert (await anonymous.post(_api("/search"), json={})).status_code == 401


@pytest.mark.parametrize(
    "body",
    [{"filters": {"terms": {f"f{n}": ["t"] for n in range(11)}}},
     {"filters": {"languages": ["en"] * 51}}, {"filters": {"status": ["new"] * 51}},
     {"page": 51, "page_size": 200}, {"page": 10**17},
     {"filters": {"terms": {"no-such-facet": ["x"]}}}],
)  # fmt: skip
async def test_queries_past_the_limits_are_400s_not_500s(
    admin: httpx.AsyncClient, body: dict[str, Any]
) -> None:
    """Search review findings 1, 3 and 14: a cheap 400 before any database work."""
    got = await admin.post(_api("/search"), json=body)
    assert got.status_code == 400, got.text


async def test_searches_are_rate_limited_per_user(admin: httpx.AsyncClient) -> None:
    """08 security 8.2: 60 a minute per user (finding 2)."""
    from regwatch.search import services

    for _ in range(services.SEARCH_RATE):
        assert (await admin.post(_api("/search"), json={"q": "x"})).status_code == 200
    refused = await admin.post(_api("/search"), json={"q": "x"})
    assert refused.status_code == 429 and int(refused.headers["retry-after"]) >= 1


async def test_repeating_a_word_never_beats_having_both(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Finding 7: matched words first, then rank."""
    sid = await made_source(admin)
    tag = uuid.uuid4().hex[:8]
    rows = [{"url": f"https://example.org/{tag}/stuffed", "text": "A. " + BSI,
             "title": f"{tag} NIS2 NIS2 NIS2 guidance", "summary": "NIS2 " * 40},
            {"url": f"https://example.org/{tag}/both", "text": "B. " + BSI,
             "title": f"{tag} NIS2 incident reporting guidance"}]  # fmt: skip
    key, objects = manifest(sid, uuid.uuid4(), rows)
    await process_manifest(db, key, loader(objects))
    got = (await admin.post(_api("/search"), json={"q": f"{tag} NIS2 incident"})).json()
    assert got["items"][0]["title"].endswith("incident reporting guidance")


async def test_websearch_phrases_and_exclusions(admin: httpx.AsyncClient, db: AsyncSession) -> None:
    """Finding 8: the contract's websearch syntax."""
    await corpus(admin, db)
    phrase = await admin.post(_api("/search"), json={"q": f'{TAG} "incident reporting"'})
    assert [i["title"] for i in phrase.json()["items"]] == [
        f"{TAG} NIS2 incident reporting guidance"]  # fmt: skip
    excluded = await admin.post(_api("/search"), json={"q": f"{TAG} NIS2 -guidance"})
    assert [i["title"] for i in excluded.json()["items"]] == [f"{TAG} NIS2 scope clarified"]


async def test_severity_is_the_query_periods(admin: httpx.AsyncClient, db: AsyncSession) -> None:
    """Finding 9: an old major event does not make an item major for a later period."""
    from sqlalchemy import select, update

    from regwatch.processing.models import ChangeEvent, Item

    await corpus(admin, db)
    item = await db.scalar(select(Item).where(Item.title == f"{TAG} Annual report published"))
    assert item is not None
    await db.execute(update(ChangeEvent).where(ChangeEvent.item_id == item.id).values(
        severity="major", occurred_at=datetime(2001, 1, 1, tzinfo=UTC)))  # fmt: skip
    await db.commit()
    recent = {"severity": ["major"], "changed": {"from": "2026-01-01T00:00:00+00:00"}}
    got = await admin.post(_api("/search"), json={"q": TAG, "filters": recent})
    assert got.json()["total"] == 0
    found = (await admin.post(_api("/search"), json={"q": TAG, "filters": {
        "severity": ["major"]}})).json()  # fmt: skip
    assert found["total"] == 1 and found["items"][0]["severity"] == "major"
    period = (await admin.post(_api("/search"), json={"q": f"{TAG} annual", "filters": {
        "changed": {"from": "2026-01-01T00:00:00+00:00"}}})).json()  # fmt: skip
    assert period["items"][0]["severity"] is None


async def test_region_europe_includes_the_european_union(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Finding 10: an item tagged only EU is in region 150."""
    from sqlalchemy import delete, select

    from regwatch.processing.models import Item, ItemJurisdiction
    from regwatch.taxonomy.models import Jurisdiction

    await corpus(admin, db)
    item = await db.scalar(select(Item).where(Item.title == f"{TAG} NIS2 scope clarified"))
    eu = await db.scalar(select(Jurisdiction.id).where(Jurisdiction.code == "EU"))
    assert item is not None and eu is not None
    await db.execute(delete(ItemJurisdiction).where(ItemJurisdiction.item_id == item.id))
    db.add(ItemJurisdiction(item_id=item.id, jurisdiction_id=eu, assigned_by="user"))
    await db.commit()
    got = await admin.post(_api("/search"), json={"q": TAG, "filters": {"regions": ["150"]}})
    assert got.json()["total"] == 3


@pytest.mark.parametrize(
    "raw", ['{"filters": {"languages": ["\\udfff"]}}', '{"filters": {"terms": {"\\udfff": ["x"]}}}']
)
async def test_a_lone_surrogate_is_a_400(admin: httpx.AsyncClient, raw: str) -> None:
    """Finding 14: sent as JSON escapes, as no client library would encode it."""
    got = await admin.post(
        _api("/search"), content=raw.encode(), headers={"content-type": "application/json"}
    )
    assert got.status_code == 400, got.text


async def test_a_term_filter_matches_and_an_incorrect_term_never_does(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Finding 15: a matching term filter; a term a user marked incorrect is neither matched
    nor shown; a match in the English title is highlighted (finding 12)."""
    from sqlalchemy import select, update

    from regwatch.processing.models import Item, ItemTerm
    from regwatch.processing.pipeline import reprocess_item
    from regwatch.taxonomy.models import Term
    from tests.integration.test_processing_classify import term

    await corpus(admin, db)
    rule = await term(admin, {"keywords": ["NIS2"]})
    key = await db.scalar(select(Term.key).where(Term.id == rule))
    items = (await db.scalars(select(Item).where(Item.title.like(f"{TAG}%")))).all()
    for item in items:
        await reprocess_item(db, item.id)
    body = {"q": TAG, "filters": {"terms": {"topic": [key]}}}
    assert (await admin.post(_api("/search"), json=body)).json()["total"] == 2
    target = next(i for i in items if i.title.endswith("scope clarified"))
    await db.execute(
        update(ItemTerm)
        .where(ItemTerm.item_id == target.id, ItemTerm.term_id == rule)
        .values(feedback="incorrect")
    )
    await db.execute(update(Item).where(Item.id == target.id).values(title_en="Zebrafish scope"))
    await db.commit()
    assert (await admin.post(_api("/search"), json=body)).json()["total"] == 1
    shown = (await admin.post(_api("/search"), json={"q": f"{TAG} zebrafish"})).json()
    hit = next(i for i in shown["items"] if i["id"] == str(target.id))
    assert str(rule) not in {t["term_id"] for t in hit["terms"]}
    assert hit["highlights"]["title_en"] == ["<mark>Zebrafish</mark> scope"]


async def test_a_search_past_its_timeout_is_a_503(
    admin: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-verification 1, N2: the statement timeout answers busy, not 500."""
    from sqlalchemy import text

    from regwatch.search import services

    real = services.compile_query

    def slow(*args: Any, **kwargs: Any) -> Any:
        made = real(*args, **kwargs)
        return type(made)(made.ids.where(text("pg_sleep(0.3) IS NOT NULL")), made.tsquery)

    monkeypatch.setattr(services, "compile_query", slow)
    monkeypatch.setattr(services, "STATEMENT_TIMEOUT", "50ms")
    await corpus(admin, db)
    got = await admin.post(_api("/search"), json={"q": TAG})
    assert got.status_code == 503 and got.headers["retry-after"] == "5"


async def test_a_user_without_items_read_is_refused(admin: httpx.AsyncClient) -> None:
    """Re-verification 1, #15's remaining gap (M5 test plan: users without items.read get 403)."""
    nobody = await _as_new_user(admin, f"none-{uuid.uuid4().hex[:8]}@example.org", [])
    try:
        assert (await nobody.post(_api("/search"), json={})).status_code == 403
    finally:
        await nobody.aclose()


async def test_facet_counts_for_the_matching_items(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """M5 design notes: one grouped count per facet, never an incorrect term; cached."""
    from sqlalchemy import select

    from regwatch.processing.models import Item
    from regwatch.processing.pipeline import reprocess_item
    from regwatch.taxonomy.models import Term
    from tests.integration.test_processing_classify import term

    await corpus(admin, db)
    rule = await term(admin, {"keywords": ["NIS2"]})
    key = await db.scalar(select(Term.key).where(Term.id == rule))
    for item in (await db.scalars(select(Item).where(Item.title.like(f"{TAG}%")))).all():
        await reprocess_item(db, item.id)
    body = (await admin.post(_api("/search"), json={"q": TAG})).json()
    assert {f["key"]: f["count"] for f in body["facets"]["jurisdictions"]} == {"DE": 3}
    assert {f["key"]: f["count"] for f in body["facets"]["topic"]}[key] == 2
    none = (await admin.post(_api("/search"), json={"q": TAG, "facet_counts": False})).json()
    assert none["facets"] == {}
