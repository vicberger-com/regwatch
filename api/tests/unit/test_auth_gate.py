"""The application-wide gate and the login limits, without a database (#31, REQ-16)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from regwatch.api.app import API_PREFIX, create_app
from regwatch.core.errors import ProblemError
from regwatch.core.settings import Settings
from regwatch.identity import permissions, services
from regwatch.identity.models import User


@pytest.fixture(autouse=True)
def clear_limits() -> Iterator[None]:
    services.login_attempts.clear()
    services.password_changes.clear()
    services.login_attempts_hourly.clear()
    services.all_attempts.clear()
    services.unknown_failures.clear()
    services.unknown_locks.clear()
    yield
    services.login_attempts.clear()
    services.password_changes.clear()
    services.login_attempts_hourly.clear()
    services.all_attempts.clear()
    services.unknown_failures.clear()
    services.unknown_locks.clear()


@pytest.fixture
def app(valid_env: dict[str, str]) -> FastAPI:
    return create_app(Settings())


def _user(**kw: Any) -> User:
    base: dict[str, Any] = {"id": uuid.uuid4(), "email": "a@example.org", "display_name": "A",
                            "status": "active", "must_change_password": False, "preferences": {},
                            "created_at": datetime.now(UTC)}  # fmt: skip
    return User(**{**base, **kw})


def _principal(perms: set[str], **kw: Any) -> services.Principal:
    return services.Principal(_user(**kw), uuid.uuid4(), ("viewer",), frozenset(perms))


async def _get(app: FastAPI, path: str, **kw: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    cookies = kw.pop("cookies", None)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost", cookies=cookies
    ) as client:
        return await client.request(kw.pop("method", "GET"), API_PREFIX + path, **kw)


def _resolve_to(monkeypatch: pytest.MonkeyPatch, principal: services.Principal | None) -> None:
    async def fake(db: object, token: str, passive: bool = False) -> services.Principal | None:
        return principal

    monkeypatch.setattr(services, "resolve_session", fake)


async def test_public_routes_need_no_session(app: FastAPI) -> None:
    assert (await _get(app, "/version")).status_code == 200


async def test_no_cookie_or_oversized_cookie_is_401(app: FastAPI) -> None:
    assert (await _get(app, "/auth/me")).status_code == 401
    resp = await _get(app, "/auth/me", cookies={"rw_session": "x" * 200})
    assert resp.status_code == 401
    assert resp.json()["type"].endswith("/unauthenticated")


async def test_unknown_session_is_401(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    _resolve_to(monkeypatch, None)
    assert (await _get(app, "/auth/me", cookies={"rw_session": "t"})).status_code == 401


async def test_login_without_origin_is_403(app: FastAPI) -> None:
    body = {"email": "a@example.org", "password": "x"}
    resp = await _get(app, "/auth/login", method="POST", json=body)
    assert resp.status_code == 403
    assert resp.json()["type"].endswith("/origin-mismatch")
    resp = await _get(app, "/auth/login", method="POST", json=body,
                      headers={"origin": "https://evil.example"})  # fmt: skip
    assert resp.status_code == 403


async def test_permission_from_contract_is_enforced(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolve_to(monkeypatch, _principal({"items.read"}))
    resp = await _get(app, "/admin/users", cookies={"rw_session": "t"})
    assert resp.status_code == 403
    assert resp.json()["type"].endswith("/forbidden")
    me = await _get(app, "/auth/me", cookies={"rw_session": "t"})
    assert me.status_code == 200
    assert me.json()["permissions"] == ["items.read"]


async def test_permitted_user_reaches_the_handler(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolve_to(monkeypatch, _principal({"settings.manage"}))
    from regwatch.core.db import get_db
    from regwatch.outputs import printers

    async def none(db: object) -> list[object]:
        return []

    monkeypatch.setattr(printers, "list_printers", none)  # the handler, without a database
    app.dependency_overrides[get_db] = lambda: None
    got = await _get(app, "/admin/printers", cookies={"rw_session": "t"})
    assert (got.status_code, got.json()) == (200, [])  # the gate let the call through


async def test_temporary_password_allows_only_the_change(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolve_to(monkeypatch, _principal({"items.read"}, must_change_password=True))
    resp = await _get(app, "/jurisdictions", cookies={"rw_session": "t"})
    assert resp.status_code == 403
    assert resp.json()["type"].endswith("/password-change-required")
    assert (await _get(app, "/auth/me", cookies={"rw_session": "t"})).status_code == 200


def test_current_principal_without_gate_is_401() -> None:
    class Req:
        class state:  # noqa: N801
            pass

    with pytest.raises(ProblemError) as exc:
        permissions.current_principal(Req())  # type: ignore[arg-type]
    assert exc.value.status == 401


def test_login_rate_limit_per_account_and_ip() -> None:
    """U-M1-1: 5 failures per account, 30 per address, in a minute."""
    for _ in range(5):
        services.check_login_rate("10.0.0.1", "a@example.org")
    with pytest.raises(ProblemError) as exc:
        services.check_login_rate("10.0.0.2", "A@Example.org ")  # the same account
    assert exc.value.status == 429
    assert exc.value.headers is not None and int(exc.value.headers["Retry-After"]) >= 1
    for i in range(25):  # other accounts behind the same address: 30 in all
        services.check_login_rate("10.0.0.1", f"user{i}@example.org")
    with pytest.raises(ProblemError):
        services.check_login_rate("10.0.0.1", "next@example.org")
    services.check_login_rate("10.0.0.3", "next@example.org")  # another address is not affected
    services.check_login_rate(None, "c@example.org")


def test_successful_attempts_are_given_back() -> None:
    """U-M1-1: a correct sign-in does not use up the account's or the address's budget."""
    for _ in range(10):
        services.forgive(services.check_login_rate("10.0.0.9", "ok@example.org"))
    assert services.login_attempts.count("acct:" + services.email_digest("ok@example.org")) == 0
    assert services.login_attempts.count(services.address_key("10.0.0.9")) == 0
    services.check_login_rate("10.0.0.9", "ok@example.org")  # still allowed


def test_failures_mixed_with_successes_keep_counting() -> None:
    """Rate review 6: a success gives back only its own attempt."""
    for _ in range(5):
        services.check_login_rate("10.0.0.8", "victim@example.org")  # failures, never forgiven
        services.forgive(services.check_login_rate("10.0.0.8", "mine@example.org"))
    with pytest.raises(ProblemError):
        services.check_login_rate("10.0.0.7", "victim@example.org")


def test_a_refund_removes_only_its_own_count() -> None:
    """Rate review 1: a late refund must not delete another request's failure."""
    window = services.SlidingWindow(60.0)
    mine = window.hit_at("k")
    window.hit("k")  # someone else's failure, counted later
    window.refund("k", mine)
    assert window.count("k") == 1
    window.refund("k", mine)  # twice, or after it left the window: nothing more is removed
    assert window.count("k") == 1


def test_every_attempt_is_capped_even_correct_ones() -> None:
    """Rate review 2: correct passwords cost an Argon2 hash, so all attempts have a cap."""
    for _ in range(services.LOGIN_ALL_RATE[0]):
        services.forgive(services.check_login_rate(None, "busy@example.org"))
    with pytest.raises(ProblemError):
        services.check_login_rate(None, "busy@example.org")


def test_addresses_group_ipv6_by_64_and_have_an_hourly_limit() -> None:
    """Rate review 3: one client cannot rotate through its /64, or spray all day."""
    assert services.address_key("2001:db8:1:2::1") == services.address_key("2001:db8:1:2:ffff::9")
    assert services.address_key("2001:db8:1:3::1") != services.address_key("2001:db8:1:2::1")
    assert services.address_key("::ffff:10.0.0.1") == services.address_key("10.0.0.1")
    assert services.address_key("not an address").startswith("ip:")
    key = services.address_key("10.0.0.6")
    for _ in range(services.LOGIN_RATE_IP_HOURLY[0]):
        services.login_attempts_hourly.hit(key)
    with pytest.raises(ProblemError):
        services.check_login_rate("10.0.0.6", "fresh@example.org")


def test_password_change_limit_has_its_own_message() -> None:
    import uuid

    user = uuid.uuid4()
    for _ in range(services.PASSWORD_CHANGE_RATE[0]):
        services.check_password_change_rate(user)
    with pytest.raises(ProblemError) as exc:
        services.check_password_change_rate(user)
    assert exc.value.detail is not None and "password-change" in exc.value.detail


def test_refund_of_an_empty_window_is_harmless() -> None:
    services.login_attempts.refund("ip:never-seen", 0.0)


def test_sliding_window_expires_and_prunes(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(services.time, "monotonic", lambda: clock[0])
    window = services.SlidingWindow(10)
    assert window.hit("k") == 1 and window.hit("k") == 2
    assert window.retry_after("k") == 11
    clock[0] += 11
    assert window.count("k") == 0 and window.retry_after("k") == 1
    monkeypatch.setattr(services.SlidingWindow, "MAX_KEYS", 1)
    window.hit("a")
    window.hit("b")
    clock[0] += 11
    window.hit("c")
    assert set(window._hits) == {"c"}


def test_lock_table_expires_and_prunes(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(services.time, "monotonic", lambda: clock[0])
    table = services.LockTable()
    assert not table.locked("k")
    table.lock("k", 60)
    assert table.locked("k")
    clock[0] += 61
    assert not table.locked("k")
    monkeypatch.setattr(services.LockTable, "MAX_KEYS", 1)
    table.lock("a", 10)
    table.lock("b", 10)
    clock[0] += 11
    table.lock("c", 10)
    assert set(table._until) == {"c"}


@pytest.mark.parametrize(
    ("pref", "minutes"), [(None, 480), (30, 30), (10, 480), (900, 480), (True, 480)]
)
def test_idle_timeout_is_bounded_by_admin_maximum(pref: object, minutes: int) -> None:
    prefs = {} if pref is None else {"session_idle_timeout_minutes": pref}
    assert services._idle_minutes(_user(preferences=prefs), services.AUTH_DEFAULTS) == minutes


def test_email_digest_normalises() -> None:
    assert services.email_digest(" A@Example.org") == services.email_digest("a@example.org")


async def test_gate_without_a_route_requires_a_session(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scope with no APIRoute (not expected in practice) is treated as non-public."""
    from contextlib import asynccontextmanager

    from starlette.requests import Request

    @asynccontextmanager
    async def no_db() -> Any:
        yield None

    class App:
        class state:  # noqa: N801
            db = staticmethod(no_db)

    principal = _principal(set())
    _resolve_to(monkeypatch, principal)
    scope = {"type": "http", "method": "GET", "path": "/", "app": App(),
             "headers": [(b"cookie", b"rw_session=t")]}  # fmt: skip
    request = Request(scope)
    await permissions.authorize(request, Settings())
    assert permissions.current_principal(request) is principal
    _resolve_to(monkeypatch, _principal(set(), must_change_password=True))
    with pytest.raises(ProblemError):
        await permissions.authorize(Request(dict(scope)), Settings())


def test_rejected_attempts_leave_no_trace() -> None:
    """Re-verification N1: a request refused by a limit adds no counter entry."""
    for _ in range(services.LOGIN_RATE_IP[0]):
        services.check_login_rate("10.0.0.5", f"seed{_}@example.org")
    before = len(services.all_attempts._hits) + len(services.login_attempts._hits)
    for i in range(500):
        with pytest.raises(ProblemError):
            services.check_login_rate("10.0.0.5", f"random{i}@example.org")
    assert len(services.all_attempts._hits) + len(services.login_attempts._hits) == before


def test_a_refused_client_gets_back_under_the_cap() -> None:
    """Re-verification N2: refused retries do not count, so the cap clears after its window."""
    for _ in range(services.LOGIN_ALL_RATE[0]):
        services.forgive(services.check_login_rate(None, "retry@example.org"))
    for _ in range(50):  # hammering while refused changes nothing
        with pytest.raises(ProblemError):
            services.check_login_rate(None, "retry@example.org")
    assert (
        services.all_attempts.count("all:" + "acct:" + services.email_digest("retry@example.org"))
        == (services.LOGIN_ALL_RATE[0])
    )


def test_sweeps_run_at_most_once_per_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-verification N1: past MAX_KEYS, the oldest keys go, without a scan per request."""
    window = services.SlidingWindow(60.0)
    monkeypatch.setattr(window, "MAX_KEYS", 10)
    for i in range(12):
        window.hit(f"k{i}")
    assert len(window._hits) <= 10  # the first sweep dropped the oldest keys
    swept_at = window._last_sweep
    for i in range(12, 30):
        window.hit(f"k{i}")
    assert window._last_sweep == swept_at  # no second sweep within the window


def test_recently_hit_keys_survive_the_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-verification 2, N4: a flood of new keys evicts the least recently hit, not a victim."""
    window = services.SlidingWindow(60.0)
    monkeypatch.setattr(window, "MAX_KEYS", 10)
    window.hit("victim")
    for i in range(8):
        window.hit(f"old{i}")
    window.hit("victim")  # hit again: now the most recent
    for i in range(3):
        window.hit(f"new{i}")
    assert window.count("victim") == 2
    assert "old0" not in window._hits


def test_unknown_account_failures_are_never_evicted_while_live() -> None:
    """Re-verification 2, N4: unknown emails must lock like real ones (M1 acceptance 3)."""
    assert services.unknown_failures.evict_live is False
    window = services.SlidingWindow(60.0, evict_live=False)
    window.MAX_KEYS = 3
    for i in range(6):
        window.hit(f"k{i}")
    assert len(window._hits) == 6  # all live, all kept
