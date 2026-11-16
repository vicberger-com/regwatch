"""SafeFetcher: the only way the application fetches from external hosts (ADR-0001, 8.2, M3).

Security-critical (7.1: 100 percent unit coverage). This package holds:

- ``policy``: which URLs and addresses may be fetched at all, checked when a source is
  configured and again, after DNS resolution, before every connection.
- ``fetch``: ``SafeFetcher.fetch``, one pinned connection per hop, re-checked redirects, and
  caps on body size and time.
"""

from regwatch.capture.safe_fetch.fetch import FetchLimits, FetchResult, SafeFetcher
from regwatch.capture.safe_fetch.policy import (
    FetchRefusedError,
    Target,
    check_address,
    parse_target,
    resolve,
    validate_source_url,
)

__all__ = [
    "FetchLimits",
    "FetchRefusedError",
    "FetchResult",
    "SafeFetcher",
    "Target",
    "check_address",
    "parse_target",
    "resolve",
    "validate_source_url",
]
