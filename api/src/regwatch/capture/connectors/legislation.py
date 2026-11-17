"""The legislation.gov.uk adapter of the API feed connector (R-06 section 3 and the section 4
starter configuration).

- One title search per term: ``https://www.legislation.gov.uk/{type}/data.feed?title=...&sort=``.
  Paging follows the feed's own ``rel="next"`` link only, on the same host and path, at most
  ``max_pages_per_term`` pages (20 entries each). Pages left over make the run ``truncated``.
- Each page is Atom, parsed like any feed: the expat pre-check, then feedparser from bytes
  (``rss._parse``); titles and summaries become plain text.
- The fair use policy refuses anonymous user agents and recommends contact details (E-UK-3), so
  the adapter refuses to run while the user agent names no contact address (BL-29).
- A document is the entry's ``data.xml`` (robots.txt allows it; ``*/data.pdf`` and
  ``*/data.docx`` are disallowed), or the HTML page when ``fetch_format`` is ``html``. Links must
  be https on www.legislation.gov.uk. The stored XML is hostile like any capture: M4 parses it.
- The 1,500 requests per 5 minutes limit and robots.txt's Crawl-delay 5 are enforced by the
  per-host rate limiter, which takes the slower of the job's rate and the Crawl-delay.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode, urlsplit

import anyio

from regwatch.capture.connectors.base import (
    Candidate,
    ConnectorContext,
    ConnectorError,
    JobSettings,
    RawDocument,
)
from regwatch.capture.connectors.rss import (
    MAX_SUMMARY,
    MAX_TITLE,
    _parse,
    entry_link,
    entry_time,
    identifier,
    plain_text,
)

PROVIDER = "legislation_gov_uk"
HOST = "www.legislation.gov.uk"
BASE = f"https://{HOST}"
SORTS = frozenset({"published", "title", "year", "type"})
FORMATS = frozenset({"data.xml", "html"})
KNOWN = frozenset({"feed", "type", "title_terms", "sort", "max_pages_per_term", "fetch_format"})
MAX_TERMS = 20
MAX_TERM = 100
MAX_PAGES_PER_TERM = 5
_TYPE = re.compile(r"^[a-z]{2,12}$")


def check(params: dict[str, Any]) -> None:
    """The legislation.gov.uk settings a source must have when saved."""
    unknown = set(params) - KNOWN
    if unknown:
        raise ConnectorError("bad-config", f"unknown setting {sorted(unknown)[0][:50]!r}")
    if params.get("feed", "search") != "search":
        raise ConnectorError("bad-config", "feed must be search")
    kind = params.get("type", "all")
    if not isinstance(kind, str) or not _TYPE.match(kind):
        raise ConnectorError("bad-config", "type is a legislation type such as all or uksi")
    terms = params.get("title_terms")

    def short(term: Any) -> bool:
        return isinstance(term, str) and 0 < len(term.strip()) <= MAX_TERM

    if (
        not isinstance(terms, list)
        or not 1 <= len(terms) <= MAX_TERMS
        or not all(map(short, terms))
    ):
        raise ConnectorError("bad-config", f"title_terms is a list of 1 to {MAX_TERMS} short "
                             "texts")  # fmt: skip
    if params.get("sort", "published") not in SORTS:
        raise ConnectorError("bad-config", f"sort is one of {', '.join(sorted(SORTS))}")
    pages = params.get("max_pages_per_term", 2)
    if (
        not isinstance(pages, int)
        or isinstance(pages, bool)
        or not 1 <= pages <= MAX_PAGES_PER_TERM
    ):
        raise ConnectorError("bad-config", f"max_pages_per_term is 1 to {MAX_PAGES_PER_TERM}")
    if params.get("fetch_format", "data.xml") not in FORMATS:
        raise ConnectorError("bad-config", "fetch_format is data.xml or html")


def user_agent_has_contact(ctx: ConnectorContext) -> bool:
    """Whether the fetcher's user agent names a contact address (E-UK-3, BL-29)."""
    fetcher: Any = ctx.fetcher
    while fetcher is not None and not hasattr(fetcher, "user_agent"):
        fetcher = getattr(fetcher, "inner", None) or getattr(fetcher, "fetcher", None)
    agent = getattr(fetcher, "user_agent", "") if fetcher is not None else ""
    return "@" in agent


def _own(url: Any) -> str | None:
    """An https link on www.legislation.gov.uk on the default port, checked as any link."""
    link = entry_link({"link": url}, BASE)
    if link is None:
        return None
    parts = urlsplit(link)
    ok = parts.scheme == "https" and parts.port is None and parts.hostname == HOST
    return link if ok else None


def _data_xml(entry: Any) -> str | None:
    for link in entry.get("links") or []:
        href = link.get("href") if isinstance(link, dict) else None
        if isinstance(href, str) and href.split("?", 1)[0].endswith("/data.xml"):
            return _own(href)
    return None


def _next(feed: Any, path: str, asked: set[str]) -> str | None:
    for link in feed.feed.get("links") or []:
        if isinstance(link, dict) and link.get("rel") == "next":
            following = _own(link.get("href"))
            if following is None or urlsplit(following).path != path:
                raise ConnectorError("malformed-answer", "the next page is not the same feed")
            if following in asked:
                raise ConnectorError("malformed-answer", "the next page repeats an earlier one")
            return following
    return None


async def discover(params: dict[str, Any], job: JobSettings,
                   ctx: ConnectorContext) -> AsyncIterator[Candidate]:  # fmt: skip
    check(params)
    if not user_agent_has_contact(ctx):
        raise ConnectorError("needs-contact", "legislation.gov.uk refuses anonymous user "
                             "agents; set general.contact_email first")  # fmt: skip
    path = f"/{params.get('type', 'all')}/data.feed"
    pages = params.get("max_pages_per_term", 2)
    fmt = params.get("fetch_format", "data.xml")
    seen: set[str] = set()
    for term in params["title_terms"]:
        query = urlencode({"title": term.strip(), "sort": params.get("sort", "published")})
        url: str | None = f"{BASE}{path}?{query}"
        asked: set[str] = set()
        for _ in range(pages):
            if url is None:
                break
            asked.add(url)
            got = await ctx.fetcher.fetch(url, rate_per_minute=job.rate_per_minute,
                                          robots_override=job.robots_override)  # fmt: skip
            if not 200 <= got.status < 300:
                raise ConnectorError("http-status", f"the feed answered HTTP {got.status}")
            feed = await anyio.to_thread.run_sync(
                _parse, got.body, got.url, got.headers.get("content-type", ""))  # fmt: skip
            if not feed.version:
                raise ConnectorError("malformed-feed", "the answer is not an Atom feed")
            for entry in feed.entries:
                link = _own(entry.get("link"))
                ident = identifier(entry.get("id"))
                if link is None or link in seen or (ident and ident in seen):
                    continue
                seen.update(x for x in (link, ident) if x)
                xml = _data_xml(entry)
                target = xml if fmt == "data.xml" and xml else link
                yield Candidate(url=link, title=plain_text(entry.get("title"), MAX_TITLE),
                                published_at=entry_time(entry), external_id=ident,
                                summary=plain_text(entry.get("summary"), MAX_SUMMARY),
                                language="en",
                                hints={"provider": PROVIDER, "fetch": target})  # fmt: skip
            url = _next(feed, path, asked)
        if url is not None:
            ctx.notes.add("truncated")  # this term had pages past max_pages_per_term


async def fetch(candidate: Candidate, job: JobSettings, ctx: ConnectorContext) -> RawDocument:
    target = _own(candidate.hints.get("fetch")) or candidate.url
    got = await ctx.fetcher.fetch(target, rate_per_minute=job.rate_per_minute,
                                  robots_override=job.robots_override)  # fmt: skip
    if not 200 <= got.status < 300:
        raise ConnectorError("http-status", f"the page answered HTTP {got.status}")
    key = f"raw/{job.source_id}/{hashlib.sha256(got.body).hexdigest()}"
    await ctx.store(key, got.body)
    return RawDocument(url=candidate.url, fetched_at=ctx.now(), status=got.status, body_ref=key,
                       mime=got.mime or "application/octet-stream", final_url=got.url,
                       text=candidate.summary,
                       metadata={"provider": PROVIDER, "fetched": target})  # fmt: skip
