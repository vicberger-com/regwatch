"""Saved views (M5 interfaces; Q3): own and shared views, curation, one default per user."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.models import AuditLog
from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import ORIGIN, clear_limits, db_url
from tests.integration.test_capture_runs import db

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db", "db_url"]  # shared fixtures

VIEW = {"name": "EU data protection", "view_by": "country", "period_days": 30,
        "color_scheme": "severity", "q": "NIS2",
        "filters": {"regions": ["150"], "terms": {"topic": ["data-protection"]},
                    "changed": {"from": "2026-01-01T00:00:00+00:00"}}}  # fmt: skip


async def user(admin: httpx.AsyncClient, role: str) -> httpx.AsyncClient:
    return await _as_new_user(admin, f"{role}-{uuid.uuid4().hex[:8]}@example.org", [role])


async def test_a_user_keeps_private_views_with_one_default(admin: httpx.AsyncClient) -> None:
    alice, bob = await user(admin, "viewer"), await user(admin, "viewer")
    try:
        made = await alice.post(_api("/views"), json={**VIEW, "is_default": True})
        assert made.status_code == 201, made.text
        view = made.json()
        assert (view["q"], view["shared"], view["is_default"]) == ("NIS2", False, True)
        assert view["filters"]["regions"] == ["150"] and "_q" not in view["filters"]
        assert view["filters"]["changed"]["from"].startswith("2026-01-01")
        second = (
            await alice.post(_api("/views"), json={**VIEW, "name": "Two", "is_default": True})
        ).json()
        listed = {v["name"]: v for v in (await alice.get(_api("/views"))).json()}
        assert (listed["EU data protection"]["is_default"], listed["Two"]["is_default"]) == (
            False, True)  # fmt: skip
        assert view["id"] not in {v["id"] for v in (await bob.get(_api("/views"))).json()}
        for call in (bob.patch(_api(f"/views/{view['id']}"), json={"name": "mine"}),
                     bob.delete(_api(f"/views/{view['id']}"))):  # fmt: skip
            assert (await call).status_code == 404  # another's private view: not told it exists
        renamed = await alice.patch(_api(f"/views/{second['id']}"),
                                    json={"name": "Renamed", "q": ""})  # fmt: skip
        assert renamed.status_code == 200 and renamed.json()["q"] is None
        assert renamed.json()["filters"]["regions"] == ["150"]
        assert (await alice.delete(_api(f"/views/{second['id']}"))).status_code == 204
        assert (await alice.delete(_api(f"/views/{second['id']}"))).status_code == 404
    finally:
        await alice.aclose()
        await bob.aclose()


async def test_shared_views_need_curation_and_are_audited(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    viewer, editor = await user(admin, "viewer"), await user(admin, "editor")
    try:
        refused = await viewer.post(_api("/views"), json={**VIEW, "shared": True})
        assert refused.status_code == 403
        own = (await viewer.post(_api("/views"), json=VIEW)).json()
        assert (
            await viewer.patch(_api(f"/views/{own['id']}"), json={"shared": True})
        ).status_code == 403
        shared = await editor.post(_api("/views"), json={**VIEW, "name": "Team", "shared": True})
        assert shared.status_code == 201 and shared.json()["user_id"] is None
        sid = shared.json()["id"]
        assert sid in {v["id"] for v in (await viewer.get(_api("/views"))).json()}
        for call in (viewer.patch(_api(f"/views/{sid}"), json={"name": "x"}),
                     viewer.delete(_api(f"/views/{sid}"))):  # fmt: skip
            assert (await call).status_code == 403
        assert (
            await editor.patch(_api(f"/views/{sid}"), json={"name": "Team 2"})
        ).status_code == 200
        assert (await editor.delete(_api(f"/views/{sid}"))).status_code == 204
        actions = (await db.scalars(select(AuditLog.action).where(AuditLog.entity_id == sid))).all()
        assert sorted(actions) == ["saved_view.create", "saved_view.delete", "saved_view.update"]
    finally:
        await viewer.aclose()
        await editor.aclose()


@pytest.mark.parametrize(
    "body",
    [{"view_by": "country"}, {**VIEW, "name": "  "}, {**VIEW, "view_by": "no-such-facet"},
     {**VIEW, "period_days": 0}, {**VIEW, "color_scheme": "rainbow"}, {**VIEW, "q": "x" * 501},
     {**VIEW, "filters": {"jurisdictions": [f"J{n}" for n in range(51)]}},
     {**VIEW, "name": "x" * 121}],
)  # fmt: skip
async def test_bad_views_are_refused(admin: httpx.AsyncClient, body: dict[str, Any]) -> None:
    assert (await admin.post(_api("/views"), json=body)).status_code == 422


async def test_an_anonymous_caller_has_no_views(admin: httpx.AsyncClient) -> None:
    anonymous = httpx.AsyncClient(transport=admin._transport, base_url="https://localhost",
                                  headers=ORIGIN)  # fmt: skip
    async with anonymous:
        assert (await anonymous.get(_api("/views"))).status_code == 401
        assert (await anonymous.post(_api("/views"), json=VIEW)).status_code == 401
