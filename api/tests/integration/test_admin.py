"""Integration: user, role, setting, flag, branding and audit administration (#32; M1
acceptance 2 and 5; REQ-16)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from regwatch.api.app import API_PREFIX, create_app
from regwatch.core.settings import Settings
from tests.integration.test_auth import ADMIN_PW, ORIGIN, _login, clear_limits, db_url

pytestmark = pytest.mark.integration
__all__ = ["clear_limits", "db_url"]  # fixtures shared with test_auth


@pytest.fixture
async def admin(db_url: str) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(Settings()))
    async with httpx.AsyncClient(transport=transport, base_url="https://localhost",
                                 headers=ORIGIN) as c:  # fmt: skip
        assert (await _login(c, "admin@example.org", ADMIN_PW)).status_code == 200
        yield c


def _api(path: str) -> str:
    return API_PREFIX + path


async def test_admin_creates_user_who_must_change_password(admin: httpx.AsyncClient) -> None:
    body = {"email": "ana@example.org", "display_name": "Ana", "roles": ["analyst"]}
    created = await admin.post(_api("/admin/users"), json=body)
    assert created.status_code == 201, created.text
    user = created.json()
    assert user["must_change_password"] is True and user["roles"] == ["analyst"]
    temporary = user["temporary_password"]
    assert (await admin.post(_api("/admin/users"), json=body)).status_code == 409
    bad = {**body, "email": "x@example.org", "roles": ["nosuch"]}
    assert (await admin.post(_api("/admin/users"), json=bad)).status_code == 422

    transport = admin._transport
    async with httpx.AsyncClient(transport=transport, base_url="https://localhost",
                                 headers=ORIGIN) as ana:  # fmt: skip
        assert (await _login(ana, "ana@example.org", temporary)).status_code == 200
        assert (await ana.get(_api("/sources"))).status_code == 403  # change first
        change = {"current_password": temporary, "new_password": "ana's own passphrase"}
        assert (await ana.post(_api("/auth/password"), json=change)).status_code == 204
        me = (await ana.get(_api("/auth/me"))).json()
        assert "reports.build" in me["permissions"] and "users.manage" not in me["permissions"]
        assert (await ana.get(_api("/admin/users"))).status_code == 403

        # Role change applies on the next request; admin reset ends Ana's sessions.
        await admin.patch(_api(f"/admin/users/{user['id']}"), json={"roles": ["viewer"]})
        me = (await ana.get(_api("/auth/me"))).json()
        assert me["roles"] == ["viewer"]
        reset = await admin.post(_api(f"/admin/users/{user['id']}/reset-password"))
        assert reset.status_code == 200 and reset.json()["temporary_password"] != temporary
        assert (await ana.get(_api("/auth/me"))).status_code == 401

    page = (await admin.get(_api("/admin/users"), params={"q": "ana", "page_size": 1})).json()
    assert page["total"] == 1 and page["items"][0]["email"] == "ana@example.org"
    assert (await admin.get(_api("/admin/users"), params={"q": "%"})).json()["total"] == 0


async def test_audit_viewer_filters_and_pages(admin: httpx.AsyncClient) -> None:
    body = {"email": "bo@example.org", "display_name": "Bo", "roles": ["viewer"]}
    user = (await admin.post(_api("/admin/users"), json=body)).json()
    await admin.patch(_api(f"/admin/users/{user['id']}"), json={"display_name": "Bo B"})
    query = {"entity_type": "user", "entity_id": user["id"], "action": "user.update"}
    page = (await admin.get(_api("/admin/audit"), params=query)).json()
    assert page["total"] == 1
    row = page["items"][0]
    assert row["before"]["display_name"] == "Bo" and row["after"]["display_name"] == "Bo B"
    assert row["actor_email"] == "admin@example.org" and row["request_id"]
    everything = (await admin.get(_api("/admin/audit"), params={"page_size": 1})).json()
    assert everything["total"] > 1 and len(everything["items"]) == 1
    future = {"from": "2999-01-01T00:00:00Z"}
    assert (await admin.get(_api("/admin/audit"), params=future)).json()["total"] == 0
    me = (await admin.get(_api("/auth/me"))).json()
    by_me = {"actor": me["id"], "to": "2999-01-01T00:00:00Z"}
    mine = (await admin.get(_api("/admin/audit"), params=by_me)).json()
    assert mine["total"] >= 3


async def test_role_change_is_audited_with_before_and_after(admin: httpx.AsyncClient) -> None:
    roles = {r["key"]: r for r in (await admin.get(_api("/admin/roles"))).json()}
    viewer = roles["viewer"]
    perms = sorted({*viewer["permissions"], "outputs.csv"})
    resp = await admin.patch(_api(f"/admin/roles/{viewer['id']}"), json={"permissions": perms})
    assert resp.status_code == 200 and resp.json()["permissions"] == perms
    query = {"entity_type": "role", "action": "role.update"}
    audit = (await admin.get(_api("/admin/audit"), params=query)).json()
    assert audit["total"] == 1
    row = audit["items"][0]
    assert "outputs.csv" not in row["before"]["permissions"]
    assert "outputs.csv" in row["after"]["permissions"]
    assert row["actor_email"] == "admin@example.org"


async def test_role_lifecycle_and_guards(admin: httpx.AsyncClient) -> None:
    auditor = {"key": "auditor", "label": "Auditor", "permissions": ["audit.read"]}
    created = await admin.post(_api("/admin/roles"), json=auditor)
    assert created.status_code == 201
    role_id = created.json()["id"]
    dup = await admin.post(_api("/admin/roles"), json={"key": "auditor", "label": "Again"})
    assert dup.status_code == 422
    bad_perm = {"key": "x_role", "label": "X", "permissions": ["no.such"]}
    unknown = await admin.post(_api("/admin/roles"), json=bad_perm)
    assert unknown.status_code == 422
    body = {"email": "aud@example.org", "display_name": "Aud", "roles": ["auditor"]}
    user = (await admin.post(_api("/admin/users"), json=body)).json()
    assert (await admin.delete(_api(f"/admin/roles/{role_id}"))).status_code == 409
    await admin.patch(_api(f"/admin/users/{user['id']}"), json={"roles": []})
    assert (await admin.delete(_api(f"/admin/roles/{role_id}"))).status_code == 204
    roles = {r["key"]: r for r in (await admin.get(_api("/admin/roles"))).json()}
    assert (await admin.delete(_api(f"/admin/roles/{roles['viewer']['id']}"))).status_code == 409
    strip = await admin.patch(_api(f"/admin/roles/{roles['admin']['id']}"),
                              json={"permissions": ["items.read"]})  # fmt: skip
    assert strip.status_code == 422
    perms = (await admin.get(_api("/admin/permissions"))).json()
    assert len(perms) == 23 and perms[0]["key"] == "audit.read"


async def test_last_manager_cannot_be_removed(admin: httpx.AsyncClient) -> None:
    me = (await admin.get(_api("/auth/me"))).json()
    resp = await admin.patch(_api(f"/admin/users/{me['id']}"), json={"roles": ["viewer"]})
    assert resp.status_code == 422
    resp = await admin.patch(_api(f"/admin/users/{me['id']}"), json={"status": "disabled"})
    assert resp.status_code == 422
    assert (await admin.get(_api("/auth/me"))).json()["roles"] == ["admin"]


async def test_disable_and_unlock(admin: httpx.AsyncClient) -> None:
    users = (await admin.get(_api("/admin/users"), params={"q": "viewer"})).json()["items"]
    viewer_id = users[0]["id"]
    off = await admin.patch(_api(f"/admin/users/{viewer_id}"), json={"status": "disabled"})
    assert off.json()["status"] == "disabled"
    on = await admin.patch(_api(f"/admin/users/{viewer_id}"), json={"status": "active"})
    assert on.json()["status"] == "active"
    assert (await admin.get(_api(f"/admin/users/{viewer_id}"))).status_code == 200
    missing = "01900000-0000-7000-8000-000000000000"
    assert (await admin.get(_api(f"/admin/users/{missing}"))).status_code == 404


async def test_settings_validation_and_hosted_basis(admin: httpx.AsyncClient) -> None:
    listed = {s["key"]: s for s in (await admin.get(_api("/admin/settings"))).json()}
    assert listed["map.projection"]["values"] == ["equal-earth", "mercator"]
    put = await admin.put(_api("/admin/settings/map.projection"), json={"value": "mercator"})
    assert put.status_code == 200 and put.json()["value"] == "mercator"
    for key, value in (("map.projection", "robinson"), ("auth.password_min_length", 8),
                       ("auth.lockout_threshold", True), ("general.site_title", 5)):  # fmt: skip
        resp = await admin.put(_api(f"/admin/settings/{key}"), json={"value": value})
        assert resp.status_code == 400, key
    assert (await admin.put(_api("/admin/settings/no.such"), json={"value": 1})).status_code == 404
    hosted = await admin.put(_api("/admin/settings/translation.provider"), json={"value": "http"})
    assert hosted.status_code == 400
    basis = {"value": "Contract with provider, 2026-11"}
    assert (await admin.put(_api("/admin/settings/translation.data_processing_basis"),
                            json=basis)).status_code == 200  # fmt: skip
    hosted = await admin.put(_api("/admin/settings/translation.provider"), json={"value": "http"})
    assert hosted.status_code == 200
    empty = await admin.put(_api("/admin/settings/translation.data_processing_basis"),
                            json={"value": " "})  # fmt: skip
    assert empty.status_code == 400


async def test_feature_flags(admin: httpx.AsyncClient) -> None:
    flags = {f["key"]: f for f in (await admin.get(_api("/admin/feature-flags"))).json()}
    assert flags["reports.builder"]["enabled"] is True
    resp = await admin.patch(_api("/admin/feature-flags/search.internet"), json={"enabled": True})
    assert resp.status_code == 200 and resp.json()["enabled"] is True
    missing = await admin.patch(_api("/admin/feature-flags/no.such"), json={"enabled": True})
    assert missing.status_code == 404
    audit = await admin.get(_api("/admin/audit"), params={"action": "feature_flag.update"})
    assert audit.json()["items"][0]["after"] == {"enabled": True}


async def test_branding_and_legal_text(admin: httpx.AsyncClient) -> None:
    body = {"site_title": "Policy Watch", "company_name": "Example Ltd", "primary_color": "#123abc"}
    resp = await admin.put(_api("/admin/branding"), json=body)
    assert resp.status_code == 200
    brand = (await admin.get(_api("/branding"))).json()
    assert brand["site_title"] == "Policy Watch" and brand["primary_color"] == "#123abc"
    bad = await admin.put(_api("/admin/branding"), json={"primary_color": "red"})
    assert bad.status_code == 422
    clear = await admin.put(_api("/admin/branding"), json={"primary_color": None})
    assert clear.json()["primary_color"] is None
    legal = {"page_markdown": "# Notices", "required_markings": "INTERNAL"}
    assert (await admin.put(_api("/admin/legal"), json=legal)).status_code == 204
    assert (await admin.get(_api("/branding"))).json()["required_markings"] == "INTERNAL"
    page = (await admin.get(_api("/admin/audit"), params={"entity_type": "setting",
                                                          "page_size": 2})).json()  # fmt: skip
    assert page["total"] >= 4 and len(page["items"]) == 2
