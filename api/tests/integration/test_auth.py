"""Integration: login, lockout, logout and sessions against PostgreSQL (#31; M1 acceptance
2, 3 and 4; REQ-14, REQ-16)."""

from __future__ import annotations

import asyncio
import io
import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from regwatch.api.app import API_PREFIX, create_app
from regwatch.core import seed
from regwatch.core.db import create_engine, session_factory
from regwatch.core.settings import Settings, get_settings
from regwatch.identity import admin_cli, services
from tests.integration.conftest import Postgres, upgrade

pytestmark = pytest.mark.integration

SEED_DIR = Path(__file__).resolve().parents[2] / "seed"
ORIGIN = {"origin": "http://localhost"}
ADMIN_PW = "admin password 1234"
VIEWER_PW = "viewer password 1234"


@pytest.fixture(autouse=True)
def clear_limits() -> Iterator[None]:
    services.login_attempts.clear()
    services.unknown_failures.clear()
    services.unknown_locks.clear()
    yield


@pytest.fixture
def db_url(
    postgres: Postgres, empty_db: str, valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> str:
    url = postgres.url(empty_db)
    upgrade(url)
    asyncio.run(seed.run(SEED_DIR, url))
    monkeypatch.setenv("REGWATCH_DATABASE_URL", url)
    get_settings.cache_clear()
    for args, pw in (
        (["--email", "admin@example.org", "--name", "Admin"], ADMIN_PW),
        (["--email", "viewer@example.org", "--name", "Viewer", "--role", "viewer",
          "--temporary"], VIEWER_PW),
    ):  # fmt: skip
        monkeypatch.setattr("sys.stdin", io.StringIO(pw + "\n"))
        assert admin_cli.main(["create-user", *args, "--password-stdin"]) == 0
    return url


@pytest.fixture
async def client(db_url: str) -> AsyncIterator[httpx.AsyncClient]:
    app: FastAPI = create_app(Settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://localhost") as c:
        yield c


async def _login(c: httpx.AsyncClient, email: str, pw: str) -> httpx.Response:
    return await c.post(f"{API_PREFIX}/auth/login", json={"email": email, "password": pw},
                        headers=ORIGIN)  # fmt: skip


async def _audit(url: str, action: str) -> list[dict[str, object]]:
    from sqlalchemy import select

    from regwatch.core.models import AuditLog

    engine = create_engine(url, poolclass_null=True)
    async with session_factory(engine)() as db:
        rows = await db.scalars(select(AuditLog).where(AuditLog.action == action))
        out = [{"entity_id": r.entity_id, "after": r.after, "actor": r.actor_user_id}
               for r in rows.all()]  # fmt: skip
    await engine.dispose()
    return out


async def test_admin_login_cookie_and_me(client: httpx.AsyncClient, db_url: str) -> None:
    resp = await _login(client, "ADMIN@example.org", ADMIN_PW)
    assert resp.status_code == 200, resp.text
    cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert "max-age" not in cookie  # not remember_me: a browser-session cookie
    me = (await client.get(f"{API_PREFIX}/auth/me")).json()
    assert me["roles"] == ["admin"] and "users.manage" in me["permissions"]
    assert (await client.get(f"{API_PREFIX}/admin/users")).status_code == 200
    assert len(await _audit(db_url, "auth.login")) == 1


async def test_temporary_password_then_viewer_is_denied_admin(client: httpx.AsyncClient) -> None:
    assert (await _login(client, "viewer@example.org", VIEWER_PW)).status_code == 200
    resp = await client.get(f"{API_PREFIX}/jurisdictions")
    assert resp.json()["type"].endswith("/password-change-required")
    change = f"{API_PREFIX}/auth/password"
    same = {"current_password": VIEWER_PW, "new_password": VIEWER_PW}
    bad = await client.post(change, headers=ORIGIN, json=same)
    assert bad.status_code == 400
    old_cookie = client.cookies["rw_session"]
    new = {"current_password": VIEWER_PW, "new_password": "a new pass 5678"}
    ok = await client.post(change, headers=ORIGIN, json=new)
    assert ok.status_code == 204
    assert client.cookies["rw_session"] != old_cookie  # rotated
    assert (await client.get(f"{API_PREFIX}/jurisdictions")).status_code == 501
    # Acceptance 1: a viewer gets 403 on every admin route, even with a crafted request.
    admin_routes = [("GET", "/admin/users"), ("GET", "/admin/audit"), ("GET", "/admin/settings"),
                    ("PATCH", "/admin/feature-flags/auth.oidc")]  # fmt: skip
    for method, path in admin_routes:
        resp = await client.request(method, API_PREFIX + path, headers=ORIGIN, json={})
        assert resp.status_code == 403, (method, path)
    stale = httpx.Cookies({"rw_session": old_cookie})
    client.cookies = stale
    assert (await client.get(f"{API_PREFIX}/auth/me")).status_code == 401


async def test_ten_failures_lock_without_revealing_the_email(
    client: httpx.AsyncClient, db_url: str
) -> None:
    statuses, unknown = [], []
    for _ in range(10):
        services.login_attempts.clear()  # the 5-per-minute limit is tested separately
        statuses.append((await _login(client, "admin@example.org", "wrong password!!")).status_code)
        unknown.append((await _login(client, "nobody@example.org", "wrong password!!")).status_code)
    assert statuses == [401] * 9 + [423]
    assert unknown == statuses  # same answers for an email that does not exist
    services.login_attempts.clear()
    assert (await _login(client, "admin@example.org", ADMIN_PW)).status_code == 423
    locked = await _audit(db_url, "auth.locked")
    assert len(locked) == 1 and locked[0]["after"]["status"] == "locked"  # type: ignore[index]
    failed = await _audit(db_url, "auth.login_failed")
    assert len(failed) == 20
    assert "nobody@example.org" not in json.dumps([f["after"] for f in failed])


async def test_concurrent_bursts_still_lock(client: httpx.AsyncClient) -> None:
    """Review finding 1: parallel wrong passwords each count toward the lockout."""
    codes: list[int] = []
    for _ in range(2):
        services.login_attempts.clear()
        burst = [_login(client, "admin@example.org", "wrong password!!") for _ in range(5)]
        codes += [r.status_code for r in await asyncio.gather(*burst)]
    assert codes.count(423) == 1 and codes.count(401) == 9
    services.login_attempts.clear()
    assert (await _login(client, "admin@example.org", ADMIN_PW)).status_code == 423


async def test_locked_answers_cost_the_same_and_last_as_long(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding 4: real and unknown locks run Argon2 and both last lockout_minutes."""
    for _ in range(10):
        services.login_attempts.clear()
        await _login(client, "admin@example.org", "wrong password!!")
        await _login(client, "nobody@example.org", "wrong password!!")
    calls: list[str | None] = []
    real_verify = services.security.verify_password_async

    async def counting(stored: str | None, password: str) -> bool:
        calls.append(stored)
        return await real_verify(stored, password)

    monkeypatch.setattr(services.security, "verify_password_async", counting)
    later = services.time.monotonic() + 16 * 60  # past the 15-minute failure window
    monkeypatch.setattr(services.time, "monotonic", lambda: later)
    for email in ("admin@example.org", "nobody@example.org"):
        services.login_attempts.clear()
        assert (await _login(client, email, "wrong password!!")).status_code == 423
    assert calls == [None, None]


async def test_lock_ends_existing_sessions(client: httpx.AsyncClient) -> None:
    """Review finding 12d: a locked account keeps no live session."""
    assert (await _login(client, "admin@example.org", ADMIN_PW)).status_code == 200
    token = client.cookies["rw_session"]
    for _ in range(10):
        services.login_attempts.clear()
        await _login(client, "admin@example.org", "wrong password!!")
    client.cookies = httpx.Cookies({"rw_session": token})
    assert (await client.get(f"{API_PREFIX}/auth/me")).status_code == 401


async def test_rate_limit_answers_429(client: httpx.AsyncClient) -> None:
    codes = [(await _login(client, "admin@example.org", "nope nope nope")).status_code
             for _ in range(6)]  # fmt: skip
    assert codes[:5] == [401] * 5 and codes[5] == 429


async def test_logout_revokes_and_replay_is_401(client: httpx.AsyncClient, db_url: str) -> None:
    await _login(client, "admin@example.org", ADMIN_PW)
    token = client.cookies["rw_session"]
    assert (await client.post(f"{API_PREFIX}/auth/logout")).status_code == 403  # no Origin
    assert (await client.post(f"{API_PREFIX}/auth/logout", headers=ORIGIN)).status_code == 204
    client.cookies = httpx.Cookies({"rw_session": token})
    assert (await client.get(f"{API_PREFIX}/auth/me")).status_code == 401
    assert len(await _audit(db_url, "auth.logout")) == 1


async def test_sessions_list_and_revoke(client: httpx.AsyncClient, db_url: str) -> None:
    await _login(client, "admin@example.org", ADMIN_PW)
    first = client.cookies["rw_session"]
    client.cookies = httpx.Cookies()
    await _login(client, "admin@example.org", ADMIN_PW)
    sessions = (await client.get(f"{API_PREFIX}/me/sessions")).json()
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    other = next(s["id"] for s in sessions if not s["current"])
    resp = await client.delete(f"{API_PREFIX}/me/sessions/{other}", headers=ORIGIN)
    assert resp.status_code == 204
    again = await client.delete(f"{API_PREFIX}/me/sessions/{other}", headers=ORIGIN)
    assert again.status_code == 404
    client.cookies = httpx.Cookies({"rw_session": first})
    assert (await client.get(f"{API_PREFIX}/auth/me")).status_code == 401


def test_admin_cli_rejects_short_password_and_duplicates(
    db_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    args = ["create-user", "--email", "x@example.org", "--name", "X", "--password-stdin"]
    assert admin_cli.main(args) == 1
    monkeypatch.setattr("sys.stdin", io.StringIO(ADMIN_PW + "\n"))
    dup = ["create-user", "--email", "admin@example.org", "--name", "A", "--password-stdin"]
    assert admin_cli.main(dup) == 1
    monkeypatch.setattr("sys.stdin", io.StringIO(ADMIN_PW + "\n"))
    assert admin_cli.main([*args[:-1], "--role", "nosuch", "--password-stdin"]) == 1
    assert "unknown roles" in capsys.readouterr().err


async def test_nul_in_login_email_is_422_and_not_logged(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Review finding 7: database input errors are 422, and bound values stay out of logs."""
    resp = await _login(client, "vic\u0000tim@example.org", "whatever password")
    assert resp.status_code == 422
    assert "tim@example.org" not in caplog.text


def test_admin_cli_rejects_invalid_email(
    db_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(ADMIN_PW + "\n"))
    args = ["create-user", "--email", "nope", "--name", "N", "--password-stdin"]
    assert admin_cli.main(args) == 1
    assert "email" in capsys.readouterr().err
