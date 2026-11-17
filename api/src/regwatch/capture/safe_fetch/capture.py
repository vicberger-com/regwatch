"""``CaptureFetcher``: SafeFetcher with robots.txt and per-host rate limits on every hop (M3).

This is what connectors use. For each hop, the first request and every redirect target, it:

1. checks the URL and its addresses first, so a private target is reported as
   ``private-address``, not hidden behind a robots or rate answer (review finding 19);
2. checks robots.txt for that host, unless the source has an admin override with a reason; a
   robots.txt fetch takes a rate slot of its own (finding 18), reserved only by the check that
   actually fetches it (finding 25 (a));
3. waits for the host's rate-limit slot, slowed by the site's Crawl-delay; a wait longer than
   ``max_wait_s`` is refused as ``rate-limited``;
4. lets SafeFetcher make the request, with all of its own checks.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from regwatch.capture.safe_fetch.fetch import FetchResult, SafeFetcher
from regwatch.capture.safe_fetch.policy import FetchRefusedError
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
        self, url: str, *, rate_per_minute: int | None = None, robots_override: str | None = None,
        refuse_hosts: frozenset[str] = frozenset(),
        allow_hop: Callable[[str], bool] | None = None,
        headers: Mapping[str, str] | None = None, upgrade_hosts: frozenset[str] = frozenset(),
    ) -> FetchResult:  # fmt: skip
        """``refuse_hosts`` are hosts no hop may reach, and ``allow_hop``, when given, must accept
        every hop's URL, redirects included. Both are checked before robots.txt, the rate slot and
        the request, so a refused hop is never contacted (API feed review 5; legislation
        re-verification R1)."""
        rate = self.rate_per_minute if rate_per_minute is None else rate_per_minute
        kwargs = {"sleep": self._sleep} if self._sleep is not None else {}

        async def before_hop(hop_url: str) -> None:
            target = await self.fetcher.check_url(hop_url)
            if target.host in refuse_hosts or (allow_hop is not None and not allow_hop(hop_url)):
                raise FetchRefusedError("refused-host", f"{target.host} is not contacted")

            async def robots_slot() -> None:
                await wait_turn(
                    self.limiter, target.host, interval(rate), self.max_wait_s, **kwargs
                )

            delay = await self.robots.check(
                hop_url, override_reason=robots_override, before_fetch=robots_slot
            )
            spacing = interval(rate, delay)
            await wait_turn(self.limiter, target.host, spacing, self.max_wait_s, **kwargs)

        return await self.fetcher.fetch(url, before_hop=before_hop, headers=headers,
                                        upgrade_hosts=upgrade_hosts)  # fmt: skip
