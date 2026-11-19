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
     "nis2:* & !incident"],
)  # fmt: skip
async def test_hostile_queries_are_words_not_syntax(
    admin: httpx.AsyncClient, db: AsyncSession, q: str
) -> None:
    await corpus(admin, db)
    got = await admin.post(
        _api("/search"),
        json={
            "q": q,
            "filters": {"jurisdictions": ["DE' OR '1'='1"], "terms": {"topic' --": ["x"]}},
        },
    )
    assert got.status_code == 200, got.text
    assert got.json()["total"] == 0


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
