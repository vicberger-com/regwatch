"""``CaptureFetcher``: SafeFetcher with robots.txt and per-host rate limits on every hop (M3).

This is what connectors use. For each hop, the first request and every redirect target, it:

1. checks robots.txt for that host, unless the source has an admin override with a reason;
2. waits for the host's rate-limit slot, slowed by the site's Crawl-delay; a wait longer than
   ``max_wait_s`` is refused as ``rate-limited``;
3. lets SafeFetcher make the request, with all of its own checks.
"""

from __future__ import annotations

from regwatch.capture.safe_fetch.fetch import FetchResult, SafeFetcher
from regwatch.capture.safe_fetch.policy import parse_target
from regwatch.capture.safe_fetch.rate import RateLimiter, Sleep, interval, wait_turn
from regwatch.capture.safe_fetch.robots import RobotsPolicy

DEFAULT_RATE_PER_MINUTE = 30  # registries.yaml capture.default_rate_per_minute
MAX_WAIT_S = 120.0


class CaptureFetcher:
    def __init__(
        self,
        fetcher: SafeFetcher,
        limiter: RateLimiter,
        *,
        robots: RobotsPolicy | None = None,
        rate_per_minute: int = DEFAULT_RATE_PER_MINUTE,
        max_wait_s: float = MAX_WAIT_S,
        sleep: Sleep | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.limiter = limiter
        self.robots = robots or RobotsPolicy(fetcher)
        self.rate_per_minute = rate_per_minute
        self.max_wait_s = max_wait_s
        self._sleep = sleep

    async def fetch(
        self, url: str, *, rate_per_minute: int | None = None, robots_override: str | None = None
    ) -> FetchResult:
        rate = rate_per_minute or self.rate_per_minute

        async def before_hop(hop_url: str) -> None:
            delay = await self.robots.check(hop_url, override_reason=robots_override)
            host = parse_target(hop_url).host
            kwargs = {"sleep": self._sleep} if self._sleep is not None else {}
            await wait_turn(self.limiter, host, interval(rate, delay), self.max_wait_s, **kwargs)

        return await self.fetcher.fetch(url, before_hop=before_hop)
