"""Search sources (ADR-0010): save-time checks and the worker's search context."""

from __future__ import annotations

import httpx
import pytest

from regwatch.capture import tasks
from tests.integration.test_admin import _api, admin
from tests.integration.test_auth import clear_limits, db_url
from tests.integration.test_capture_runs import db
from tests.integration.test_sources import fixed_dns

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db", "db_url", "fixed_dns"]  # shared fixtures


def search(**config: object) -> dict[str, object]:
    return {"name": "Search", "kind": "search_query", "credibility": "secondary",
            "config": {"query": "AI act", **config}}  # fmt: skip


@pytest.mark.parametrize(
    ("body", "field"),
    [({**search(), "robots_policy": "override", "override_reason": "agreed"}, "robots_policy"),
     (search(site_filters=["*.reg.example"]), "config"), (search(query="   "), "config")],
)  # fmt: skip
async def test_bad_search_sources_are_refused(admin: httpx.AsyncClient, body: dict[str, object],
                                              field: str) -> None:  # fmt: skip
    got = await admin.post(_api("/sources"), json=body)
    assert got.status_code == 422, got.text
    assert [e["field"] for e in got.json()["errors"]] == [field]
    ok = await admin.post(_api("/sources"), json=search(site_filters=["reg.example"]))
    assert ok.status_code == 201, ok.text


async def test_the_search_context_follows_the_flag_and_the_provider(
    admin: httpx.AsyncClient, db: object
) -> None:
    feed = {"name": "Official feed", "kind": "rss", "credibility": "official",
            "config": {"feed_url": "https://feeds.example/rss"}}  # fmt: skip
    assert (await admin.post(_api("/sources"), json=feed)).status_code == 201
    off, official = await tasks._search_context(db)  # type: ignore[arg-type]
    assert off is None and "feeds.example" in official  # the flag is off by default
    flag = await admin.patch(_api("/admin/feature-flags/search.internet"), json={"enabled": True})
    assert flag.status_code == 200, flag.text
    still_off, _ = await tasks._search_context(db)  # type: ignore[arg-type]
    assert still_off is None  # search.provider is none by default
    put = await admin.put(_api("/admin/settings/search.provider"), json={"value": "searxng"})
    assert put.status_code in (200, 204), put.text
    on, _ = await tasks._search_context(db)  # type: ignore[arg-type]
    assert on is not None and on.base_url == "http://search:8080"


async def test_search_sources_are_secondary_and_never_name_official_hosts(
    admin: httpx.AsyncClient, db: object
) -> None:
    """Search review finding 4."""
    body = {"name": "S", "kind": "search_query", "url": "https://feeds.example/lookalike",
            "config": {"query": "https://junk.example/ AI act"}}  # fmt: skip
    made = await admin.post(_api("/sources"), json=body)
    assert made.status_code == 201, made.text
    assert made.json()["credibility"] == "secondary"  # never official by default
    loud = {**body, "name": "S2", "credibility": "official"}
    assert (await admin.post(_api("/sources"), json=loud)).status_code == 201
    _, official = await tasks._search_context(db)  # type: ignore[arg-type]
    assert "feeds.example" not in official and "junk.example" not in official
