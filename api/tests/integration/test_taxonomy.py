"""Integration: facets and view dimensions (M2 acceptance 1; REQ-03, REQ-11)."""

from __future__ import annotations

import httpx
import pytest

from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import clear_limits, db_url

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db_url"]  # fixtures shared with test_admin and test_auth


async def _version(admin: httpx.AsyncClient) -> int:
    settings = {s["key"]: s for s in (await admin.get(_api("/admin/settings"))).json()}
    return int(settings["taxonomy.version"]["value"])


async def test_new_facet_appears_at_once_and_bumps_the_version(admin: httpx.AsyncClient) -> None:
    before = await _version(admin)
    body = {"key": "enforcement_body", "label": "Enforcement body", "value_type": "term",
            "show_in_view_selector": True}  # fmt: skip
    created = await admin.post(_api("/taxonomy/facets"), json=body)
    assert created.status_code == 201, created.text
    assert created.json()["system"] is False and created.json()["terms"] == []
    facets = {f["key"]: f for f in (await admin.get(_api("/taxonomy/facets"))).json()}
    assert "enforcement_body" in facets and facets["topic"]["terms"]
    dims = (await admin.get(_api("/taxonomy/view-dimensions"))).json()
    assert [d["key"] for d in dims][:3] == ["country", "region", "regulation"]
    assert {"key": "enforcement_body", "label": "Enforcement body", "kind": "facet"} in dims
    assert await _version(admin) == before + 1

    hidden = await admin.patch(_api("/taxonomy/facets/enforcement_body"), json={"hidden": True})
    assert hidden.status_code == 200 and hidden.json()["hidden"] is True
    dims = (await admin.get(_api("/taxonomy/view-dimensions"))).json()
    assert "enforcement_body" not in [d["key"] for d in dims]
    assert await _version(admin) == before + 2
    audit = (await admin.get(_api("/admin/audit"), params={"entity_type": "facet"})).json()
    assert [r["action"] for r in audit["items"]] == ["facet.update", "facet.create"]
    assert audit["items"][0]["before"]["hidden"] is False


async def test_facet_rules(admin: httpx.AsyncClient) -> None:
    post = lambda body: admin.post(_api("/taxonomy/facets"), json=body)  # noqa: E731
    assert (await post({"key": "region", "label": "R", "value_type": "term"})).status_code == 422
    assert (await post({"key": "x", "label": "X", "value_type": "term"})).status_code == 422
    assert (await post({"key": "notes", "value_type": "text"})).status_code == 422
    assert (await post({"key": "topic", "label": "T", "value_type": "term"})).status_code == 409
    assert (await admin.delete(_api("/taxonomy/facets/topic"))).status_code == 409
    change = await admin.patch(_api("/taxonomy/facets/topic"), json={"value_type": "text"})
    assert change.status_code == 422
    assert (
        await admin.patch(_api("/taxonomy/facets/topic"), json={"key": "t2"})
    ).status_code == 422
    assert (
        await admin.patch(_api("/taxonomy/facets/topic"), json={"hidden": True})
    ).status_code == 200
    assert (
        await admin.patch(_api("/taxonomy/facets/nope"), json={"hidden": True})
    ).status_code == 404
    assert (await post({"key": "notes", "label": "Notes", "value_type": "text"})).status_code == 201
    assert (
        await admin.patch(_api("/taxonomy/facets/notes"), json={"label": None})
    ).status_code == 422
    assert (await admin.delete(_api("/taxonomy/facets/notes"))).status_code == 204
    assert (await admin.delete(_api("/taxonomy/facets/notes"))).status_code == 404
    version = await admin.put(_api("/admin/settings/taxonomy.version"), json={"value": 99})
    assert version.status_code == 400


async def test_viewers_read_but_do_not_edit(admin: httpx.AsyncClient) -> None:
    viewer = await _as_new_user(admin, "tv@example.org", ["viewer"])
    assert (await viewer.get(_api("/taxonomy/facets"))).status_code == 200
    assert (await viewer.get(_api("/taxonomy/view-dimensions"))).status_code == 200
    body = {"key": "x_facet", "label": "X", "value_type": "term"}
    assert (await viewer.post(_api("/taxonomy/facets"), json=body)).status_code == 403
    await viewer.aclose()
