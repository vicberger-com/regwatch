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
    assert (await client.get(f"{API_PREFIX}/admin/users")).status_code == 501  # #32 stub
    assert len(await _audit(db_url, "auth.login")) == 1


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
