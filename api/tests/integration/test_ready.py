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


async def test_the_queue_probe_authenticates() -> None:
    """The stack's Valkey has a password (BL-90): a bare PING answers NOAUTH. Found by the
    M10.2 restore drill, where /ready was 503 on a healthy stack."""
    import asyncio
    import subprocess
    import uuid

    from regwatch.api import services
    from tests.integration.test_valkey_rate import VALKEY_IMAGE, _docker

    name = f"regwatch-it-valkey-auth-{uuid.uuid4().hex[:8]}"
    secret = uuid.uuid4().hex
    await asyncio.to_thread(_docker, "run", "-d", "--rm", "--name", name, "-p", "127.0.0.1::6379",
                            VALKEY_IMAGE, "valkey-server", "--requirepass", secret)  # fmt: skip
    try:
        mapped = await asyncio.to_thread(_docker, "port", name, "6379/tcp")
        port = int(mapped.splitlines()[0].rsplit(":", 1)[1])
        url = f"redis://default:{secret}@127.0.0.1:{port}/0"
        for _ in range(50):
            if await services.probe_queue(url) == "ok":
                break
            await asyncio.sleep(0.2)
        assert await services.probe_queue(url) == "ok"
        assert await services.probe_queue(f"redis://:{secret}@127.0.0.1:{port}/0") == "ok"
        assert await services.probe_queue(f"redis://127.0.0.1:{port}/0") == "unavailable"
        assert await services.probe_queue(f"redis://default:wrong@127.0.0.1:{port}/0") == (
            "unavailable")  # fmt: skip
    finally:
        await asyncio.to_thread(subprocess.run, ["docker", "rm", "-f", name],
                                capture_output=True, check=False)  # fmt: skip
