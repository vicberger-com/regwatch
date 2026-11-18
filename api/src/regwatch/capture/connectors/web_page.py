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
- Listing mode: the listing page is fetched and extracted like any page, and the hrefs that
  ``listing_link_selector`` matches become candidates: resolved against the page's final URL,
  checked as any captured link (``rss.entry_link``), filtered by the URL patterns (RE2), each
  once, at most ``max_links`` (more makes the run ``truncated``). The listing page itself is
  not a document. Each linked page is compared with its own last hash, kept per URL in one
  content-addressed object (``state/{source_id}/{sha256}.json``) the cursor points to; a page no
  longer listed drops out of it.
- ``render_js`` answers ``not-implemented`` until it lands.
"""

from __future__ import annotations

import hashlib
import json
import re
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
from regwatch.capture.connectors.rss import entry_link
from regwatch.capture.extract.isolate import ParseError, extract_isolated

HTML = frozenset({"text/html", "application/xhtml+xml"})


def _charset(content_type: str) -> str | None:
    for part in content_type.split(";")[1:]:
        name, _, value = part.strip().partition("=")
        if name.lower() == "charset" and value:
            return value.strip("\"' ")[:40]
    return None


def _own_text_ref(value: Any, source_id: str) -> str | None:
    """The previous text's key, only if it is exactly one this source wrote: a stale or edited
    cursor must never point M4's diff at another source's object (re-verification R1)."""
    if isinstance(value, str) and re.fullmatch(rf"text/{re.escape(source_id)}/[0-9a-f]{{64}}\.txt",
                                               value):  # fmt: skip
        return value
    return None


def _own_listing_ref(value: Any, source_id: str) -> str | None:
    if isinstance(value, str) and re.fullmatch(
            rf"state/{re.escape(source_id)}/[0-9a-f]{{64}}\.json", value):  # fmt: skip
        return value
    return None


async def _get_html(url: str, job: JobSettings, ctx: ConnectorContext) -> Any:  # noqa: ANN401
    got = await ctx.fetcher.fetch(url, rate_per_minute=job.rate_per_minute,
                                  robots_override=job.robots_override)  # fmt: skip
    if not 200 <= got.status < 300:
        raise ConnectorError("http-status", f"the page answered HTTP {got.status}")
    if (got.mime or "") not in HTML:
        raise ConnectorError("not-html", "the page is not HTML")
    return got


async def _extract(got: Any, job: JobSettings, links: str | None = None) -> Any:  # noqa: ANN401
    rules = job.rules if isinstance(job.rules, ExtractionRules) else ExtractionRules()
    try:
        return await extract_isolated(got.body, _charset(got.headers.get("content-type", "")),
                                      rules, links)  # fmt: skip
    except ParseError as exc:
        raise ConnectorError(exc.reason, "the page could not be read within the limits") from None


def _url_filter(rules: Any) -> Any:  # noqa: ANN401 - RE2 patterns have no stubs
    """include and exclude URL patterns, RE2 as match rules are (checked when saved)."""
    from regwatch.taxonomy.rules import PatternError, compile_pattern

    try:
        include = [compile_pattern(x) for x in getattr(rules, "include_url_patterns", [])]
        exclude = [compile_pattern(x) for x in getattr(rules, "exclude_url_patterns", [])]
    except PatternError as exc:
        raise ConnectorError("bad-config", f"a URL pattern: {exc}") from None

    def keep(url: str) -> bool:
        return ((not include or any(p.search(url) for p in include))
                and not any(p.search(url) for p in exclude))  # fmt: skip

    return keep


async def _previous_listing(job: JobSettings, ctx: ConnectorContext) -> dict[str, list[str]]:
    """The last run's {url: [content_hash, text_ref]}, or {} when there is none or it is not
    exactly this source's, or not what this connector wrote."""
    ref = _own_listing_ref((job.cursor or {}).get("listing_ref"), job.source_id)
    try:
        raw = await ctx.load(ref) if ref and ctx.load is not None else None
        data = json.loads(raw) if raw else {}
    except (OSError, ValueError):  # a missing, unreadable or broken object: start afresh
        return {}
    if not isinstance(data, dict):
        return {}
    return {u: v for u, v in data.items()
            if isinstance(u, str) and isinstance(v, list) and len(v) == 2
            and all(isinstance(x, str) for x in v)}  # fmt: skip


class WebPageConnector:
    kind = "web_page"
    config_schema: type[BaseModel] = WebPageConfig

    async def discover(self, job: JobSettings, ctx: ConnectorContext) -> AsyncIterator[Candidate]:
        config = job.config
        assert isinstance(config, WebPageConfig)  # noqa: S101 - job_settings validated it
        if job.render_js:
            raise ConnectorError("not-implemented", "JavaScript rendering is not built yet")
        if config.mode == "single":
            before = job.cursor or {}
            yield Candidate(url=str(config.page_url),
                            hints={"previous": [before.get("content_hash"),
                                                before.get("text_ref")]})  # fmt: skip
            return
        if not config.listing_link_selector:
            raise ConnectorError("bad-config", "listing mode needs listing_link_selector")
        got = await _get_html(str(config.page_url), job, ctx)
        listing = await _extract(got, job, config.listing_link_selector)
        keep = _url_filter(job.rules)
        previous = await _previous_listing(job, ctx)
        seen: list[str] = []
        for href in listing.links:
            url = entry_link({"link": href}, got.url)
            if url is None or url in seen or not keep(url):
                continue
            if len(seen) >= config.max_links:
                ctx.notes.add("truncated")  # more links than max_links
                break
            seen.append(url)
        ctx.scratch["listing"] = {"listed": seen, "pages": {}, "previous": previous}
        for url in seen:
            yield Candidate(url=url, hints={"previous": previous.get(url, [None, None])})

    async def fetch(self, candidate: Candidate, job: JobSettings,
                    ctx: ConnectorContext) -> RawDocument:  # fmt: skip
        got = await _get_html(candidate.url, job, ctx)
        found = await _extract(got, job)
        before_hash, before_ref = (candidate.hints.get("previous") or [None, None])[:2]
        text_ref = f"text/{job.source_id}/{found.content_hash}.txt"
        if before_hash == found.content_hash:
            change = "unchanged"  # counted only: nothing stored, nothing for M4
        else:
            change = "changed" if before_hash else "new"
            await ctx.store(text_ref, found.text.encode())
        listing = ctx.scratch.get("listing")
        if listing is not None:
            listing["pages"][candidate.url] = [found.content_hash, text_ref]
        elif change != "unchanged":
            ctx.state = {"content_hash": found.content_hash, "text_ref": text_ref}
        key = f"raw/{job.source_id}/{hashlib.sha256(got.body).hexdigest()}"
        if change != "unchanged":
            await ctx.store(key, got.body)
        previous = _own_text_ref(before_ref, job.source_id) if change == "changed" else None
        metadata: dict[str, Any] = {"title": found.title, "method": found.method,
                                    "warnings": found.warnings, "content_hash": found.content_hash,
                                    # For M4's diff; its own key checks apply when it reads it.
                                    "previous_text_ref": previous,
                                    "published_at": found.published_at.isoformat()
                                    if found.published_at else None}  # fmt: skip
        return RawDocument(url=candidate.url, fetched_at=ctx.now(), status=got.status,
                           body_ref=key, mime=got.mime or "text/html", final_url=got.url,
                           text=found.text, metadata=metadata, change=change,
                           headers={k: v for k, v in got.headers.items()
                                    if k in ("content-type", "last-modified", "etag")})  # fmt: skip

    async def finish(self, job: JobSettings, ctx: ConnectorContext) -> None:
        """After every candidate was handled: listing mode writes the pages' hashes, for the
        pages still listed, as one content-addressed object the cursor points to (CP-16)."""
        listing = ctx.scratch.get("listing")
        if listing is None:
            return
        pages = {u: listing["pages"].get(u) or listing["previous"].get(u)
                 for u in listing["listed"]}  # fmt: skip
        body = json.dumps({u: v for u, v in pages.items() if v}, sort_keys=True).encode()
        key = f"state/{job.source_id}/{hashlib.sha256(body).hexdigest()}.json"
        await ctx.store(key, body)
        ctx.state = {"listing_ref": key}

    def health(self, job: JobSettings) -> HealthReport:
        return HealthReport("unknown", "health comes from the job's runs")


register(WebPageConnector())
