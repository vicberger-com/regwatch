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
import math
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from regwatch.capture.safe_fetch.policy import FetchRefusedError

Sleep = Callable[[float], Awaitable[None]]

# KEYS[1] = the host's key; ARGV[1] = interval in ms; ARGV[2] = longest acceptable wait in ms.
# Returns the wait in ms, or -1 when it would be longer than ARGV[2]: then nothing is reserved,
# so refused requests never push the host's slots back (review finding 14). The key lives until
# the last reserved slot has passed, plus a minute, so queued slots never expire early (15).
_TAKE = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local free = tonumber(redis.call('GET', KEYS[1]) or now)
if free < now then free = now end
if free - now > tonumber(ARGV[2]) then return -1 end
local nxt = free + tonumber(ARGV[1])
redis.call('SET', KEYS[1], nxt, 'PX', nxt - now + 60000)
return free - now
"""
MAX_INTERVAL_S = 3600.0  # a Crawl-delay above an hour is treated as an hour (finding 17)


class RateLimiter(Protocol):
    async def take(self, host: str, interval_s: float, max_wait_s: float) -> float | None:
        """Reserve the host's next slot and return the seconds to wait, or None, reserving
        nothing, when the wait would be longer than ``max_wait_s``."""
        ...


def interval(rate_per_minute: int, crawl_delay: float | None = None) -> float:
    """Seconds between requests to one host: the rate, slowed by Crawl-delay when larger,
    never more than ``MAX_INTERVAL_S`` and never under a millisecond."""
    if rate_per_minute < 1:
        raise ValueError("a rate of at least 1 request per minute is needed")
    return _clamp(max(60.0 / rate_per_minute, crawl_delay or 0.0))


def _check_wait(max_wait_s: float) -> None:
    """A NaN or negative longest wait would accept every request or none (review finding 27)."""
    if not 0 <= max_wait_s < math.inf:
        raise ValueError("the longest wait must be a finite number of seconds, at least 0")


def _clamp(seconds: float) -> float:
    """Every limiter clamps too, so none relies on its callers using ``interval`` (25 (b))."""
    if seconds != seconds:  # NaN
        return MAX_INTERVAL_S
    return min(max(seconds, 0.001), MAX_INTERVAL_S)


class ValkeyRateLimiter:
    def __init__(self, client: object, prefix: str = "regwatch:rate:") -> None:
        self._client = client
        self._prefix = prefix
        self._script = client.register_script(_TAKE)  # type: ignore[attr-defined]

    async def take(self, host: str, interval_s: float, max_wait_s: float) -> float | None:
        _check_wait(max_wait_s)
        # ceil: an interval is never shortened
        args = [math.ceil(_clamp(interval_s) * 1000), math.floor(max_wait_s * 1000)]
        wait_ms = int(await self._script(keys=[self._prefix + host], args=args))
        return None if wait_ms < 0 else wait_ms / 1000


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._free: dict[str, float] = {}

    async def take(self, host: str, interval_s: float, max_wait_s: float) -> float | None:
        _check_wait(max_wait_s)
        now = time.monotonic()
        free = max(self._free.get(host, now), now)
        if free - now > max_wait_s:
            return None
        self._free[host] = free + _clamp(interval_s)
        return free - now


async def wait_turn(
    limiter: RateLimiter, host: str, interval_s: float, max_wait_s: float,
    sleep: Sleep = asyncio.sleep,
) -> None:  # fmt: skip
    """Wait for the host's slot, or refuse when the wait would be longer than ``max_wait_s``."""
    wait = await limiter.take(host, interval_s, max_wait_s)
    if wait is None:
        raise FetchRefusedError(
            "rate-limited", f"{host} is busy for over {max_wait_s:g} s; tried again next run"
        )
    if wait > 0:
        await sleep(wait)
