"""The Valkey rate limiter against a throwaway Valkey (M3 acceptance 5, workers share limits)."""

from __future__ import annotations

import asyncio
import subprocess
import time
import uuid
from collections.abc import AsyncIterator

import pytest
import redis.asyncio as redis

from regwatch.capture.safe_fetch import ValkeyRateLimiter

pytestmark = pytest.mark.integration
VALKEY_IMAGE = (
    "valkey/valkey:9@sha256:3add1a336a920ea54770a001ab6feb3da5fceea96a40373a3a2cd469b815f0b7"
)


def _docker(*args: str) -> str:
    done = subprocess.run(["docker", *args], capture_output=True, text=True, check=True)  # noqa: S603, S607
    return done.stdout.strip()


@pytest.fixture
async def valkey() -> AsyncIterator[redis.Redis]:
    name = f"regwatch-it-valkey-{uuid.uuid4().hex[:8]}"
    await asyncio.to_thread(
        _docker, "run", "-d", "--rm", "--name", name, "-p", "127.0.0.1::6379", VALKEY_IMAGE
    )
    try:
        mapped = await asyncio.to_thread(_docker, "port", name, "6379/tcp")
        port = int(mapped.splitlines()[0].rsplit(":", 1)[1])
        client = redis.Redis(host="127.0.0.1", port=port)
        deadline = time.monotonic() + 30
        while True:
            try:
                await client.ping()
                break
            except redis.ConnectionError:
                if time.monotonic() > deadline:
                    raise
                await asyncio.sleep(0.2)
        yield client
        await client.aclose()
    finally:
        await asyncio.to_thread(
            subprocess.run, ["docker", "rm", "-f", "-v", name], capture_output=True, check=False
        )


async def test_slots_are_shared_and_spaced(valkey: redis.Redis) -> None:
    limiter = ValkeyRateLimiter(valkey)
    first = await limiter.take("example.org", 6.0)
    second = await limiter.take("example.org", 6.0)
    assert first == 0.0 and 5.9 <= second <= 6.0
    assert await limiter.take("other.example", 6.0) == 0.0
    ttl = await valkey.pttl("regwatch:rate:example.org")
    assert 0 < ttl <= 6000 * 2 + 60_000


async def test_concurrent_workers_never_share_a_slot(valkey: redis.Redis) -> None:
    """Two clients, as two workers would be, taking 20 slots at once: every wait is distinct."""
    other = redis.Redis(connection_pool=valkey.connection_pool)
    a, b = ValkeyRateLimiter(valkey), ValkeyRateLimiter(other)
    waits = await asyncio.gather(
        *[(a if i % 2 else b).take("busy.example", 1.0) for i in range(20)]
    )
    steps = sorted(round(w) for w in waits)
    assert steps == list(range(20))
