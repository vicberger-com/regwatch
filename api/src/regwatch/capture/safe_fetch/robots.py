"""robots.txt for SafeFetcher (M3 design notes; acceptance 4; RFC 9309).

``RobotsPolicy.check(url)`` fetches ``/robots.txt`` for the URL's origin through SafeFetcher,
with its own small size cap, caches the parsed rules per origin, and refuses a disallowed URL
with reason ``robots``. The answers follow RFC 9309 section 2.3.1:

- 2xx: the rules apply (parsed by protego);
- 4xx, including a missing file: everything is allowed;
- 5xx, or no answer at all (refused, timed out, unreachable): everything is disallowed, until
  the cache entry expires and the file is fetched again.

An admin may override robots.txt for a source, but only with a recorded reason, which the
capture run audits; ``check`` takes the override and skips the rules then.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from protego import Protego

from regwatch.capture.safe_fetch.fetch import FetchLimits, SafeFetcher
from regwatch.capture.safe_fetch.policy import FetchRefusedError, parse_target

ROBOTS_LIMITS = FetchLimits(max_bytes=512 * 1024, connect_s=10, read_s=15, total_s=30)
CACHE_SECONDS = 24 * 3600  # RFC 9309: caching for up to 24 hours is reasonable
UNREACHABLE_SECONDS = 15 * 60  # retry sooner when the file could not be fetched
PRODUCT = "regwatch"  # the user-agent token matched against robots.txt groups


@dataclass(frozen=True)
class _Rules:
    parser: Protego | None  # None: allow everything
    disallow_all: bool
    expires: float


class RobotsPolicy:
    def __init__(self, fetcher: SafeFetcher, product: str = PRODUCT) -> None:
        self._fetcher = fetcher.with_limits(ROBOTS_LIMITS)
        self._product = product
        self._cache: dict[str, _Rules] = {}

    async def _rules(self, origin: str) -> _Rules:
        now = time.monotonic()
        cached = self._cache.get(origin)
        if cached is not None and cached.expires > now:
            return cached
        try:
            got = await self._fetcher.fetch(origin + "/robots.txt")
        except FetchRefusedError:
            rules = _Rules(None, True, now + UNREACHABLE_SECONDS)
        else:
            if 200 <= got.status < 300:
                text = got.body.decode("utf-8", errors="replace")
                rules = _Rules(Protego.parse(text), False, now + CACHE_SECONDS)
            elif 400 <= got.status < 500:
                rules = _Rules(None, False, now + CACHE_SECONDS)
            else:  # 5xx, or a redirect SafeFetcher did not follow (no Location)
                rules = _Rules(None, True, now + UNREACHABLE_SECONDS)
        if len(self._cache) > 10_000:
            self._cache.clear()  # a bound on memory; origins are re-fetched as needed
        self._cache[origin] = rules
        return rules

    async def check(self, url: str, override_reason: str | None = None) -> float | None:
        """Refuse a URL robots.txt disallows; return the site's Crawl-delay, if it gives one.

        ``override_reason`` is the admin's recorded reason for ignoring robots.txt on this
        source; with it the rules are not consulted (acceptance 4).
        """
        if override_reason is not None:
            if not override_reason.strip():
                raise ValueError("a robots.txt override needs a reason")
            return None
        target = parse_target(url)
        rules = await self._rules(target.origin)
        if rules.disallow_all:
            raise FetchRefusedError(
                "robots", f"{target.host} robots.txt could not be read, so nothing is fetched"
            )
        if rules.parser is None:
            return None
        if not rules.parser.can_fetch(url, self._product):
            raise FetchRefusedError("robots", f"robots.txt of {target.host} disallows {url}")
        delay = rules.parser.crawl_delay(self._product)
        return float(delay) if delay is not None else None
