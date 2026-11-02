"""The RFC 9457 problem-details handlers in regwatch.core.errors."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from regwatch.api.middleware import RequestContextMiddleware
from regwatch.core.errors import (
    PROBLEM_MEDIA_TYPE,
    ProblemError,
    ProblemFieldError,
    install_problem_handlers,
)
from regwatch.core.routing import not_implemented


class Body(BaseModel):
    name: str
    count: int


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    install_problem_handlers(app)

    @app.get("/stub")
    async def stub() -> None:
        not_implemented()

    @app.get("/conflict")
    async def conflict() -> None:
        raise ProblemError(
            409, "conflict", "Role is in use.",
            errors=[ProblemFieldError(field="key", message="in use")],
            headers={"Retry-After": "5"},
        )  # fmt: skip

    @app.get("/http")
    async def http() -> None:
        raise HTTPException(status_code=403, detail="Missing permission users.manage")

    @app.get("/teapot")
    async def teapot() -> None:
        raise HTTPException(status_code=418)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.get("/thing")
    async def get_thing() -> dict[str, str]:
        return {}

    @app.delete("/thing")
    async def delete_thing() -> None:
        return None

    @app.post("/thing")
    async def post_thing(body: Body) -> Body:
        return body

    return app


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _problem(resp: httpx.Response, status: int, slug: str) -> dict[str, object]:
    assert resp.status_code == status
    assert resp.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body: dict[str, object] = resp.json()
    assert body["type"] == f"https://regwatch/errors/{slug}"
    assert body["status"] == status
    assert isinstance(body["title"], str) and body["title"]
    if status != 500:  # a 500 is sent by Starlette's outermost middleware, outside the request id
        assert body["request_id"] == resp.headers["x-request-id"]
    return body


async def test_stub_answers_501(client: httpx.AsyncClient) -> None:
    body = _problem(await client.get("/stub"), 501, "not-implemented")
    assert body["instance"] == "/stub"
    assert body["title"] == "Not Implemented"


async def test_problem_error_carries_detail_errors_and_headers(client: httpx.AsyncClient) -> None:
    resp = await client.get("/conflict", headers={"X-Request-Id": "req-1"})
    body = _problem(resp, 409, "conflict")
    assert body["detail"] == "Role is in use."
    assert body["errors"] == [{"field": "key", "message": "in use"}]
    assert body["request_id"] == "req-1"
    assert resp.headers["retry-after"] == "5"


async def test_http_exception_becomes_problem(client: httpx.AsyncClient) -> None:
    body = _problem(await client.get("/http"), 403, "forbidden")
    assert body["detail"] == "Missing permission users.manage"


async def test_http_exception_without_detail_and_unknown_slug(client: httpx.AsyncClient) -> None:
    body = _problem(await client.get("/teapot"), 418, "http-error")
    assert "detail" not in body


async def test_unknown_path_is_404_problem(client: httpx.AsyncClient) -> None:
    body = _problem(await client.get("/nowhere"), 404, "not-found")
    assert "detail" not in body


async def test_405_lists_every_routed_method(client: httpx.AsyncClient) -> None:
    resp = await client.put("/thing")
    _problem(resp, 405, "method-not-allowed")
    assert resp.headers["allow"] == "DELETE, GET, POST"


async def test_validation_error_lists_fields(client: httpx.AsyncClient) -> None:
    resp = await client.post("/thing", json={"name": 3})
    body = _problem(resp, 422, "validation")
    fields = {e["field"] for e in body["errors"]}  # type: ignore[attr-defined]
    assert fields == {"name", "count"}


async def test_undecodable_body_is_validation_problem(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/thing", content=b"\xff\xfe{", headers={"content-type": "application/json"}
    )
    body = _problem(resp, 422, "validation")
    assert body["detail"] == "The request body is not valid JSON."


async def test_unhandled_error_is_generic_500(client: httpx.AsyncClient) -> None:
    resp = await client.get("/boom")
    body = _problem(resp, 500, "internal")
    assert "secret" not in resp.text
    assert "detail" not in body
