"""M9 preferences: ``GET|PATCH /me/preferences`` (acceptance 1: they follow the user)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from tests.integration.test_admin import _api, _as_new_user, _login, admin
from tests.integration.test_auth import ORIGIN, clear_limits, db_url
from tests.integration.test_capture_runs import db

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db", "db_url"]


async def viewer(admin: httpx.AsyncClient) -> tuple[httpx.AsyncClient, str]:
    email = f"prefs-{uuid.uuid4().hex[:8]}@example.org"
    return await _as_new_user(admin, email, ["viewer"]), email


async def test_preferences_default_merge_and_follow_the_user(admin: httpx.AsyncClient) -> None:
    alice, email = await viewer(admin)
    try:
        got = (await alice.get(_api("/me/preferences"))).json()
        assert (got["theme"], got["font_scale"], got["density"], got["locale"]) == (
            "system", 100, "default", "en")  # fmt: skip
        assert got["session_idle_timeout_minutes"] == 480  # the admin ceiling by default
        changed = await alice.patch(_api("/me/preferences"),
                                    json={"theme": "high-contrast", "font_scale": 125})  # fmt: skip
        assert changed.status_code == 200, changed.text
        more = await alice.patch(_api("/me/preferences"),
                                 json={"density": "compact", "timezone": "Europe/Berlin",
                                       "session_idle_timeout_minutes": 20})  # fmt: skip
        body = more.json()
        assert (body["theme"], body["font_scale"], body["density"]) == ("high-contrast", 125,
                                                                         "compact")  # fmt: skip
        assert (body["timezone"], body["session_idle_timeout_minutes"]) == ("Europe/Berlin", 20)
        # Another device: a new session sees the same preferences, and so does /auth/me.
        other = httpx.AsyncClient(transport=admin._transport, base_url="https://localhost",
                                  headers=ORIGIN)  # fmt: skip
        try:
            assert (await _login(other, email, "a long new passphrase")).status_code == 200
            again = (await other.get(_api("/me/preferences"))).json()
            assert (again["theme"], again["density"]) == ("high-contrast", "compact")
            me = (await other.get(_api("/auth/me"))).json()
            assert me["preferences"]["font_scale"] == 125
        finally:
            await other.aclose()
    finally:
        await alice.aclose()


@pytest.mark.parametrize("body", [
    {"timezone": "Mars/Olympus"}, {"locale": "de"}, {"session_idle_timeout_minutes": 481},
    {"session_idle_timeout_minutes": 5}, {"theme": "neon"}, {"font_scale": 300},
    {"landing_view_id": str(uuid.uuid4())},
])  # fmt: skip
async def test_bad_preferences_are_refused(admin: httpx.AsyncClient, body: dict[str, Any]) -> None:
    alice, _ = await viewer(admin)
    try:
        got = await alice.patch(_api("/me/preferences"), json=body)
        assert got.status_code in (400, 422), got.text
        assert (await alice.get(_api("/me/preferences"))).json()["theme"] == "system"
    finally:
        await alice.aclose()


async def test_the_landing_view_must_be_one_the_user_can_see(admin: httpx.AsyncClient) -> None:
    alice, _ = await viewer(admin)
    bob, _ = await viewer(admin)
    try:
        view = {"name": "Mine", "view_by": "country", "period_days": 30, "color_scheme": "recency",
                "filters": {}}  # fmt: skip
        own = (await alice.post(_api("/views"), json=view)).json()["id"]
        theirs = (await bob.post(_api("/views"), json=view)).json()["id"]
        assert (await alice.patch(_api("/me/preferences"),
                                  json={"landing_view_id": own})).status_code == 200  # fmt: skip
        refused = await alice.patch(_api("/me/preferences"), json={"landing_view_id": theirs})
        assert refused.status_code == 400  # another user's private view
        assert (await alice.get(_api("/me/preferences"))).json()["landing_view_id"] == own
        cleared = await alice.patch(_api("/me/preferences"), json={"landing_view_id": None})
        assert cleared.status_code == 200 and cleared.json()["landing_view_id"] is None
    finally:
        await alice.aclose()
        await bob.aclose()


async def test_unknown_fields_are_not_stored(admin: httpx.AsyncClient) -> None:
    alice, _ = await viewer(admin)
    try:
        got = await alice.patch(_api("/me/preferences"), json={"unknown": 1, "theme": "dark"})
        assert got.status_code == 200 and "unknown" not in got.json()
        assert got.json()["theme"] == "dark"
    finally:
        await alice.aclose()


async def test_a_stored_value_no_longer_valid_falls_back(admin: httpx.AsyncClient,
                                                         db: Any) -> None:  # fmt: skip
    """M9 review info 1: a value a later schema refuses never locks the user out."""
    from sqlalchemy import update

    from regwatch.identity.models import User

    alice, email = await viewer(admin)
    try:
        await db.execute(
            update(User)
            .where(User.email == email)
            .values(preferences={"font_scale": 999, "theme": "dark", "x": 1})
        )
        await db.commit()
        got = await alice.get(_api("/me/preferences"))
        assert got.status_code == 200 and got.json()["font_scale"] == 100
        assert got.json()["theme"] == "dark"
        assert (await alice.get(_api("/auth/me"))).status_code == 200
    finally:
        await alice.aclose()


async def test_anonymous_callers_have_no_preferences(admin: httpx.AsyncClient) -> None:
    anon = httpx.AsyncClient(transport=admin._transport, base_url="https://localhost",
                             headers=ORIGIN)  # fmt: skip
    try:
        assert (await anon.get(_api("/me/preferences"))).status_code == 401
        assert (
            await anon.patch(_api("/me/preferences"), json={"theme": "dark"})
        ).status_code == 401
    finally:
        await anon.aclose()
