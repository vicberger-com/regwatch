"""robots.txt for SafeFetcher (M3 design notes; acceptance 4; RFC 9309).

``RobotsPolicy.check(url)`` fetches ``/robots.txt`` for the URL's origin through SafeFetcher,
with its own small size cap, caches the parsed rules per origin, and refuses a disallowed URL
with reason ``robots``. The answers follow RFC 9309 section 2.3.1:

- 2xx: the rules apply (parsed by protego). Files up to ``ROBOTS_LIMITS.max_bytes`` are read
  and the first ``PARSE_BYTES`` (500 KiB, as the RFC requires at least) are parsed;
- 4xx, including a missing file: everything is allowed, except 429 (too many requests),
  which counts as "try later" and disallows until the file is fetched again;
- 5xx, or no answer at all (refused, timed out, unreachable, larger than the read limit):
  everything is disallowed, until the cache entry expires and the file is fetched again.

Parsed rules are cached per origin in an LRU bounded by the bytes parsed, not by the number of
origins, so hostile robots files cannot fill a worker's memory (review finding 16).

An admin may override robots.txt for a source, but only with a recorded reason, which the
capture run audits; ``check`` takes the override and skips the rules then.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass

from protego import Protego

from regwatch.capture.safe_fetch.fetch import FetchLimits, SafeFetcher
from regwatch.capture.safe_fetch.policy import FetchRefusedError, parse_target

ROBOTS_LIMITS = FetchLimits(max_bytes=2 * 1024 * 1024, connect_s=10, read_s=15, total_s=30)
PARSE_BYTES = 500 * 1024
CACHE_BUDGET = 4 * 1024 * 1024  # bytes of robots.txt held parsed; about 100 MB once parsed
CACHE_SECONDS = 24 * 3600  # RFC 9309: caching for up to 24 hours is reasonable
UNREACHABLE_SECONDS = 15 * 60  # retry sooner when the file could not be fetched
PRODUCT = "regwatch"  # the user-agent token matched against robots.txt groups


@dataclass(frozen=True)
class _Rules:
    parser: Protego | None  # None: allow everything
    disallow_all: bool
    expires: float
    size: int = 0  # bytes parsed, counted against CACHE_BUDGET


class RobotsPolicy:
    def __init__(self, fetcher: SafeFetcher, product: str = PRODUCT) -> None:
        self._fetcher = fetcher.with_limits(ROBOTS_LIMITS)
        self._product = product
        self._cache: OrderedDict[str, _Rules] = OrderedDict()
        self._held = 0

    def is_cached(self, origin: str) -> bool:
        """Whether the origin's rules are known and fresh, so ``check`` will not fetch."""
        cached = self._cache.get(origin)
        return cached is not None and cached.expires > time.monotonic()

    def _store(self, origin: str, rules: _Rules) -> None:
        old = self._cache.pop(origin, None)
        if old is not None:
            self._held -= old.size
        self._cache[origin] = rules
        self._held += rules.size
        while self._held > CACHE_BUDGET or len(self._cache) > 10_000:
            _, dropped = self._cache.popitem(last=False)  # least recently used first
            self._held -= dropped.size

    async def _rules(self, origin: str) -> _Rules:
        now = time.monotonic()
        cached = self._cache.get(origin)
        if cached is not None and cached.expires > now:
            self._cache.move_to_end(origin)
            return cached
        try:
            got = await self._fetcher.fetch(origin + "/robots.txt")
        except FetchRefusedError:
            rules = _Rules(None, True, now + UNREACHABLE_SECONDS)
        else:
            if 200 <= got.status < 300:
                text = got.body[:PARSE_BYTES].decode("utf-8", errors="replace")
                rules = _Rules(Protego.parse(text), False, now + CACHE_SECONDS, len(text))
            elif 400 <= got.status < 500 and got.status != 429:
                rules = _Rules(None, False, now + CACHE_SECONDS)
            else:  # 429, 5xx, or a redirect SafeFetcher did not follow (no Location)
                rules = _Rules(None, True, now + UNREACHABLE_SECONDS)
        self._store(origin, rules)
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
