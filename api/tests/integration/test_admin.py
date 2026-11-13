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
