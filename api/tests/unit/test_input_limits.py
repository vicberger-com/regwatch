"""Request size limit and input checks from the M1 review (findings 3, 10; REQ-16)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from regwatch.api.app import API_PREFIX, create_app
from regwatch.api.middleware import MAX_BODY_BYTES
from regwatch.core.schemas import check_email, max_items, max_len
from regwatch.core.settings import Settings


@pytest.fixture
def app(valid_env: dict[str, str]) -> FastAPI:
    return create_app(Settings())


async def _post(app: FastAPI, path: str, **kw: object) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        return await c.post(API_PREFIX + path, **kw)  # type: ignore[arg-type]


async def test_declared_oversize_body_is_413_before_the_gate(app: FastAPI) -> None:
    resp = await _post(app, "/admin/roles", content=b"x" * (MAX_BODY_BYTES + 1))
    assert resp.status_code == 413
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.json()["type"].endswith("/payload-too-large") and resp.json()["request_id"]


async def test_streamed_oversize_body_is_413(app: FastAPI) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(3):
            yield b"x" * (MAX_BODY_BYTES // 2 + 1)

    resp = await _post(app, "/admin/roles", content=chunks())
    assert resp.status_code == 413


async def test_bad_content_length_is_413(app: FastAPI) -> None:
    resp = await _post(app, "/admin/roles", content=b"{}", headers={"content-length": "abc"})
    assert resp.status_code == 413


async def test_small_body_reaches_the_gate(app: FastAPI) -> None:
    assert (await _post(app, "/admin/roles", json={})).status_code == 403  # no Origin


@pytest.mark.parametrize("value", ["a@b.co", " A.B+c@Example.org "])
def test_valid_emails(value: str) -> None:
    assert check_email(value) == value.strip()


@pytest.mark.parametrize("value", ["", "no-at-sign", "a@b", "a b@c.de", "x" * 250 + "@a.de"])
def test_invalid_emails(value: str) -> None:
    with pytest.raises(ValueError):
        check_email(value)


def test_length_and_item_limits() -> None:
    assert max_len(3)("abc") == "abc"
    with pytest.raises(ValueError):
        max_len(3)("abcd")
    with pytest.raises(ValueError):
        max_len(10, min_len=1)("   ")
    assert max_items(2)(["a", "b"]) == ["a", "b"]
    with pytest.raises(ValueError):
        max_items(2)(["a", "b", "c"])
    with pytest.raises(ValueError):
        max_items(2)(["x" * 201])


@pytest.mark.parametrize(("sqlstate", "status"), [("22021", 422), ("23505", 409), ("40001", 500)])
async def test_database_input_errors_map_to_problems(sqlstate: str, status: int) -> None:
    from fastapi import FastAPI
    from sqlalchemy.exc import DBAPIError

    from regwatch.core.errors import install_problem_handlers

    class OrigError(Exception):
        pass

    orig = OrigError("boom")
    orig.sqlstate = sqlstate  # type: ignore[attr-defined]
    app = FastAPI()
    install_problem_handlers(app)

    @app.get("/x")
    async def fail() -> None:
        raise DBAPIError("SELECT 1", {"email": "secret@example.org"}, orig)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get("/x")
    assert resp.status_code == status
    assert "secret@example.org" not in resp.text


async def test_a_contract_valid_body_over_2_mb_gets_a_documented_413(app: FastAPI) -> None:
    """Fields within their maxLength can still exceed 2 MB once JSON-escaped (12 bytes for an
    emoji); the 413 that answers is documented on every operation with a body."""
    import json

    body = json.dumps({"page_markdown": "\U0001f600" * 200_000}).encode()
    assert len(body) > MAX_BODY_BYTES
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        resp = await c.put(API_PREFIX + "/admin/legal", content=body,
                           headers={"content-type": "application/json"})  # fmt: skip
    assert resp.status_code == 413
    doc = app.openapi()
    assert "413" in doc["paths"]["/admin/legal"]["put"]["responses"]
    assert "413" not in doc["paths"]["/health"]["get"]["responses"]
