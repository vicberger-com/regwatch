"""Integration: sign-in with the organisation's account against PostgreSQL and a mock provider
(M1b; ADR-0007 G0 Q1 to Q3; CP-37)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from sqlalchemy import text

from regwatch.api.app import create_app
from regwatch.core.settings import Settings, get_settings
from regwatch.identity import oidc
from tests.integration.test_admin import _api
from tests.integration.test_auth import (
    ADMIN_PW,  # fmt: skip
    ORIGIN,
    VIEWER_PW,
    _audit,
    _login,
    _sql,
    clear_limits,
    db_url,
)
from tests.oidc_provider import Provider, oidc_env

pytestmark = pytest.mark.integration
__all__ = ["clear_limits", "db_url"]


@pytest.fixture
def idp(db_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Provider]:
    for key, value in oidc_env().items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    found = Provider(claims={"email": "viewer@example.org", "name": "Viewer"})
    monkeypatch.setattr(oidc, "transport", found.transport())
    oidc._cache.clear()
    yield found
    oidc._cache.clear()


async def _flag(url: str, on: bool) -> None:
    await _sql(url, f"UPDATE feature_flag SET enabled = {'true' if on else 'false'} "
                    "WHERE key = 'auth.oidc'")  # fmt: skip


@pytest.fixture
async def web(idp: Provider) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(Settings()))
    async with httpx.AsyncClient(transport=transport, base_url="https://localhost",
                                 headers=ORIGIN) as c:  # fmt: skip
        yield c


async def _sign_in(web: httpx.AsyncClient, idp: Provider, next_path: str = "/items",
                   code: str = "code-1") -> httpx.Response:  # fmt: skip
    start = await web.get(_api("/auth/oidc/login"), params={"next": next_path})
    assert start.status_code == 302, start.text
    assert start.headers["cache-control"] == "no-store"
    back = idp.authorize(start.headers["location"], code=code)
    return await web.get(_api("/auth/oidc/callback"), params=back)


async def test_off_by_default(web: httpx.AsyncClient) -> None:
    assert (await web.get(_api("/auth/sso"))).json() == {"enabled": False}
    assert (await web.get(_api("/auth/oidc/login"))).status_code == 404
    assert (await web.get(_api("/auth/oidc/callback"))).status_code == 404


async def test_first_sign_in_links_by_verified_email_then_by_subject(
    web: httpx.AsyncClient, idp: Provider, db_url: str
) -> None:
    await _flag(db_url, True)
    assert (await web.get(_api("/auth/sso"))).json() == {"enabled": True}
    done = await _sign_in(web, idp)
    assert done.status_code == 302 and done.headers["location"] == "/items"
    assert "rw_oidc=" in done.headers.get("set-cookie", "")  # the state cookie is cleared
    me = await web.get(_api("/auth/me"))
    assert me.status_code == 200 and me.json()["email"] == "viewer@example.org"
    linked = await _audit(db_url, "auth.sso_linked")
    assert len(linked) == 1 and "email_sha256" in linked[0]["after"]  # type: ignore[operator]
    logins = await _audit(db_url, "auth.login")
    assert logins[-1]["after"] == {"method": "sso"}
    # Next time by the subject alone, even when the provider's email has changed.
    web.cookies.clear()
    idp.claims = {"email": "renamed@example.org"}
    done = await _sign_in(web, idp, code="code-2")
    assert done.headers["location"] == "/items"
    assert (await web.get(_api("/auth/me"))).json()["email"] == "viewer@example.org"
    stored = await _count(db_url, "SELECT length(external_subject) FROM \"user\" "
                                  "WHERE email = 'viewer@example.org'")  # fmt: skip
    assert stored == 64  # the issuer and subject digest, never the bare subject
    assert len(await _audit(db_url, "auth.sso_linked")) == 1


@pytest.mark.parametrize(("claims", "reason"), [
    ({"email": "nobody@example.org"}, "no_account"),
    ({"email_verified": False}, "no_verified_email"),
    ({"email": None}, "no_verified_email"),
])  # fmt: skip
async def test_unknown_or_unverified_people_are_refused(
    web: httpx.AsyncClient, idp: Provider, db_url: str, claims: dict[str, object], reason: str
) -> None:
    await _flag(db_url, True)
    idp.claims = {**idp.claims, **claims}
    done = await _sign_in(web, idp)
    assert done.headers["location"] == "/login?sso=unknown"
    assert (await web.get(_api("/auth/me"))).status_code == 401
    refused = await _audit(db_url, "auth.sso_refused")
    assert refused[-1]["after"]["reason"] == reason  # type: ignore[index]
    count = await _count(db_url, 'SELECT count(*) FROM "user"')
    assert count == 2  # never a new account


async def _count(url: str, statement: str) -> int:
    from regwatch.core.db import create_engine

    engine = create_engine(url, poolclass_null=True)
    async with engine.connect() as conn:
        value = (await conn.execute(text(statement))).scalar_one()
    await engine.dispose()
    return int(value)


async def test_an_account_linked_to_another_subject_is_not_taken_over(
    web: httpx.AsyncClient, idp: Provider, db_url: str
) -> None:
    await _flag(db_url, True)
    await _sql(db_url, "UPDATE \"user\" SET external_subject = 'someone-else' "
                       "WHERE email = 'viewer@example.org'")  # fmt: skip
    done = await _sign_in(web, idp)
    assert done.headers["location"] == "/login?sso=unknown"
    refused = await _audit(db_url, "auth.sso_refused")
    assert refused[-1]["after"]["reason"] == "linked_elsewhere"  # type: ignore[index]


async def test_an_administrator_is_never_linked_by_email(
    web: httpx.AsyncClient, idp: Provider, db_url: str
) -> None:
    await _flag(db_url, True)
    idp.claims = {"email": "admin@example.org"}
    done = await _sign_in(web, idp)
    assert done.headers["location"] == "/login?sso=unknown"
    refused = await _audit(db_url, "auth.sso_refused")
    assert refused[-1]["after"]["reason"] == "privileged"  # type: ignore[index]
    linked = await _count(db_url, 'SELECT count(*) FROM "user" WHERE external_subject IS NOT NULL')
    assert linked == 0


async def test_a_disabled_account_is_refused(
    web: httpx.AsyncClient, idp: Provider, db_url: str
) -> None:
    await _flag(db_url, True)
    await _sql(db_url, "UPDATE \"user\" SET status = 'disabled' WHERE email = 'viewer@example.org'")
    done = await _sign_in(web, idp)
    assert done.headers["location"] == "/login?sso=inactive"
    assert (await web.get(_api("/auth/me"))).status_code == 401


async def test_a_bad_state_or_a_provider_error_signs_no_one_in(
    web: httpx.AsyncClient, idp: Provider, db_url: str
) -> None:
    await _flag(db_url, True)
    start = await web.get(_api("/auth/oidc/login"))
    back = idp.authorize(start.headers["location"])
    forged = await web.get(_api("/auth/oidc/callback"), params={**back, "state": "x"})
    assert forged.headers["location"] == "/login?sso=state"
    denied = {"error": "access_denied", "state": back["state"]}
    refused = await web.get(_api("/auth/oidc/callback"), params=denied)
    assert refused.headers["location"] == "/login?sso=refused"
    assert (await web.get(_api("/auth/me"))).status_code == 401


async def test_next_never_leaves_the_site(
    web: httpx.AsyncClient, idp: Provider, db_url: str
) -> None:
    await _flag(db_url, True)
    done = await _sign_in(web, idp, next_path="//evil.example/x")
    assert done.headers["location"] == "/"


async def test_with_sso_on_passwords_are_for_administrators_only(
    web: httpx.AsyncClient, idp: Provider, db_url: str
) -> None:
    await _flag(db_url, True)
    viewer = await _login(web, "viewer@example.org", VIEWER_PW)
    assert viewer.status_code == 403 and viewer.json()["type"].endswith("sso-required")
    wrong = await _login(web, "viewer@example.org", "wrong password 1234")
    assert wrong.status_code == 401  # a wrong password still says only that
    assert (await _login(web, "admin@example.org", ADMIN_PW)).status_code == 200
    await _flag(db_url, False)
    web.cookies.clear()
    assert (await _login(web, "viewer@example.org", VIEWER_PW)).status_code == 200
