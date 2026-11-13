"""Every contract operation is routed, and the live document matches the contract (#30)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from regwatch.api.app import API_PREFIX, api_routes, create_app
from regwatch.core.routing import PERMISSION_KEY
from regwatch.core.settings import Settings
from regwatch.identity.permissions import authorize

from ..openapi_semantic import ACCEPTED, compare, load, operations

CONTRACT_PATH = Path(__file__).resolve().parents[3] / "openapi" / "regwatch.v1.yaml"
CONTRACT = load(CONTRACT_PATH)


@pytest.fixture
def app(valid_env: dict[str, str]) -> FastAPI:
    return create_app(Settings())


def _routed(app: FastAPI) -> dict[tuple[str, str], APIRoute]:
    """Routes as served: ``api_routes()`` must agree with the mounted application."""
    pairs = {
        (path.removeprefix(API_PREFIX), m.lower()): r
        for path, r in api_routes()
        if isinstance(r, APIRoute)
        for m in r.methods
    }
    served = {(p, m) for p, item in app.openapi()["paths"].items() for m in item}
    assert set(pairs) == served
    return pairs


def test_contract_has_68_paths_and_91_operations() -> None:
    assert len(CONTRACT["paths"]) == 68
    assert len(operations(CONTRACT)) == 91


def test_every_contract_operation_is_routed(app: FastAPI) -> None:
    routed = _routed(app)
    missing = sorted(operations(CONTRACT) - set(routed))
    extra = sorted(set(routed) - operations(CONTRACT))
    assert missing == [] and extra == []


def test_permission_metadata_matches_contract(app: FastAPI) -> None:
    for (path, method), route in _routed(app).items():
        expected = CONTRACT["paths"][path][method].get(PERMISSION_KEY)
        assert (route.openapi_extra or {}).get(PERMISSION_KEY) == expected, (method, path)


def test_live_document_matches_contract_semantically(app: FastAPI) -> None:
    assert compare(CONTRACT, app.openapi()) == []


def test_accepted_differences_are_still_real(app: FastAPI) -> None:
    """An accepted difference that no longer occurs must be removed from ACCEPTED."""
    remaining = set(compare(CONTRACT, app.openapi(), accepted={}))
    assert set(ACCEPTED) <= remaining


def _mutate(doc: dict[str, Any]) -> dict[str, Any]:
    doc = copy.deepcopy(doc)
    del doc["paths"]["/admin/roles"]["post"]
    users = doc["paths"]["/admin/users"]["get"]
    users[PERMISSION_KEY] = "users.read"
    next(p for p in users["parameters"] if p["name"] == "page")["schema"]["minimum"] = 0
    doc["components"]["schemas"]["User"]["properties"]["email"]["format"] = "uri"
    doc["paths"]["/legal"]["get"]["responses"]["501"]["content"] = {"application/json": {}}
    return doc


def test_semantic_diff_reports_drift(app: FastAPI) -> None:
    lines = compare(CONTRACT, _mutate(app.openapi()))
    joined = "\n".join(lines)
    assert "POST /admin/roles: not routed" in joined
    assert "GET /admin/users.x-permission" in joined
    assert "GET /admin/users.parameters.query:page.schema.minimum" in joined
    assert "properties.email.format" in joined
    assert "GET /legal: 501 is not problem details" in joined


def test_document_shape(app: FastAPI) -> None:
    doc = app.openapi()
    assert doc["servers"] == [{"url": API_PREFIX}]
    assert doc["components"]["securitySchemes"] == CONTRACT["components"]["securitySchemes"]
    assert doc["security"] == CONTRACT["security"]
    assert [t["name"] for t in doc["tags"]] == [t["name"] for t in CONTRACT["tags"]]
    assert {"HTTPValidationError", "ValidationError"}.isdisjoint(doc["components"]["schemas"])


async def test_gate_answers_before_stubs(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"{API_PREFIX}/admin/users")
        assert resp.status_code == 401
        assert resp.headers["content-type"] == "application/problem+json"
        resp = await client.post(f"{API_PREFIX}/admin/users", json={})
        assert resp.status_code == 403  # no Origin header: the CSRF check comes first


async def test_stubs_answer_501_problem(app: FastAPI) -> None:
    app.dependency_overrides[authorize] = lambda: None  # past the gate (#31)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"{API_PREFIX}/sources")
        assert resp.status_code == 501
        assert resp.headers["content-type"] == "application/problem+json"
        resp = await client.post(f"{API_PREFIX}/admin/branding/logo", content=b"x")
        assert resp.status_code == 501
        resp = await client.post(f"{API_PREFIX}/taxonomy/import", content=b"facets: []")
        assert resp.status_code == 501
        resp = await client.request("OPTIONS", f"{API_PREFIX}/jurisdictions/regions")
        assert resp.headers["allow"] == "GET"  # not PATCH of /jurisdictions/{code}
        resp = await client.put(f"{API_PREFIX}/admin/users")
        assert resp.status_code == 405
        assert resp.headers["allow"] == "GET, POST"
        resp = await client.delete(f"{API_PREFIX}/admin/users/{uuid4()}")
        assert resp.headers["allow"] == "GET, PATCH"
