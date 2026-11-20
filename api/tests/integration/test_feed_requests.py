"""Integration: feed requests (CP-26, ADR-0012, M11.3)."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from regwatch.capture import requests
from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import clear_limits, db_url
from tests.integration.test_sources import fixed_dns, rss

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db_url", "fixed_dns"]  # shared fixtures

ASK = {"url": "https://example.org/feed.xml", "reason": "Our regulator's notices."}


@pytest.fixture(autouse=True)
def clear_requests() -> Iterator[None]:
    requests.requests_made.clear()
    yield
    requests.requests_made.clear()


async def _audit(admin: httpx.AsyncClient) -> list[str]:
    rows = await admin.get(_api("/admin/audit"), params={"entity_type": "feed_request"})
    return [r["action"] for r in rows.json()["items"]]


async def test_a_request_is_approved_into_the_catalogue(admin: httpx.AsyncClient) -> None:
    viewer = await _as_new_user(admin, "vic@example.org", ["viewer"])
    made = await viewer.post(_api("/feed-requests"), json=ASK)
    assert made.status_code == 201, made.text
    rid = made.json()["id"]
    assert made.json()["status"] == "pending" and made.json()["requested_by"] is None
    mine = (await viewer.get(_api("/feed-requests"))).json()
    assert [r["id"] for r in mine] == [rid] and mine[0]["requested_by"] is None
    queue = (await admin.get(_api("/feed-requests"), params={"status": "pending"})).json()
    assert [(r["id"], r["requested_by"]) for r in queue] == [(rid, "vic")]
    # Editors only decide; a viewer may not.
    decision = {"decision": "approved", "source_id": None, "summary": "Notices."}
    assert (await viewer.post(_api(f"/feed-requests/{rid}/decision"),
                              json=decision)).status_code == 403  # fmt: skip

    no_source = await admin.post(_api(f"/feed-requests/{rid}/decision"), json=decision)
    assert no_source.status_code == 422 and "source_id" in no_source.text
    source = (await admin.post(_api("/sources"), json=rss())).json()
    no_summary = {"decision": "approved", "source_id": source["id"]}
    assert (await admin.post(_api(f"/feed-requests/{rid}/decision"),
                             json=no_summary)).status_code == 422  # fmt: skip
    approve = {**decision, "source_id": source["id"], "note": "Added."}
    approved = await admin.post(_api(f"/feed-requests/{rid}/decision"), json=approve)
    assert approved.status_code == 200, approved.text
    assert (approved.json()["status"], approved.json()["source_id"]) == ("approved", source["id"])
    entries = {e["id"]: e for e in (await viewer.get(_api("/catalogue"))).json()}
    added = entries[source["id"]]
    assert added["key"].startswith("added-") and added["summary"] == "Notices."
    assert added["following"] is True  # the requester follows what they asked for
    again = await admin.post(_api(f"/feed-requests/{rid}/decision"), json=decision)
    assert again.status_code == 409
    assert await _audit(admin) == ["feed_request.approve", "feed_request.create"]
    await viewer.aclose()


async def test_requests_are_checked_limited_and_private(
    admin: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    viewer = await _as_new_user(admin, "val@example.org", ["viewer"])
    other = await _as_new_user(admin, "oli@example.org", ["viewer"])
    for bad in ({**ASK, "url": "http://example.org/feed.xml"},
                {**ASK, "url": "javascript:alert(1)"}, {**ASK, "reason": "  "},
                {**ASK, "reason": "bad‮text"}, {**ASK, "url": "https://" + "a" * 2048}):  # fmt: skip
        assert (await viewer.post(_api("/feed-requests"), json=bad)).status_code == 422, bad
    rid = (await viewer.post(_api("/feed-requests"), json=ASK)).json()["id"]
    assert (await viewer.post(_api("/feed-requests"), json=ASK)).status_code == 409  # again
    assert (await other.get(_api("/feed-requests"))).json() == []  # nobody else's
    assert (await other.delete(_api(f"/feed-requests/{rid}"))).status_code == 404
    assert (await viewer.delete(_api(f"/feed-requests/{rid}"))).status_code == 204
    assert (await viewer.delete(_api(f"/feed-requests/{rid}"))).status_code == 409
    declined_late = await admin.post(_api(f"/feed-requests/{rid}/decision"),
                                     json={"decision": "declined"})  # fmt: skip
    assert declined_late.status_code == 409

    monkeypatch.setattr(requests, "MAX_PENDING", 1)
    two = {**ASK, "url": "https://example.org/two.xml"}
    assert (await viewer.post(_api("/feed-requests"), json=two)).status_code == 201
    full = await viewer.post(_api("/feed-requests"), json={**ASK, "url": "https://x.org/3"})
    assert full.status_code == 409 and "at most 1" in full.text
    monkeypatch.setattr(requests, "REQUEST_RATE", 2)  # create, and the second one, counted
    limited = await other.post(_api("/feed-requests"), json=ASK)
    assert limited.status_code == 201  # per user
    assert (await viewer.post(_api("/feed-requests"), json=ASK)).status_code == 429
    await viewer.aclose()
    await other.aclose()


async def test_a_declined_request_keeps_the_note(admin: httpx.AsyncClient) -> None:
    rid = (await admin.post(_api("/feed-requests"), json=ASK)).json()["id"]
    note = {"decision": "declined", "note": "Already covered by EUR-Lex."}
    declined = await admin.post(_api(f"/feed-requests/{rid}/decision"), json=note)
    assert declined.status_code == 200
    assert (declined.json()["status"], declined.json()["decision_note"]) == (
        "declined", "Already covered by EUR-Lex.")  # fmt: skip
    bad = {"decision": "declined", "note": "x‮"}
    rid2 = await admin.post(_api("/feed-requests"), json={**ASK, "url": "https://y.org/f"})
    assert (await admin.post(_api(f"/feed-requests/{rid2.json()['id']}/decision"),
                             json=bad)).status_code == 422  # fmt: skip


async def test_feed_requests_need_items_read(admin: httpx.AsyncClient) -> None:
    nobody = await _as_new_user(admin, "nia@example.org", [])
    assert (await nobody.post(_api("/feed-requests"), json=ASK)).status_code == 403
    assert (await nobody.get(_api("/feed-requests"))).status_code == 403
    await nobody.aclose()


async def test_approval_never_revives_or_widens_a_source(admin: httpx.AsyncClient) -> None:
    """Review finding 1: an approval cannot publish an older, paused, out-of-kind or
    robots-overriding source, unless the approver may override robots.txt."""
    older = (await admin.post(_api("/sources"), json=rss(name="Older"))).json()
    rid = (await admin.post(_api("/feed-requests"), json=ASK)).json()["id"]
    crawl = {"name": "Crawl", "kind": "web_crawl", "config": {
        "seed_urls": ["https://feeds.example/"], "allowed_domains": ["feeds.example"]}}  # fmt: skip
    crawler = (await admin.post(_api("/sources"), json=crawl)).json()
    paused = (await admin.post(_api("/sources"), json=rss(name="Paused"))).json()
    await admin.patch(_api(f"/sources/{paused['id']}"), json={"enabled": False})
    overriding = (await admin.post(_api("/sources"), json=rss(
        name="Override", robots_policy="override", override_reason="Owner agreed in writing",
    ))).json()  # fmt: skip
    editor = await _as_new_user(admin, "eve@example.org", ["editor"])

    async def approve(client: httpx.AsyncClient, sid: str) -> httpx.Response:
        return await client.post(_api(f"/feed-requests/{rid}/decision"), json={
            "decision": "approved", "source_id": sid, "summary": "A feed."})  # fmt: skip

    for sid, why in ((older["id"], "created for this request"), (crawler["id"], "rss, api_feed"),
                     (paused["id"], "turned off")):  # fmt: skip
        refused = await approve(admin, sid)
        assert refused.status_code == 422 and why in refused.text, refused.text
    refused = await approve(editor, overriding["id"])
    assert refused.status_code == 422 and "override robots.txt" in refused.text
    assert (await approve(admin, overriding["id"])).status_code == 200  # admin may override
    curated = (await admin.get(_api("/catalogue"))).json()
    assert {e["id"] for e in curated} >= {overriding["id"]}
    assert all(e["key"] != f"added-{older['id']}" for e in curated)
    await editor.aclose()


async def test_request_urls_show_their_real_host(admin: httpx.AsyncClient) -> None:
    """Review finding 4: no credentials, no spaces; an IDN host is stored in punycode."""
    for bad in ("https://trusted.gov@evil.example/feed", "https://u:p@example.org/",
                "https://example.org/a b", "https://[2001:db8::1]/feed",
                "https://192.0.2.1/feed"):  # fmt: skip
        got = await admin.post(_api("/feed-requests"), json={**ASK, "url": bad})
        assert got.status_code == 422, bad
    made = await admin.post(_api("/feed-requests"),
                            json={**ASK, "url": "https://gоv.uk/feed"})  # fmt: skip
    assert made.status_code == 201 and made.json()["url"] == "https://xn--gv-fmc.uk/feed"


async def test_a_disabled_requester_is_not_subscribed(admin: httpx.AsyncClient) -> None:
    viewer = await _as_new_user(admin, "dan@example.org", ["viewer"])
    vid = (await viewer.get(_api("/auth/me"))).json()["id"]
    rid = (await viewer.post(_api("/feed-requests"), json=ASK)).json()["id"]
    await viewer.aclose()
    assert (await admin.patch(_api(f"/admin/users/{vid}"),
                              json={"status": "disabled"})).status_code == 200  # fmt: skip
    source = (await admin.post(_api("/sources"), json=rss())).json()
    ok = await admin.post(_api(f"/feed-requests/{rid}/decision"), json={
        "decision": "approved", "source_id": source["id"], "summary": "A feed."})  # fmt: skip
    assert ok.status_code == 200
    assert (await admin.get(_api(f"/sources/{source['id']}"))).json()["followers"] == 0
