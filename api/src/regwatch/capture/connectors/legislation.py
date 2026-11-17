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
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

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
from regwatch.capture.safe_fetch.policy import FetchRefusedError

PROVIDER = "legislation_gov_uk"
HOST = "www.legislation.gov.uk"
BASE = f"https://{HOST}"
SORTS = frozenset({"published", "title", "year", "type"})
FORMATS = frozenset({"data.xml", "html"})
DISALLOWED_NAMES = frozenset({"data.pdf", "data.docx"})  # robots.txt E-UK-1, enforced here too
NEXT_KEYS = frozenset({"title", "sort", "page"})
# robots.txt asks for Crawl-delay 5 (12 a minute); held here even if robots.txt cannot be read
# or is overridden, which the fair use policy does not allow (E-UK-3; review finding 1).
MAX_RATE_PER_MINUTE = 12
KNOWN = frozenset({"feed", "type", "title_terms", "sort", "max_pages_per_term", "fetch_format"})
MAX_TERMS = 20
MAX_TERM = 100
MAX_PAGES_PER_TERM = 5
_TYPE = re.compile(r"[a-z]{2,12}")  # used with fullmatch: "uksi\n" is refused (finding 6)
_CONTACT = re.compile(r"\(\+[^\s()@]+@[^\s()@]+\.[^\s()@]+\)")  # "(+name@host.tld)"


def check(params: dict[str, Any]) -> None:
    """The legislation.gov.uk settings a source must have when saved."""
    unknown = set(params) - KNOWN
    if unknown:
        raise ConnectorError("bad-config", f"unknown setting {sorted(unknown)[0][:50]!r}")
    if params.get("feed", "search") != "search":
        raise ConnectorError("bad-config", "feed must be search")
    kind = params.get("type", "all")
    if not isinstance(kind, str) or not _TYPE.fullmatch(kind):
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
    if len({t.strip().lower() for t in terms}) != len(terms):
        raise ConnectorError("bad-config", "title_terms has the same term twice")
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
    return bool(_CONTACT.search(agent))  # a whole "(+name@host.tld)", not any "@" (finding 5)


def _disallowed(path: str) -> bool:
    """``data.pdf`` or ``data.docx`` anywhere in the decoded path, with any parameters or a
    trailing slash: ``/data.pdf/``, ``/data.pdf;x`` and ``/data%2Epdf`` too (re-verification R1)."""
    segments = unquote(path).lower().split("/")
    return any(segment.split(";", 1)[0] in DISALLOWED_NAMES for segment in segments)


def _strict(url: str) -> bool:
    """A hop or final URL: https on www.legislation.gov.uk, default port, not disallowed. No
    rewriting here: a redirect to http is refused, not upgraded (re-verification R1)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return (parts.scheme == "https" and parts.hostname == HOST and parts.port is None
            and not _disallowed(parts.path))  # fmt: skip


def _own(url: Any) -> str | None:
    """A link on www.legislation.gov.uk on the default port, checked as any link, always as
    https: the feed's own links may be http (its entry ids are), so an http link on the host is
    rewritten rather than dropped (review finding 2). Paths robots.txt disallows are refused
    here too, so no override or missing robots.txt can fetch them (finding 1)."""
    link = entry_link({"link": url}, BASE)
    if link is None:
        return None
    parts = urlsplit(link)
    if parts.hostname != HOST or parts.port is not None or parts.scheme not in ("http", "https"):
        return None
    if _disallowed(parts.path):  # checked after cleaning, fragment gone
        return None
    return "https://" + link.split("://", 1)[1] if parts.scheme == "http" else link


def _data_xml(entry: Any) -> str | None:
    for link in entry.get("links") or []:
        href = link.get("href") if isinstance(link, dict) else None
        if isinstance(href, str) and href.split("?", 1)[0].endswith("/data.xml"):
            return _own(href)
    return None


def _same_search(url: str, term: str, sort: str) -> bool:
    """The next page keeps the search: one title, the same sort, and no other keys than page
    (re-verification R2)."""
    pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    keys = [k for k, _ in pairs]
    if set(keys) - NEXT_KEYS or keys.count("title") != 1 or keys.count("sort") > 1:
        return False
    values = dict(pairs)
    return values.get("title") == term and values.get("sort", sort) == sort


def _next(feed: Any, path: str, asked: set[str], term: str, sort: str) -> str | None:
    for link in feed.feed.get("links") or []:
        if isinstance(link, dict) and link.get("rel") == "next":
            following = _own(link.get("href"))
            if following is None or urlsplit(following).path != path:
                raise ConnectorError("malformed-answer", "the next page is not the same feed")
            if not _same_search(following, term, sort):
                raise ConnectorError("malformed-answer", "the next page is another search")
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
            got = await _get(ctx, url, job)
            if not 200 <= got.status < 300:
                raise ConnectorError("http-status", f"the feed answered HTTP {got.status}")
            feed = await anyio.to_thread.run_sync(
                _parse, got.body, got.url, got.headers.get("content-type", ""))  # fmt: skip
            if not feed.version:
                raise ConnectorError("malformed-feed", "the answer is not an Atom feed")
            usable = 0
            for entry in feed.entries:
                link = _own(entry.get("link"))
                if link is not None:
                    usable += 1
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
            if feed.entries and not usable:  # every entry dropped: never a silent success (2)
                raise ConnectorError("malformed-answer", "no entry on the page had a usable link")
            url = _next(feed, path, asked, term.strip(), params.get("sort", "published"))
        if url is not None:
            ctx.notes.add("truncated")  # this term had pages past max_pages_per_term


async def _get(ctx: ConnectorContext, url: str, job: JobSettings) -> Any:
    """A request to the provider: at most 12 a minute and robots.txt always obeyed, whatever the
    job says (finding 1), and the answer must come from www.legislation.gov.uk after any
    redirect, so another host's body is never stored as legislation (finding 3)."""
    try:
        got = await ctx.fetcher.fetch(url, rate_per_minute=min(job.rate_per_minute,
                                                               MAX_RATE_PER_MINUTE),
                                      robots_override=None, allow_hop=_strict)  # fmt: skip
    except FetchRefusedError as exc:
        if exc.reason == "refused-host":  # a hop off the host, to http, or to a disallowed path
            raise ConnectorError("off-host", "a redirect left the allowed addresses") from None
        raise
    if not _strict(got.url):  # pragma: no cover - every hop, the last included, was checked
        raise ConnectorError("off-host", "the answer came from another address")
    return got


async def fetch(candidate: Candidate, job: JobSettings, ctx: ConnectorContext) -> RawDocument:
    target = _own(candidate.hints.get("fetch")) or _own(candidate.url)
    if target is None:
        raise ConnectorError("bad-link", "the document is not on www.legislation.gov.uk")
    got = await _get(ctx, target, job)
    if not 200 <= got.status < 300:
        raise ConnectorError("http-status", f"the page answered HTTP {got.status}")
    key = f"raw/{job.source_id}/{hashlib.sha256(got.body).hexdigest()}"
    await ctx.store(key, got.body)
    return RawDocument(url=candidate.url, fetched_at=ctx.now(), status=got.status, body_ref=key,
                       mime=got.mime or "application/octet-stream", final_url=got.url,
                       # The body is the act; the feed's summary is metadata, not its text (9).
                       metadata={"provider": PROVIDER, "fetched": target,
                                 "summary": candidate.summary})  # fmt: skip
