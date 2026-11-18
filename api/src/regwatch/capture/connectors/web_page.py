"""The web page connector, single mode (M3 scope: single web page with change detection; M3
acceptance 2; connectors.yaml ``web_page``; ADR-0009; CP-16).

- One candidate per run: ``page_url``. It is fetched through ``ctx.fetcher`` (SafeFetcher,
  robots.txt, the per-host rate), must answer 2xx with HTML, and its raw body is stored.
- The text comes from ``extract_isolated``: a child process per page with hard limits, never an
  in-process parse of captured HTML (HTML extraction review R4, BL-98). A run fetches its
  documents one after another, so a worker process runs at most one child at a time.
- Change detection: the job's cursor holds the last content hash and the object store key of
  its text (CP-16). The same hash is ``unchanged``. A different one is compared line by line:
  the share of lines added or removed, against the job's ``change_threshold_pct``. Below the
  threshold the page counts as ``unchanged`` and the stored baseline stays, so slow drift adds
  up until it crosses the threshold; at or above it, the page is ``changed`` and the baseline
  moves. The first run is ``new``.
- ``listing`` mode and ``render_js`` answer ``not-implemented`` until they land.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from regwatch.capture.connectors.base import (
    Candidate,
    ConnectorContext,
    ConnectorError,
    HealthReport,
    JobSettings,
    RawDocument,
    register,
)
from regwatch.capture.connectors.config import ExtractionRules, WebPageConfig
from regwatch.capture.extract.isolate import extract_isolated
from regwatch.capture.extract.tree import ParseError

HTML = frozenset({"text/html", "application/xhtml+xml"})


def changed_pct(before: str, after: str) -> float:
    """Lines added or removed, as a share of all lines of both texts (0 to 100). Linear: a
    multiset difference, not a diff, which would be quadratic on hostile text."""
    old, new = Counter(before.split("\n")), Counter(after.split("\n"))
    changed = sum((old - new).values()) + sum((new - old).values())
    total = sum(old.values()) + sum(new.values())
    return round(100.0 * changed / total, 2) if total else 0.0


def _charset(content_type: str) -> str | None:
    for part in content_type.split(";")[1:]:
        name, _, value = part.strip().partition("=")
        if name.lower() == "charset" and value:
            return value.strip("\"' ")[:40]
    return None


class WebPageConnector:
    kind = "web_page"
    config_schema: type[BaseModel] = WebPageConfig

    async def discover(self, job: JobSettings, ctx: ConnectorContext) -> AsyncIterator[Candidate]:
        config = job.config
        assert isinstance(config, WebPageConfig)  # noqa: S101 - job_settings validated it
        if job.render_js:
            raise ConnectorError("not-implemented", "JavaScript rendering is not built yet")
        if config.mode != "single":
            raise ConnectorError("not-implemented", "listing mode is not built yet")
        yield Candidate(url=str(config.page_url))

    async def fetch(self, candidate: Candidate, job: JobSettings,
                    ctx: ConnectorContext) -> RawDocument:  # fmt: skip
        got = await ctx.fetcher.fetch(candidate.url, rate_per_minute=job.rate_per_minute,
                                      robots_override=job.robots_override)  # fmt: skip
        if not 200 <= got.status < 300:
            raise ConnectorError("http-status", f"the page answered HTTP {got.status}")
        if (got.mime or "") not in HTML:
            raise ConnectorError("not-html", "the page is not HTML")
        rules = job.rules if isinstance(job.rules, ExtractionRules) else ExtractionRules()
        try:
            found = await extract_isolated(got.body, _charset(got.headers.get("content-type", "")),
                                           rules)  # fmt: skip
        except ParseError as exc:
            raise ConnectorError(
                exc.reason, "the page could not be read within the limits"
            ) from None
        key = f"raw/{job.source_id}/{hashlib.sha256(got.body).hexdigest()}"
        await ctx.store(key, got.body)
        change, pct = await _compare(found.text, found.content_hash, job, ctx)
        metadata: dict[str, Any] = {"title": found.title, "method": found.method,
                                    "warnings": found.warnings, "content_hash": found.content_hash,
                                    "changed_pct": pct,
                                    "published_at": found.published_at.isoformat()
                                    if found.published_at else None}  # fmt: skip
        return RawDocument(url=candidate.url, fetched_at=ctx.now(), status=got.status,
                           body_ref=key, mime=got.mime or "text/html", final_url=got.url,
                           text=found.text, metadata=metadata, change=change,
                           headers={k: v for k, v in got.headers.items()
                                    if k in ("content-type", "last-modified", "etag")})  # fmt: skip

    def health(self, job: JobSettings) -> HealthReport:
        return HealthReport("unknown", "health comes from the job's runs")


async def _compare(text: str, digest: str, job: JobSettings,
                   ctx: ConnectorContext) -> tuple[str, float | None]:  # fmt: skip
    """("new" | "changed" | "unchanged", the changed share or None), and the next state."""
    before = job.cursor or {}
    if before.get("content_hash") == digest:
        return "unchanged", 0.0
    text_ref = f"text/{job.source_id}/{digest}.txt"
    previous: bytes | None = None
    ref = before.get("text_ref")
    if isinstance(ref, str) and ref.startswith(f"text/{job.source_id}/") and ctx.load is not None:
        previous = await ctx.load(ref)
    if previous is not None:
        pct = changed_pct(previous.decode("utf-8", errors="replace"), text)
        if pct < job.change_threshold_pct:
            return "unchanged", pct  # the baseline stays, so small changes add up
    await ctx.store(text_ref, text.encode())
    ctx.state = {"content_hash": digest, "text_ref": text_ref}
    if previous is None:
        return ("changed" if before.get("content_hash") else "new"), None
    return "changed", pct


register(WebPageConnector())
