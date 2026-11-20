"""Integration: groups of users and their roles (CP-27, ADR-0012, M11.4)."""

from __future__ import annotations

import httpx
import pytest

from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import clear_limits, db_url

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db_url"]  # shared fixtures

TEAM = {"key": "eu-policy", "name": "EU policy team", "roles": ["analyst"]}


async def _perms(client: httpx.AsyncClient) -> set[str]:
    return set((await client.get(_api("/auth/me"))).json()["permissions"])


async def test_members_get_the_groups_roles(admin: httpx.AsyncClient) -> None:
    viewer = await _as_new_user(admin, "gina@example.org", ["viewer"])
    vid = (await viewer.get(_api("/auth/me"))).json()["id"]
    assert "reports.build" not in await _perms(viewer)
    made = await admin.post(_api("/admin/groups"), json=TEAM)
    assert made.status_code == 201, made.text
    gid = made.json()["id"]
    assert (made.json()["roles"], made.json()["members"]) == (["analyst"], [])

    assert (await admin.put(_api(f"/admin/groups/{gid}/members/{vid}"))).status_code == 204
    assert (await admin.put(_api(f"/admin/groups/{gid}/members/{vid}"))).status_code == 204
    assert "reports.build" in await _perms(viewer)  # at once, on the next request
    me = (await viewer.get(_api("/auth/me"))).json()
    assert set(me["roles"]) == {"viewer", "analyst"}
    listed = (await admin.get(_api("/admin/groups"))).json()
    assert [(g["key"], g["members"]) for g in listed] == [("eu-policy", [vid])]

    renamed = await admin.patch(_api(f"/admin/groups/{gid}"),
                                json={"name": "EU team", "roles": ["editor"]})  # fmt: skip
    assert renamed.status_code == 200 and renamed.json()["roles"] == ["editor"]
    assert "sources.manage" in await _perms(viewer)
    assert (await admin.delete(_api(f"/admin/groups/{gid}/members/{vid}"))).status_code == 204
    assert "sources.manage" not in await _perms(viewer)
    assert (await admin.delete(_api(f"/admin/groups/{gid}"))).status_code == 204
    rows = (await admin.get(_api("/admin/audit"), params={"entity_type": "user_group"})).json()
    assert [r["action"] for r in rows["items"]] == [
        "group.delete", "group.member_remove", "group.update", "group.member_add",
        "group.create",
    ]  # fmt: skip
    await viewer.aclose()


async def test_groups_never_hand_out_administration(admin: httpx.AsyncClient) -> None:
    """A group cannot carry users.manage or roles.manage, nor a role later given them."""
    refused = await admin.post(_api("/admin/groups"), json={**TEAM, "roles": ["admin"]})
    assert refused.status_code == 422 and "users.manage" in refused.text
    role = await admin.post(_api("/admin/roles"), json={
        "key": "readers", "label": "Readers", "permissions": ["items.read"]})  # fmt: skip
    rid = role.json()["id"]
    gid = (await admin.post(_api("/admin/groups"),
                            json={**TEAM, "roles": ["readers"]})).json()["id"]  # fmt: skip
    widened = await admin.patch(_api(f"/admin/roles/{rid}"),
                                json={"permissions": ["items.read", "roles.manage"]})  # fmt: skip
    assert widened.status_code == 422 and "groups hold" in widened.text
    assert (await admin.delete(_api(f"/admin/roles/{rid}"))).status_code == 409
    assert (await admin.delete(_api(f"/admin/groups/{gid}"))).status_code == 204
    assert (await admin.delete(_api(f"/admin/roles/{rid}"))).status_code == 204


async def test_an_administrator_grants_only_what_they_hold(admin: httpx.AsyncClient) -> None:
    keeper = await admin.post(_api("/admin/roles"), json={
        "key": "keeper", "label": "Keeper", "permissions": ["users.manage"]})  # fmt: skip
    assert keeper.status_code == 201, keeper.text
    manager = await _as_new_user(admin, "kim@example.org", ["keeper"])
    viewer = await _as_new_user(admin, "lou@example.org", ["viewer"])
    vid = (await viewer.get(_api("/auth/me"))).json()["id"]
    assert (await manager.post(_api("/admin/groups"), json=TEAM)).status_code == 403
    gid = (await admin.post(_api("/admin/groups"), json=TEAM)).json()["id"]
    assert (await manager.put(_api(f"/admin/groups/{gid}/members/{vid}"))).status_code == 403
    assert (await admin.put(_api(f"/admin/groups/{gid}/members/{vid}"))).status_code == 204
    assert (await manager.delete(_api(f"/admin/groups/{gid}/members/{vid}"))).status_code == 403
    assert (await manager.patch(_api(f"/admin/groups/{gid}"),
                                json={"roles": []})).status_code == 403  # fmt: skip
    assert (await manager.delete(_api(f"/admin/groups/{gid}"))).status_code == 403
    plain = await manager.post(_api("/admin/groups"), json={"key": "plain", "name": "Plain"})
    assert plain.status_code == 201  # a group with no roles needs nothing more
    await manager.aclose()
    await viewer.aclose()


async def test_groups_are_checked(admin: httpx.AsyncClient) -> None:
    assert (await admin.post(_api("/admin/groups"), json={**TEAM, "key": "Bad Key"})
            ).status_code == 422  # fmt: skip
    assert (await admin.post(_api("/admin/groups"), json={**TEAM, "roles": ["nosuch"]})
            ).status_code == 422  # fmt: skip
    assert (await admin.post(_api("/admin/groups"), json={**TEAM, "name": "  "})
            ).status_code == 422  # fmt: skip
    gid = (await admin.post(_api("/admin/groups"), json=TEAM)).json()["id"]
    assert (await admin.post(_api("/admin/groups"), json=TEAM)).status_code == 409
    nobody = "00000000-0000-7000-8000-000000000000"
    assert (await admin.put(_api(f"/admin/groups/{gid}/members/{nobody}"))).status_code == 404
    assert (await admin.put(_api(f"/admin/groups/{nobody}/members/{nobody}"))).status_code == 404
    viewer = await _as_new_user(admin, "may@example.org", ["viewer"])
    assert (await viewer.get(_api("/admin/groups"))).status_code == 403
    await viewer.aclose()
