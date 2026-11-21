"""Integration: two-factor sign-in with TOTP against PostgreSQL (BL-148; ADR-0007 G0 Q4; CP-38)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

import httpx
import pyotp
import pytest

from regwatch.api.app import create_app
from regwatch.core.settings import Settings
from regwatch.identity import mfa
from tests.integration.test_admin import _api
from tests.integration.test_auth import ADMIN_PW, ORIGIN, _audit, _login, _sql, clear_limits, db_url

pytestmark = pytest.mark.integration
__all__ = ["clear_limits", "db_url"]
ADMIN = "admin@example.org"


class Clock:
    """The TOTP clock, moved a step forward for every code, since a code is used once."""

    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now

    def code(self, secret: str) -> str:
        self.now += 30
        return pyotp.TOTP(secret).at(self.now)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    found = Clock()
    monkeypatch.setattr(mfa, "_clock", found)
    return found


@pytest.fixture
async def web(db_url: str) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(Settings()))
    async with httpx.AsyncClient(transport=transport, base_url="https://localhost",
                                 headers=ORIGIN) as c:  # fmt: skip
        yield c


async def _enrol(web: httpx.AsyncClient, clock: Clock) -> tuple[str, list[str]]:
    assert (await _login(web, ADMIN, ADMIN_PW)).status_code == 200
    started = await web.post(_api("/me/mfa/setup"), json={"password": ADMIN_PW})
    assert started.status_code == 200, started.text
    assert started.headers["cache-control"] == "no-store"
    secret = started.json()["secret"]
    done = await web.post(_api("/me/mfa/confirm"), json={"code": clock.code(secret)})
    assert done.status_code == 200, done.text
    return secret, done.json()["recovery_codes"]


async def _password_step(web: httpx.AsyncClient) -> httpx.Response:
    web.cookies.clear()
    first = await _login(web, ADMIN, ADMIN_PW)
    assert first.status_code == 401 and first.json()["type"].endswith("/mfa-required")
    assert "rw_mfa=" in first.headers["set-cookie"]
    assert (await web.get(_api("/auth/me"))).status_code == 401  # no session yet
    return first


async def test_enrolment_needs_the_password_and_a_working_code(
    web: httpx.AsyncClient, clock: Clock, db_url: str
) -> None:
    assert (await _login(web, ADMIN, ADMIN_PW)).status_code == 200
    off = await web.get(_api("/me/mfa"))
    assert off.json() == {"enabled": False, "confirmed_at": None, "recovery_codes_left": 0}
    wrong = await web.post(_api("/me/mfa/setup"), json={"password": "not it at all"})
    assert wrong.status_code == 400
    started = await web.post(_api("/me/mfa/setup"), json={"password": ADMIN_PW})
    body = started.json()
    assert body["otpauth_uri"].startswith("otpauth://totp/") and len(body["qr"]) > 20
    bad = await web.post(_api("/me/mfa/confirm"), json={"code": "000000"})
    assert bad.status_code == 401 and bad.json()["type"].endswith("/mfa-invalid")
    assert (await web.get(_api("/me/mfa"))).json()["enabled"] is False  # not on until confirmed
    done = await web.post(_api("/me/mfa/confirm"), json={"code": clock.code(body["secret"])})
    codes = done.json()["recovery_codes"]
    assert len(codes) == 10
    on = (await web.get(_api("/me/mfa"))).json()
    assert on["enabled"] is True and on["recovery_codes_left"] == 10
    again = await web.post(_api("/me/mfa/setup"), json={"password": ADMIN_PW})
    assert again.status_code == 409
    assert len(await _audit(db_url, "auth.mfa_enabled")) == 1


async def test_enabling_ends_the_other_sessions(
    web: httpx.AsyncClient, clock: Clock, db_url: str
) -> None:
    transport = web._transport
    async with httpx.AsyncClient(transport=transport, base_url="https://localhost",
                                 headers=ORIGIN) as other:  # fmt: skip
        assert (await _login(other, ADMIN, ADMIN_PW)).status_code == 200
        await _enrol(web, clock)
        assert (await other.get(_api("/auth/me"))).status_code == 401
    assert (await web.get(_api("/auth/me"))).status_code == 200  # this one stays


async def test_sign_in_needs_the_code_once(
    web: httpx.AsyncClient, clock: Clock, db_url: str
) -> None:
    secret, _ = await _enrol(web, clock)
    await _password_step(web)
    no = await web.post(_api("/auth/mfa"), json={"code": "123456"})
    assert no.status_code == 401 and no.json()["type"].endswith("/mfa-invalid")
    code = clock.code(secret)
    yes = await web.post(_api("/auth/mfa"), json={"code": code})
    assert yes.status_code == 200 and yes.json()["email"] == ADMIN
    assert (await web.get(_api("/auth/me"))).status_code == 200
    logins = await _audit(db_url, "auth.login")
    assert logins[-1]["after"] == {"method": "password+totp"}
    failed = await _audit(db_url, "auth.login_failed")
    assert failed[-1]["after"] == {"reason": "mfa"}
    await _password_step(web)
    replay = await web.post(_api("/auth/mfa"), json={"code": code})
    assert replay.status_code == 401  # the same code, a second time


async def test_a_recovery_code_works_once(
    web: httpx.AsyncClient, clock: Clock, db_url: str
) -> None:
    _, codes = await _enrol(web, clock)
    await _password_step(web)
    used = await web.post(_api("/auth/mfa"), json={"code": codes[0].upper()})
    assert used.status_code == 200
    assert (await web.get(_api("/me/mfa"))).json()["recovery_codes_left"] == 9
    assert (await _audit(db_url, "auth.mfa_recovery_used"))[-1]["after"] == {"left": 9}
    await _password_step(web)
    assert (await web.post(_api("/auth/mfa"), json={"code": codes[0]})).status_code == 401


async def test_no_pending_cookie_or_a_changed_password_starts_over(
    web: httpx.AsyncClient, clock: Clock, db_url: str
) -> None:
    secret, _ = await _enrol(web, clock)
    web.cookies.clear()
    none = await web.post(_api("/auth/mfa"), json={"code": clock.code(secret)})
    assert none.status_code == 401 and none.json()["type"].endswith("/mfa-expired")
    await _password_step(web)
    await _sql(db_url, "UPDATE \"user\" SET password_hash = password_hash || 'x' "
                       f"WHERE email = '{ADMIN}'")  # fmt: skip
    stale = await web.post(_api("/auth/mfa"), json={"code": clock.code(secret)})
    assert stale.status_code == 401 and stale.json()["type"].endswith("/mfa-expired")


async def test_wrong_codes_lock_the_account(web: httpx.AsyncClient, clock: Clock) -> None:
    await _enrol(web, clock)
    await _password_step(web)
    answers = [(await web.post(_api("/auth/mfa"), json={"code": "000000"})).status_code
               for _ in range(10)]  # fmt: skip
    assert answers[-1] in (423, 429) and 401 in answers


async def test_turning_it_off_needs_the_password_and_a_code(
    web: httpx.AsyncClient, clock: Clock, db_url: str
) -> None:
    secret, _ = await _enrol(web, clock)
    no_code = await web.post(_api("/me/mfa/disable"),
                             json={"password": ADMIN_PW, "code": "000000"})  # fmt: skip
    assert no_code.status_code == 401
    wrong = {"password": "not it at all", "code": clock.code(secret)}
    no_pw = await web.post(_api("/me/mfa/disable"), json=wrong)
    assert no_pw.status_code == 400
    off = await web.post(_api("/me/mfa/disable"),
                         json={"password": ADMIN_PW, "code": clock.code(secret)})  # fmt: skip
    assert off.status_code == 204
    web.cookies.clear()
    assert (await _login(web, ADMIN, ADMIN_PW)).status_code == 200  # one step again
    assert len(await _audit(db_url, "auth.mfa_disabled")) == 1


async def test_new_recovery_codes_replace_the_old(web: httpx.AsyncClient, clock: Clock) -> None:
    secret, old = await _enrol(web, clock)
    got = await web.post(_api("/me/mfa/recovery-codes"),
                         json={"password": ADMIN_PW, "code": clock.code(secret)})  # fmt: skip
    new = got.json()["recovery_codes"]
    assert got.status_code == 200 and len(new) == 10 and not set(new) & set(old)
    await _password_step(web)
    assert (await web.post(_api("/auth/mfa"), json={"code": old[1]})).status_code == 401


async def test_an_administrator_resets_a_lost_authenticator(
    web: httpx.AsyncClient, clock: Clock, db_url: str
) -> None:
    assert (await _login(web, ADMIN, ADMIN_PW)).status_code == 200
    made = await web.post(_api("/admin/users"),
                          json={"email": "ana@example.org", "display_name": "Ana",
                                "roles": ["analyst"]})  # fmt: skip
    ana_id, temporary = made.json()["id"], made.json()["temporary_password"]
    transport = web._transport
    async with httpx.AsyncClient(transport=transport, base_url="https://localhost",
                                 headers=ORIGIN) as ana:  # fmt: skip
        assert (await _login(ana, "ana@example.org", temporary)).status_code == 200
        own = "ana's own passphrase"
        change = {"current_password": temporary, "new_password": own}
        assert (await ana.post(_api("/auth/password"), json=change)).status_code == 204
        started = await ana.post(_api("/me/mfa/setup"), json={"password": own})
        secret = started.json()["secret"]
        code = {"code": clock.code(secret)}
        assert (await ana.post(_api("/me/mfa/confirm"), json=code)).status_code == 200
        reset = await web.delete(_api(f"/admin/users/{ana_id}/mfa"))
        assert reset.status_code == 204
        assert (await ana.get(_api("/auth/me"))).status_code == 401  # her sessions end
        ana.cookies.clear()
        assert (await _login(ana, "ana@example.org", own)).status_code == 200  # password alone
    assert len(await _audit(db_url, "auth.mfa_reset")) == 1
    assert (await web.delete(_api(f"/admin/users/{ana_id}/mfa"))).status_code == 404


async def test_an_administrator_cannot_reset_their_own(
    web: httpx.AsyncClient, clock: Clock
) -> None:
    await _enrol(web, clock)
    me = (await web.get(_api("/auth/me"))).json()["id"]
    refused = await web.delete(_api(f"/admin/users/{me}/mfa"))
    assert refused.status_code == 403
    assert (await web.get(_api("/me/mfa"))).json()["enabled"] is True


async def test_rotating_the_secret_key_keeps_authenticators(
    web: httpx.AsyncClient, clock: Clock, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from regwatch.core.settings import get_settings
    from regwatch.identity import admin_cli

    secret, _ = await _enrol(web, clock)
    old = get_settings().secret_key.get_secret_value()
    monkeypatch.setenv("REGWATCH_SECRET_KEY_PREVIOUS", old)
    monkeypatch.setenv("REGWATCH_SECRET_KEY", "e" * 64)
    get_settings.cache_clear()
    import asyncio

    assert await asyncio.to_thread(admin_cli.main, ["rotate-mfa-secrets"]) == 0
    monkeypatch.delenv("REGWATCH_SECRET_KEY_PREVIOUS")
    get_settings.cache_clear()
    rotated = mfa.decrypt(get_settings(), await _secret_enc(db_url))
    assert rotated == secret  # opens with the new key alone


async def _secret_enc(url: str) -> str:
    from sqlalchemy import text

    from regwatch.core.db import create_engine

    engine = create_engine(url, poolclass_null=True)
    async with engine.connect() as conn:
        value = (await conn.execute(text("SELECT secret_enc FROM user_mfa"))).scalar_one()
    await engine.dispose()
    return str(value)
