"""Integration: report layouts and the field whitelist (M7.1; acceptance 2; CP-30)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import clear_limits, db_url

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db_url"]  # shared fixtures


def layout(*content: dict[str, Any]) -> dict[str, Any]:
    return {"root": {"props": {"title": "Europe this month"}}, "content": list(content)}


TABLE = {"type": "ItemsTable", "props": {
    "id": "t1", "columns": ["item.title", "jurisdiction.names", "item.last_changed_at"],
    "sort": "item.last_changed_at", "limit": 20}}  # fmt: skip
HEADING = {"type": "Heading", "props": {"id": "h1", "text": "Changes"}}
BODY = {"name": "Europe 30 days", "layout": layout(HEADING, TABLE)}


async def test_layouts_are_private_until_shared(admin: httpx.AsyncClient) -> None:
    ana = await _as_new_user(admin, "ana@example.org", ["analyst"])
    bob = await _as_new_user(admin, "bob@example.org", ["analyst"])
    eve = await _as_new_user(admin, "eve@example.org", ["editor"])
    fields = {f["key"] for f in (await ana.get(_api("/reports/fields"))).json()}
    assert {"item.title", "jurisdiction.names", "facet.topic"} <= fields

    made = await ana.post(_api("/reports/layouts"), json=BODY)
    assert made.status_code == 201, made.text
    lid = made.json()["id"]
    assert (made.json()["version"], made.json()["shared"], made.json()["page_size"]) == (
        1, False, "A4")  # fmt: skip
    stored = made.json()["layout"]["content"][1]["props"]
    assert stored["direction"] == "desc" and stored["caption"] is None  # defaults filled in
    assert (await bob.get(_api(f"/reports/layouts/{lid}"))).status_code == 404
    assert [x["id"] for x in (await bob.get(_api("/reports/layouts"))).json()] == []
    assert lid in [x["id"] for x in (await admin.get(_api("/reports/layouts"))).json()]  # all

    no_share = await ana.patch(_api(f"/reports/layouts/{lid}"), json={"shared": True})
    assert no_share.status_code == 403  # analysts lack reports.share
    eves = (await eve.post(_api("/reports/layouts"), json={**BODY, "shared": True})).json()
    assert eves["shared"] is True
    assert eves["id"] in [x["id"] for x in (await bob.get(_api("/reports/layouts"))).json()]
    assert (await bob.patch(_api(f"/reports/layouts/{eves['id']}"),
                            json={"name": "Mine"})).status_code == 403  # fmt: skip
    assert (await bob.delete(_api(f"/reports/layouts/{eves['id']}"))).status_code == 403
    assert (await admin.patch(_api(f"/reports/layouts/{lid}"),
                              json={"name": "Taken"})).status_code == 403  # fmt: skip

    renamed = await ana.patch(_api(f"/reports/layouts/{lid}"), json={"name": "Renamed"})
    assert renamed.json()["version"] == 1  # the name is not a new version
    moved = await ana.patch(_api(f"/reports/layouts/{lid}"), json={"layout": layout(TABLE)})
    assert moved.json()["version"] == 2
    assert (await ana.delete(_api(f"/reports/layouts/{lid}"))).status_code == 204
    rows = (await admin.get(_api("/admin/audit"), params={"entity_type": "report_layout"})).json()
    actions = [r["action"] for r in rows["items"]]
    assert actions.count("report_layout.create") == 2 and "report_layout.delete" in actions
    viewer = await _as_new_user(admin, "vik@example.org", ["viewer"])
    assert (await viewer.get(_api("/reports/layouts"))).status_code == 403
    for client in (ana, bob, eve, viewer):
        await client.aclose()


@pytest.mark.parametrize(
    ("bad", "field"),
    [
        (layout({"type": "Script", "props": {"id": "x"}}), "layout.content.0.type"),
        (layout({"type": "Heading", "props": {"id": "x", "text": "a", "onclick": "y"}}),
         "layout.content.0.props.onclick"),
        (layout({"type": "Heading", "props": {"id": "x", "text": "a‮b"}}),
         "layout.content.0.props.text"),
        (layout({"type": "Heading", "props": {"id": "x", "text": "a" * 201}}),
         "layout.content.0.props.text"),
        (layout({"type": "ItemsTable", "props": {"id": "t", "columns": ["item.content_hash"]}}),
         "layout.content.0.props"),
        (layout({"type": "ItemsTable", "props": {"id": "t", "columns": ["item.title"],
                                                 "sort": "item.summary"}}),
         "layout.content.0.props.sort"),
        (layout(HEADING, HEADING), "layout.content.1.props.id"),
        ({**layout(HEADING), "zones": {"a:b": [HEADING]}}, "layout.zones"),
        ({**layout(HEADING), "extra": 1}, "layout.extra"),
        (layout(*({"type": "PageBreak", "props": {"id": f"p{n}"}} for n in range(201))),
         "layout.content"),
        (layout(*({"type": "MapSnapshot", "props": {"id": f"m{n}"}} for n in range(6))),
         "layout.content"),
        (layout(*({"type": "BarChart", "props": {"id": f"b{n}"}} for n in range(21))),
         "layout.content"),
        (layout({"type": "Paragraph", "props": {"id": "p", "text": "x" * 5000}},
                *({"type": "Paragraph", "props": {"id": f"q{n}", "text": "y" * 4999}}
                  for n in range(60))), "layout"),
    ],
)  # fmt: skip
async def test_bad_layouts_are_refused(admin: httpx.AsyncClient, bad: dict[str, Any],
                                       field: str) -> None:  # fmt: skip
    got = await admin.post(_api("/reports/layouts"), json={"name": "Bad", "layout": bad})
    assert got.status_code == 422, got.text
    assert [e["field"] for e in got.json()["errors"]] == [field]


async def test_the_data_source_is_one_the_owner_can_see(admin: httpx.AsyncClient) -> None:
    ana = await _as_new_user(admin, "amy@example.org", ["analyst"])
    view = await admin.post(_api("/views"), json={"name": "Admin only", "period_days": 30})
    assert view.status_code == 201, view.text
    hidden = {**BODY, "data_source": {"saved_view_id": view.json()["id"]}}
    refused = await ana.post(_api("/reports/layouts"), json=hidden)
    assert refused.status_code == 422 and "saved view" in refused.text
    both = {**BODY, "data_source": {"saved_view_id": view.json()["id"], "query": {"q": "nis2"}}}
    assert (await admin.post(_api("/reports/layouts"), json=both)).status_code == 422
    query = {**BODY, "data_source": {"query": {"q": "nis2"}, "limit": 100}}
    made = await ana.post(_api("/reports/layouts"), json=query)
    assert made.status_code == 201 and made.json()["data_source"]["limit"] == 100
    await ana.aclose()


async def test_sharing_never_exposes_a_private_view(admin: httpx.AsyncClient) -> None:
    """M7.1 review: a shared layout needs a shared view; owners may always unshare."""
    eve = await _as_new_user(admin, "eva@example.org", ["editor"])
    eid = (await eve.get(_api("/auth/me"))).json()["id"]
    mine = (await eve.post(_api("/views"), json={"name": "Mine", "period_days": 30})).json()
    private = {**BODY, "data_source": {"saved_view_id": mine["id"]}}
    refused = await eve.post(_api("/reports/layouts"), json={**private, "shared": True})
    assert refused.status_code == 422 and "shared saved view" in refused.text
    lid = (await eve.post(_api("/reports/layouts"), json=private)).json()["id"]
    late = await eve.patch(_api(f"/reports/layouts/{lid}"), json={"shared": True})
    assert late.status_code == 422
    shared = (await eve.post(_api("/reports/layouts"), json={**BODY, "shared": True})).json()
    demoted = await admin.patch(_api(f"/admin/users/{eid}"), json={"roles": ["analyst"]})
    assert demoted.status_code == 200  # no reports.share any more
    withdrawn = await eve.patch(_api(f"/reports/layouts/{shared['id']}"), json={"shared": False})
    assert withdrawn.status_code == 200 and withdrawn.json()["shared"] is False
    bad = await eve.post(_api("/reports/layouts"), json={**BODY, "data_source": {"limit": 0}})
    assert bad.status_code == 422
    await eve.aclose()
