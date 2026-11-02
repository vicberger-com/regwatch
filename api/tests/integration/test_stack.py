"""Integration: the Compose stack answers through the proxy (``make test-integration``)."""

from __future__ import annotations

import os

import httpx
import pytest

BASE_URL = os.environ.get("IT_PROXY_URL", "http://localhost")


@pytest.mark.integration
def test_health_through_proxy_reports_dependencies_up() -> None:
    resp = httpx.get(f"{BASE_URL}/api/v1/health", timeout=5)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok", body
    assert body["db"] == "ok" and body["queue"] == "ok"
    assert resp.headers.get("x-request-id")
