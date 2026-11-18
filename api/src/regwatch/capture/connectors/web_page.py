"""The web page connector, single mode (M3 scope: single web page with change detection; M3
acceptance 2; connectors.yaml ``web_page``; ADR-0009; CP-16).

- One candidate per run: ``page_url``. It is fetched through ``ctx.fetcher`` (SafeFetcher,
  robots.txt, the per-host rate), must answer 2xx with HTML, and its raw body is stored.
- The text comes from ``extract_isolated``: a child process per page with hard limits, never an
  in-process parse of captured HTML (HTML extraction review R4, BL-98). A run fetches its
  documents one after another, so a worker process runs at most one child at a time.
- Change detection (CP-16): the job's cursor holds the last content hash and the object store
  key of its text. The same hash is ``unchanged``: counted, nothing stored, nothing for M4. Any
  other hash is ``changed`` (``new`` on the first run) and goes to M4 with the previous text's
  key, and the baseline moves. How much a page changed, and whether it is worth an event, is
  M4's decision: its threshold counts characters, and a status change is always an event (M4
  spec). M3 never drops a change (web page review findings 1 and 2).
- The raw body is stored only for a new or changed page, so unchanged runs leave no objects
  behind (finding 5).
- ``listing`` mode and ``render_js`` answer ``not-implemented`` until they land.
"""

from __future__ import annotations

import hashlib
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
        before = job.cursor or {}
        if before.get("content_hash") == found.content_hash:
            change = "unchanged"  # counted only: nothing stored, nothing for M4
        else:
            change = "changed" if before.get("content_hash") else "new"
            text_ref = f"text/{job.source_id}/{found.content_hash}.txt"
            await ctx.store(text_ref, found.text.encode())
            ctx.state = {"content_hash": found.content_hash, "text_ref": text_ref}
        key = f"raw/{job.source_id}/{hashlib.sha256(got.body).hexdigest()}"
        if change != "unchanged":
            await ctx.store(key, got.body)
        previous = before.get("text_ref") if change == "changed" else None
        metadata: dict[str, Any] = {"title": found.title, "method": found.method,
                                    "warnings": found.warnings, "content_hash": found.content_hash,
                                    # For M4's diff; its own key checks apply when it reads it.
                                    "previous_text_ref": previous if isinstance(previous, str)
                                    else None,
                                    "published_at": found.published_at.isoformat()
                                    if found.published_at else None}  # fmt: skip
        return RawDocument(url=candidate.url, fetched_at=ctx.now(), status=got.status,
                           body_ref=key, mime=got.mime or "text/html", final_url=got.url,
                           text=found.text, metadata=metadata, change=change,
                           headers={k: v for k, v in got.headers.items()
                                    if k in ("content-type", "last-modified", "etag")})  # fmt: skip

    def health(self, job: JobSettings) -> HealthReport:
        return HealthReport("unknown", "health comes from the job's runs")


register(WebPageConnector())
