from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime

import httpx
import pytest
from structlog.stdlib import ProcessorFormatter

from regwatch.api import services
from regwatch.api.app import create_app
from regwatch.core.settings import Settings


@pytest.fixture
async def client(valid_env: dict[str, str]) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _patch_probes(monkeypatch: pytest.MonkeyPatch, db: str, queue: str) -> None:
    async def fake_db(_: str) -> str:
        return db

    async def fake_queue(_: str) -> str:
        return queue

    monkeypatch.setattr(services, "probe_db", fake_db)
    monkeypatch.setattr(services, "probe_queue", fake_queue)


@pytest.mark.parametrize(
    ("db", "queue", "status"),
    [
        ("ok", "ok", "ok"),
        ("ok", "unavailable", "degraded"),
        ("unavailable", "ok", "degraded"),
        ("unavailable", "unavailable", "down"),
    ],
)
async def test_health_matches_contract(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, db: str, queue: str, status: str
) -> None:
    _patch_probes(monkeypatch, db, queue)
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"status", "version", "db", "queue", "checked_at"}
    assert body["status"] == status
    assert (body["db"], body["queue"]) == (db, queue)
    assert body["version"] == services.app_version()
    assert datetime.fromisoformat(body["checked_at"]).tzinfo is not None


async def test_health_without_dependencies_reports_down(client: httpx.AsyncClient) -> None:
    # VALID_ENV points db and queue at port 1 on loopback, where nothing listens.
    body = (await client.get("/api/v1/health")).json()
    assert body["status"] == "down"


async def test_version(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/version")
    assert resp.status_code == 200
    assert resp.json() == {"version": services.app_version(), "commit": services.BUILD_COMMIT}


async def test_request_id_is_echoed_when_safe(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/version", headers={"X-Request-Id": "abc-123"})
    assert resp.headers["x-request-id"] == "abc-123"


@pytest.mark.parametrize("raw", [None, "", "bad id\r\nx", "x" * 200, "<script>"])
async def test_unsafe_or_missing_request_id_is_replaced(
    client: httpx.AsyncClient, raw: str | None
) -> None:
    headers = {"X-Request-Id": raw} if raw is not None else {}
    try:
        resp = await client.get("/api/v1/version", headers=headers)
    except httpx.LocalProtocolError:
        pytest.skip("client refuses to send the header")
    rid = resp.headers["x-request-id"]
    assert rid != raw and len(rid) == 32


async def test_access_log_is_json_with_request_id(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    await client.get("/api/v1/version", headers={"X-Request-Id": "log-test"})
    records = [r for r in caplog.records if r.name == "regwatch.access"]
    assert records
    json_handler = next(
        h for h in logging.getLogger().handlers if isinstance(h.formatter, ProcessorFormatter)
    )
    line = json.loads(json_handler.format(records[-1]))
    assert line["event"] == "request" and line["request_id"] == "log-test"
    assert line["path"] == "/api/v1/version" and line["status"] == 200
    assert line["level"] == "info" and "timestamp" in line
    assert logging.getLogger("uvicorn.access").disabled


def test_docs_hidden_outside_development(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REGWATCH_ENV", "production")
    assert create_app(Settings()).docs_url is None
