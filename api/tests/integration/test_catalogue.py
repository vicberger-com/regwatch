"""Integration: the feed catalogue and following (CP-25, ADR-0012, M11.2)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from regwatch.capture import catalogue
from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import clear_limits, db_url
from tests.integration.test_sources import fixed_dns, rss

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db_url", "fixed_dns"]  # shared fixtures

FR = "us-federal-register-it"


@pytest.fixture(autouse=True)
def clear_follows() -> Iterator[None]:
    catalogue.follows.clear()
    yield
    catalogue.follows.clear()


async def _entries(client: httpx.AsyncClient) -> dict[str, dict[str, object]]:
    got = await client.get(_api("/catalogue"))
    assert got.status_code == 200, got.text
    return {e["key"]: e for e in got.json()}


async def _follows(admin: httpx.AsyncClient) -> list[tuple[str, object, object]]:
    rows = (await admin.get(_api("/admin/audit"), params={"entity_type": "source"})).json()
    return [(r["action"], r["before"], r["after"]) for r in rows["items"]
            if r["action"] in ("source.follow", "source.unfollow")]  # fmt: skip


async def test_following_switches_capture_and_is_audited_once(admin: httpx.AsyncClient) -> None:
    viewer = await _as_new_user(admin, "vera@example.org", ["viewer"])
    entries = await _entries(viewer)
    assert sorted(entries) == ["eu-eurlex-cellar-it", "eu-eurlex-rss-ep-council",
                               "gb-legislation-it", FR]  # fmt: skip
    fr = entries[FR]
    assert fr["jurisdictions"] == ["US"] and fr["summary"] and fr["terms_url"]
    assert (fr["available"], fr["captured"], fr["following"]) == (True, False, False)
    sid = fr["id"]

    assert (await viewer.put(_api(f"/catalogue/{sid}/follow"))).status_code == 204
    assert (await viewer.put(_api(f"/catalogue/{sid}/follow"))).status_code == 204  # no change
    fr = (await _entries(viewer))[FR]
    assert (fr["captured"], fr["following"]) == (True, True)
    assert (await _entries(admin))[FR]["following"] is False  # per user
    assert (await admin.put(_api(f"/catalogue/{sid}/follow"))).status_code == 204
    shown = (await admin.get(_api(f"/sources/{sid}"))).json()
    assert (shown["enabled"], shown["captured"], shown["followers"]) == (False, True, 2)
    assert shown["catalogue_key"] == FR

    assert (await viewer.delete(_api(f"/catalogue/{sid}/follow"))).status_code == 204
    assert (await viewer.delete(_api(f"/catalogue/{sid}/follow"))).status_code == 204
    assert (await _entries(viewer))[FR]["captured"] is True  # the admin still follows it
    assert (await admin.delete(_api(f"/catalogue/{sid}/follow"))).status_code == 204
    assert (await _entries(viewer))[FR]["captured"] is False
    # Only the two switches are audited: on by the viewer, off by the admin.
    assert await _follows(admin) == [
        ("source.unfollow", {"captured": True}, {"captured": False}),
        ("source.follow", {"captured": False}, {"captured": True}),
    ]
    await viewer.aclose()


async def test_only_available_catalogue_sources_can_be_followed(
    admin: httpx.AsyncClient,
) -> None:
    own = (await admin.post(_api("/sources"), json=rss())).json()
    assert (await admin.put(_api(f"/catalogue/{own['id']}/follow"))).status_code == 404
    unknown = "00000000-0000-7000-8000-000000000000"
    assert (await admin.put(_api(f"/catalogue/{unknown}/follow"))).status_code == 404
    assert all(e["id"] != own["id"] for e in (await _entries(admin)).values())

    sid = (await _entries(admin))[FR]["id"]
    assert (await admin.put(_api(f"/catalogue/{sid}/follow"))).status_code == 204
    assert (await admin.delete(_api(f"/sources/{sid}"))).status_code == 204  # job off
    fr = (await _entries(admin))[FR]
    assert (fr["available"], fr["captured"], fr["following"]) == (False, False, True)
    assert (await admin.get(_api(f"/sources/{sid}"))).json()["captured"] is False
    assert (await admin.delete(_api(f"/catalogue/{sid}/follow"))).status_code == 204
    refused = await admin.put(_api(f"/catalogue/{sid}/follow"))
    assert refused.status_code == 409 and "turned this source off" in refused.text


async def test_following_is_limited(
    admin: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = [e["id"] for e in (await _entries(admin)).values()]
    monkeypatch.setattr(catalogue, "MAX_FOLLOWED", 1)
    assert (await admin.put(_api(f"/catalogue/{ids[0]}/follow"))).status_code == 204
    capped = await admin.put(_api(f"/catalogue/{ids[1]}/follow"))
    assert capped.status_code == 409 and "at most 1" in capped.text
    monkeypatch.setattr(catalogue, "FOLLOW_RATE", 3)  # the three calls above count
    assert (await admin.delete(_api(f"/catalogue/{ids[0]}/follow"))).status_code == 204
    limited = await admin.put(_api(f"/catalogue/{ids[0]}/follow"))
    assert limited.status_code == 429 and limited.headers["Retry-After"]


async def test_the_catalogue_needs_items_read(admin: httpx.AsyncClient) -> None:
    nobody = await _as_new_user(admin, "nora@example.org", [])
    sid = (await _entries(admin))[FR]["id"]
    assert (await nobody.get(_api("/catalogue"))).status_code == 403
    assert (await nobody.put(_api(f"/catalogue/{sid}/follow"))).status_code == 403
    await nobody.aclose()


async def test_a_disabled_users_follows_keep_nothing_fetched(admin: httpx.AsyncClient) -> None:
    """11.2b review: only active users' follows count, for capture and for admins' count."""
    viewer = await _as_new_user(admin, "dora@example.org", ["viewer"])
    vid = (await viewer.get(_api("/auth/me"))).json()["id"]
    sid = (await _entries(admin))[FR]["id"]
    assert (await viewer.put(_api(f"/catalogue/{sid}/follow"))).status_code == 204
    assert (await admin.get(_api(f"/sources/{sid}"))).json()["captured"] is True
    off = await admin.patch(_api(f"/admin/users/{vid}"), json={"status": "disabled"})
    assert off.status_code == 200, off.text
    shown = (await admin.get(_api(f"/sources/{sid}"))).json()
    assert (shown["captured"], shown["followers"]) == (False, 0)
    assert (await _entries(admin))[FR]["captured"] is False
    on = await admin.patch(_api(f"/admin/users/{vid}"), json={"status": "active"})
    assert on.status_code == 200, on.text
    assert (await admin.get(_api(f"/sources/{sid}"))).json()["captured"] is True
    await viewer.aclose()


async def test_concurrent_follows_stay_under_the_cap(
    admin: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """11.2b review: follows of different sources by one user are ordered by a per-user lock."""
    ids = [e["id"] for e in (await _entries(admin)).values()]
    monkeypatch.setattr(catalogue, "MAX_FOLLOWED", 1)
    checked = catalogue.is_capturing

    async def slow(db: Any, source_id: Any) -> bool:  # between the count and the insert
        await asyncio.sleep(0.3)
        return await checked(db, source_id)

    monkeypatch.setattr(catalogue, "is_capturing", slow)
    got = await asyncio.gather(*(admin.put(_api(f"/catalogue/{i}/follow")) for i in ids))
    assert sorted(r.status_code for r in got) == [204, 409, 409, 409]
    assert sum(e["following"] for e in (await _entries(admin)).values()) == 1
