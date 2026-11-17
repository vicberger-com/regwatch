"""The RSS and Atom connector (M3 scope; connectors.yaml ``rss``).

``discover`` fetches the feed through ``ctx.fetcher`` and parses the bytes with feedparser;
``fetch`` fetches each entry's page, or keeps the entry's own text when ``fetch_full_page`` is
off. Feeds are hostile (8.1), so:

- feedparser only ever gets bytes. Given a string it fetches it as a URL or opens it as a local
  file, either of which would bypass SafeFetcher (``_parse`` refuses anything else).
- Expat, which feedparser's strict parser uses, does not load external entities, and since
  2.4 it refuses entity expansion past an amplification limit; a feed that only parses that
  way yields nothing. Tests cover both.
- Entry links must be absolute http or https URLs after resolving against the feed's own URL;
  ``javascript:``, ``data:``, ``file:`` and the rest are dropped. SafeFetcher still checks
  every address when a page is fetched.
- Titles and summaries become plain text: every tag is removed (nh3 with no tags allowed),
  entities are decoded once, controls and runs of white space are collapsed, and lengths are
  capped. Nothing from the feed is kept as markup.
"""

from __future__ import annotations

import calendar
import hashlib
import html
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import feedparser
import nh3
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
from regwatch.capture.connectors.config import RssConfig

MAX_TITLE = 1000
MAX_SUMMARY = 5000
MAX_ID = 500
MAX_URL = 2048


def plain_text(value: Any, limit: int) -> str | None:
    """Markup from a feed as one line of plain text, or None when nothing is left."""
    if not isinstance(value, str) or not value:
        return None
    text = html.unescape(nh3.clean(value, tags=set()))
    text = "".join(c if c.isprintable() else " " for c in text)
    return " ".join(text.split())[:limit] or None


def entry_link(entry: Any, base: str) -> str | None:
    """The entry's absolute http or https link, resolved against the feed URL."""
    link = entry.get("link")
    if not isinstance(link, str) or not link.strip():
        return None
    try:
        url = urljoin(base, link.strip())
    except ValueError:
        return None
    if len(url) > MAX_URL or any(not c.isprintable() or c.isspace() for c in url):
        return None
    parts = urlsplit(url)  # urljoin above has already parsed it
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    return url


def entry_time(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return datetime.fromtimestamp(calendar.timegm(parsed), UTC)
            except (OverflowError, ValueError, OSError):
                return None
    return None


def _parse(body: bytes, url: str, content_type: str) -> Any:
    if not isinstance(body, bytes):  # a str would be fetched or opened by feedparser
        raise TypeError("feeds are parsed from bytes only")
    return feedparser.parse(body, response_headers={"content-location": url,
                                                    "content-type": content_type})  # fmt: skip


def _config(job: JobSettings) -> RssConfig:
    if not isinstance(job.config, RssConfig):
        raise TypeError("an rss job needs an RssConfig")
    return job.config


class RssConnector:
    kind = "rss"
    config_schema: type[BaseModel] = RssConfig

    async def discover(self, job: JobSettings, ctx: ConnectorContext) -> AsyncIterator[Candidate]:
        config = _config(job)
        got = await ctx.fetcher.fetch(str(config.feed_url), rate_per_minute=job.rate_per_minute,
                                      robots_override=job.robots_override)  # fmt: skip
        if not 200 <= got.status < 300:
            raise ConnectorError("http-status", f"the feed answered HTTP {got.status}")
        feed = _parse(got.body, got.url, got.headers.get("content-type", ""))
        if not feed.version:  # not RSS or Atom at all: an HTML page, an error page, noise
            raise ConnectorError("malformed-feed", "the answer is not an RSS or Atom feed")
        language = plain_text(feed.feed.get("language"), 35)
        seen: set[str] = set()
        entries = feed.entries[: min(config.max_entries, job.max_items)]
        if feed.bozo and not any(entry_link(e, got.url) for e in entries):
            raise ConnectorError("malformed-feed", "the feed could not be parsed")
        for entry in entries:
            link = entry_link(entry, got.url)
            if link is None or link in seen:
                continue
            seen.add(link)
            summary = plain_text(entry.get("summary"), MAX_SUMMARY)
            yield Candidate(
                url=link,
                title=plain_text(entry.get("title"), MAX_TITLE),
                published_at=entry_time(entry),
                external_id=plain_text(entry.get("id"), MAX_ID),
                summary=summary,
                language=plain_text(entry.get("language"), 35) or language,
            )

    async def fetch(self, candidate: Candidate, job: JobSettings,
                    ctx: ConnectorContext) -> RawDocument:  # fmt: skip
        config = _config(job)
        now = ctx.now()
        if not config.fetch_full_page:
            body = (candidate.summary or "").encode("utf-8")
            key = f"raw/{job.source_id}/{hashlib.sha256(body).hexdigest()}.txt"
            await ctx.store(key, body)
            return RawDocument(url=candidate.url, fetched_at=now, status=200, body_ref=key,
                               mime="text/plain", text=candidate.summary)  # fmt: skip
        got = await ctx.fetcher.fetch(candidate.url, rate_per_minute=job.rate_per_minute,
                                      robots_override=job.robots_override)  # fmt: skip
        key = f"raw/{job.source_id}/{hashlib.sha256(got.body).hexdigest()}"
        await ctx.store(key, got.body)
        return RawDocument(url=candidate.url, fetched_at=now, status=got.status, body_ref=key,
                           mime=got.mime or "application/octet-stream", final_url=got.url,
                           headers={k: v for k, v in got.headers.items()
                                    if k in ("content-type", "last-modified", "etag")})  # fmt: skip

    def health(self, job: JobSettings) -> HealthReport:
        return HealthReport("unknown", "health comes from the job's runs")


register(RssConnector())
