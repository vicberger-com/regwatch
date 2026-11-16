"""SafeFetcher: the only way the application fetches from external hosts (ADR-0001, 8.2, M3).

Security-critical (7.1: 100 percent unit coverage). This package holds:

- ``policy``: which URLs and addresses may be fetched at all, checked when a source is
  configured and again, after DNS resolution, before every connection.
- ``fetch``: ``SafeFetcher.fetch``, one pinned connection per hop, re-checked redirects, and
  caps on body size and time.
- ``robots``: ``RobotsPolicy``, robots.txt per RFC 9309, with an audited admin override.
- ``rate``: per-host rate limits shared by all workers through Valkey.
- ``capture``: ``CaptureFetcher``, which connectors use: robots.txt and the rate limit on
  every hop, then SafeFetcher.
"""

from regwatch.capture.safe_fetch.capture import CaptureFetcher
from regwatch.capture.safe_fetch.fetch import FetchLimits, FetchResult, SafeFetcher
from regwatch.capture.safe_fetch.policy import (
    FetchRefusedError,
    Target,
    check_address,
    parse_target,
    resolve,
    validate_source_url,
)
from regwatch.capture.safe_fetch.rate import MemoryRateLimiter, ValkeyRateLimiter
from regwatch.capture.safe_fetch.robots import RobotsPolicy

__all__ = [
    "CaptureFetcher",
    "MemoryRateLimiter",
    "ValkeyRateLimiter",
    "FetchLimits",
    "FetchRefusedError",
    "FetchResult",
    "RobotsPolicy",
    "SafeFetcher",
    "Target",
    "check_address",
    "parse_target",
    "resolve",
    "validate_source_url",
]
