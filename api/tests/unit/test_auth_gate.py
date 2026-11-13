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
    services.unknown_failures.clear()
    yield
    services.login_attempts.clear()
    services.unknown_failures.clear()


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
    async def fake(db: object, token: str) -> services.Principal | None:
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
    _resolve_to(monkeypatch, _principal({"sources.read"}))
    assert (await _get(app, "/sources", cookies={"rw_session": "t"})).status_code == 501


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
    for _ in range(5):
        services.check_login_rate("10.0.0.1", "a@example.org")
    with pytest.raises(ProblemError) as exc:
        services.check_login_rate("10.0.0.2", "A@Example.org ")
    assert exc.value.status == 429
    assert exc.value.headers is not None and int(exc.value.headers["Retry-After"]) >= 1
    with pytest.raises(ProblemError):
        services.check_login_rate("10.0.0.1", "b@example.org")
    services.check_login_rate(None, "c@example.org")


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
