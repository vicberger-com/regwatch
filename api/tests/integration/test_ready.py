"""``GET /api/v1/ready`` (CP-34, M10.1): ready only when every dependency answers."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import redis.asyncio as redis

from regwatch.core.settings import get_settings
from tests.integration.test_admin import _api, admin
from tests.integration.test_auth import clear_limits, db_url
from tests.integration.test_valkey_rate import valkey

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db_url", "valkey"]


@pytest.fixture
def ready_env(db_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, valkey: redis.Redis
              ) -> None:  # fmt: skip
    """A real queue (a Valkey container on loopback) and a writable store, set after the
    test environment (`db_url`) and before the app."""
    kw = valkey.connection_pool.connection_kwargs
    monkeypatch.setenv("REGWATCH_QUEUE_URL", f"redis://{kw['host']}:{kw['port']}/0")
    monkeypatch.setenv("REGWATCH_OBJECT_STORE_PATH", str(tmp_path))
    get_settings.cache_clear()


async def test_ready_when_the_database_queue_and_store_answer(
    ready_env: None, admin: httpx.AsyncClient
) -> None:
    got = await admin.get(_api("/ready"))
    assert got.status_code == 200, got.text
    assert got.json()["ready"] is True
    assert {got.json()[k] for k in ("db", "queue", "object_store")} == {"ok"}


@pytest.fixture
def no_store(db_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REGWATCH_OBJECT_STORE_PATH", str(tmp_path / "missing"))
    get_settings.cache_clear()


async def test_not_ready_without_a_writable_store(no_store: None, admin: httpx.AsyncClient) -> None:
    got = await admin.get(_api("/ready"))
    assert got.status_code == 503
    assert (got.json()["ready"], got.json()["object_store"], got.json()["db"]) == (
        False, "unavailable", "ok")  # fmt: skip


async def test_repeated_calls_share_one_probe(
    no_store: None, admin: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from regwatch.api import services

    calls = 0
    real = services.probe_db_query

    async def counted(factory: object) -> str:
        nonlocal calls
        calls += 1
        return await real(factory)

    monkeypatch.setattr(services, "probe_db_query", counted)
    for _ in range(5):
        assert (await admin.get(_api("/ready"))).status_code == 503
    assert calls == 1  # kept for READY_CACHE_S
