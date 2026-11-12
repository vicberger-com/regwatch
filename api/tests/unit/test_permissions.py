"""The permission seam (#34): x-permission enforced through one replaceable dependency."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from fastapi import APIRouter, FastAPI

from regwatch.core.errors import install_problem_handlers
from regwatch.core.permissions import Principal, current_principal, dev_session_token
from regwatch.core.routing import spec
from regwatch.core.settings import Settings, get_settings

router = APIRouter()


@router.get("/live", **spec(desc="Live", perm="taxonomy.manage", stub=False))
async def live() -> None:
    return None


@router.get("/stub", **spec(desc="Stub", perm="taxonomy.manage"))
async def stub() -> None:
    return None


SETTINGS = {"secret_key": "a" * 64, "database_url": "postgresql://u@h/d",
            "queue_url": "valkey://h/0", "base_url": "http://localhost"}  # fmt: skip
TOKEN = dev_session_token(Settings(**SETTINGS))  # type: ignore[arg-type]


def make_app(env: str, principal: Principal | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    install_problem_handlers(app)
    settings = Settings(**SETTINGS, env=env)  # type: ignore[arg-type]
    app.dependency_overrides[get_settings] = lambda: settings
    if principal is not None:
        override: Callable[[], Principal] = lambda: principal  # noqa: E731
        app.dependency_overrides[current_principal] = override
    return app


async def get(app: FastAPI, path: str, cookie: str | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    cookies = {"rw_session": cookie} if cookie is not None else None
    async with httpx.AsyncClient(transport=transport, base_url="http://t", cookies=cookies) as c:
        return await c.get(path)


@pytest.mark.parametrize(
    ("env", "cookie", "status"),
    [("development", TOKEN, 200), ("test", TOKEN, 200), ("production", TOKEN, 401),
     ("test", None, 401), ("test", "forged", 401), ("test", "0" * 64, 401)],
)  # fmt: skip
async def test_pre_m1_principal_needs_the_development_session(
    env: str, cookie: str | None, status: int
) -> None:
    resp = await get(make_app(env), "/live", cookie)
    assert resp.status_code == status
    if status == 401:
        assert resp.json()["type"].endswith("/unauthenticated")


async def test_missing_permission_is_403_problem_naming_it() -> None:
    viewer = Principal(user_id=None, permissions=frozenset({"taxonomy.read"}))
    resp = await get(make_app("production", viewer), "/live")
    assert resp.status_code == 403
    assert resp.json()["type"].endswith("/forbidden")
    assert "taxonomy.manage" in resp.json()["detail"]


async def test_granted_permission_passes_and_stubs_are_not_gated() -> None:
    admin = Principal(user_id=None, permissions=frozenset({"taxonomy.manage"}))
    assert (await get(make_app("production", admin), "/live")).status_code == 200
    assert (await get(make_app("production"), "/stub")).status_code == 200
