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
    first = await limiter.take("example.org", 6.0, 120)
    second = await limiter.take("example.org", 6.0, 120)
    assert first == 0.0 and second is not None and 5.9 <= second <= 6.0
    assert await limiter.take("other.example", 6.0, 120) == 0.0


async def test_refusals_reserve_nothing_and_keys_outlive_their_slots(valkey: redis.Redis) -> None:
    """Review findings 14 and 15 against the real script."""
    limiter = ValkeyRateLimiter(valkey)
    for _ in range(70):
        assert await limiter.take("queue.example", 1.0, 120) is not None  # 70 s queued
    ttl = await valkey.pttl("regwatch:rate:queue.example")
    assert ttl > 70_000  # the key lives past the last queued slot (15)
    free_before = int(await valkey.get("regwatch:rate:queue.example"))
    for _ in range(50):
        assert await limiter.take("queue.example", 1.0, 10) is None  # refused (14)
    assert int(await valkey.get("regwatch:rate:queue.example")) == free_before


async def test_concurrent_workers_never_share_a_slot(valkey: redis.Redis) -> None:
    """Two clients, as two workers would be, taking 20 slots at once: every wait is distinct."""
    other = redis.Redis(connection_pool=valkey.connection_pool)
    a, b = ValkeyRateLimiter(valkey), ValkeyRateLimiter(other)
    waits = await asyncio.gather(
        *[(a if i % 2 else b).take("busy.example", 1.0, 120) for i in range(20)]
    )
    steps = sorted(round(w) for w in waits)
    assert steps == list(range(20))


async def test_acceptance_5_with_valkey_and_the_fixture_server(valkey: redis.Redis) -> None:
    """Acceptance 5 end to end, sped up: 30 pages at 600 a minute (one per 100 ms), robots.txt
    included, through the real Valkey limiter and the fixture server; at most 10 a second.

    Residual 21: the arrival times are checked window by window, so requests bunched at the
    end would fail, and 25 (a): one robots slot, so the crawl takes about 3 s, not 6."""
    from regwatch.capture.safe_fetch import CaptureFetcher
    from tests.support.fixture_server import FixtureServer
    from tests.unit.test_safe_fetch_fetch import FIXTURES, PinnedFetcher

    server = FixtureServer().start()
    try:
        server.state.reset()
        fetcher = PinnedFetcher({FIXTURES: "127.0.0.1"})
        capture = CaptureFetcher(fetcher, ValkeyRateLimiter(valkey), rate_per_minute=600)
        started = time.monotonic()
        await asyncio.gather(*[
            capture.fetch(f"http://{FIXTURES}:{server.port}/pages/listing/item-{n}.html")
            for n in range(30)
        ])  # fmt: skip
        elapsed = time.monotonic() - started
        assert len(server.state.requests) == 31  # robots.txt and 30 pages
        assert 2.9 <= elapsed < 4.5  # 31 slots, 100 ms apart, none wasted
        arrived = sorted(r.at for r in server.state.requests)
        # Any 11 consecutive arrivals span at least 1 s (less 50 ms of scheduling jitter), so
        # no window of 0.95 s holds more than 10 requests.
        assert min(b - a for a, b in zip(arrived, arrived[10:], strict=False)) >= 0.95
    finally:
        server.stop()
