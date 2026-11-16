"""Per-host rate limits for SafeFetcher, shared by every worker through Valkey (M3 design
notes; acceptance 5).

Each host has a "next free" time in Valkey. Taking a slot moves it on by one interval, the
larger of 60 / ``capture.default_rate_per_minute`` (or the job's own rate) and the site's
robots.txt Crawl-delay, and returns how long the caller must wait. One Lua script does this
in a single step with Valkey's own clock, so workers on several machines share one limit and
never race. A wait longer than ``max_wait_s`` is refused with reason ``rate-limited`` instead of
holding a worker; the job tries the URL again on its next run.

``MemoryRateLimiter`` gives the same behaviour within one process, for tests and tools.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from regwatch.capture.safe_fetch.policy import FetchRefusedError

Sleep = Callable[[float], Awaitable[None]]

# KEYS[1] = the host's key; ARGV[1] = interval in ms. Returns the wait in ms.
_TAKE = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local free = tonumber(redis.call('GET', KEYS[1]) or now)
if free < now then free = now end
local interval = tonumber(ARGV[1])
redis.call('SET', KEYS[1], free + interval, 'PX', interval + 60000)
return free - now
"""


class RateLimiter(Protocol):
    async def take(self, host: str, interval_s: float) -> float:
        """Reserve the host's next slot; the seconds to wait before using it."""
        ...


def interval(rate_per_minute: int, crawl_delay: float | None = None) -> float:
    """Seconds between requests to one host: the rate, slowed by Crawl-delay when larger."""
    if rate_per_minute < 1:
        raise ValueError("a rate of at least 1 request per minute is needed")
    return max(60.0 / rate_per_minute, crawl_delay or 0.0)


class ValkeyRateLimiter:
    def __init__(self, client: object, prefix: str = "regwatch:rate:") -> None:
        self._client = client
        self._prefix = prefix
        self._script = client.register_script(_TAKE)  # type: ignore[attr-defined]

    async def take(self, host: str, interval_s: float) -> float:
        wait_ms = await self._script(keys=[self._prefix + host], args=[round(interval_s * 1000)])
        return int(wait_ms) / 1000


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._free: dict[str, float] = {}

    async def take(self, host: str, interval_s: float) -> float:
        now = time.monotonic()
        free = max(self._free.get(host, now), now)
        self._free[host] = free + interval_s
        return free - now


async def wait_turn(
    limiter: RateLimiter, host: str, interval_s: float, max_wait_s: float,
    sleep: Sleep = asyncio.sleep,
) -> None:  # fmt: skip
    """Wait for the host's slot, or refuse when the wait would be longer than ``max_wait_s``."""
    wait = await limiter.take(host, interval_s)
    if wait > max_wait_s:
        raise FetchRefusedError(
            "rate-limited", f"{host} is busy for {wait:.0f} s more; tried again on the next run"
        )
    if wait > 0:
        await sleep(wait)
