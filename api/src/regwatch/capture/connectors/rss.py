"""The RSS and Atom connector (M3 scope; connectors.yaml ``rss``).

``discover`` fetches the feed through ``ctx.fetcher`` and parses the bytes with feedparser;
``fetch`` fetches each entry's page, or keeps the entry's own text when ``fetch_full_page`` is
off. Feeds are hostile (8.1), so:

- feedparser only ever gets an in-memory stream. Given a string it fetches it as a URL, and
  given a string or bytes it first tries to ``open()`` them as a local path, which read local
  files and let ``/dev/zero`` exhaust memory (RSS review finding 1).
- Before feedparser sees it, ``precheck`` parses the body once with expat and refuses any
  DOCTYPE, any entity declaration (also found by a plain search, as a backstop), bodies over
  ``MAX_FEED_BYTES``, nesting past ``MAX_DEPTH``, more than
  ``MAX_ELEMENTS`` elements, and anything that is not well-formed XML. feedparser keeps simple
  entity declarations and, when expat stops at its amplification limit, re-parses with its
  loose parser and expands them without limit (gigabytes from a 100 KB feed, finding 2); its
  loose parser is also slow on tag soup (finding 3). Refused feeds never reach it. Parsing
  runs off the event loop, and the worker's time and memory limits are the last stop.
- Entry links pass SafeFetcher's ``parse_target`` (http or https, no user name or password,
  IDNA host, length and character checks), contain no backslash, and are rebuilt from the
  parsed parts, so what is stored is what was checked; an IP literal must also pass
  ``check_address`` (finding 5). SafeFetcher still checks every address when a page is fetched.
- Titles and summaries become plain text: every tag is removed (nh3 with no tags allowed) and
  entities decoded, repeated until nothing changes, so ``&amp;lt;script&amp;gt;`` cannot
  come back as ``<script>`` (finding 4); controls and runs of white space are collapsed, and
  lengths are capped before and after cleaning. The text is still untrusted: show it escaped.
"""

from __future__ import annotations

import calendar
import hashlib
import html
import io
import re
import unicodedata
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin
from xml.parsers import expat

import anyio
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
from regwatch.capture.safe_fetch.policy import (
    FetchRefusedError,
    check_address,
    is_ip,
    parse_target,
)

MAX_TITLE = 1000
MAX_SUMMARY = 5000
MAX_ID = 500
MAX_URL = 2048
MAX_FEED_BYTES = 5 * 1024 * 1024  # no real feed is larger; halves feedparser's worst case (12)
MAX_DEPTH = 64
MAX_ELEMENTS = 200_000
CLEAN_ROUNDS = 5
# Hosts written as numbers (2130706433, 0x7f.1, 017700000001): IP addresses in disguise, which
# getaddrinfo accepts and ipaddress does not; no real feed links to one.
_NUMERIC_HOST = re.compile(r"^(0x[0-9a-f]*|[0-9]+)(\.(0x[0-9a-f]*|[0-9]+)){0,3}\.?$", re.I)
# Names that are never public (RFC 6761, RFC 6762, RFC 8375, ICANN's .internal). SafeFetcher
# refuses them at fetch time once they resolve; a stored link should not name one either.
_LOCAL_SUFFIXES = ("localhost", "local", "internal", "home.arpa", "lan", "intranet", "corp")


def _local_name(host: str) -> bool:
    name = host.rstrip(".").lower()
    return "." not in name or any(name == s or name.endswith("." + s) for s in _LOCAL_SUFFIXES)


_LANGUAGE = re.compile(r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8}){0,4}$")


_ENTITY = re.compile(rb"<!\s*entity", re.I)


def _maybe_utf16(body: bytes) -> bool:
    return body[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in body[:200]


def _as_utf8(body: bytes) -> bytes:
    for encoding in ("utf-16", "utf-16-le", "utf-16-be"):
        try:
            return body.decode(encoding).encode("utf-8")
        except UnicodeDecodeError:
            continue
    return b""


class _RefusedError(Exception):
    pass


def precheck(body: bytes) -> None:
    """Refuse what feedparser must never see: DTD subsets, entity declarations, deep or huge
    trees, and anything that is not well-formed XML (findings 2 and 3)."""
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    state = {"depth": 0, "count": 0}

    def start(name: str, attrs: dict[str, str]) -> None:
        state["depth"] += 1
        state["count"] += 1
        if state["depth"] > MAX_DEPTH or state["count"] > MAX_ELEMENTS:
            raise _RefusedError("the feed is nested too deeply or has too many elements")

    def end(name: str) -> None:
        state["depth"] -= 1

    def doctype(name: str, sysid: str | None, pubid: str | None, internal: int) -> None:
        # Any DOCTYPE, not only one with a subset: with an external DTD named, expat skips
        # undefined entities, and feedparser's own regexes can rebuild a subset from text in
        # a comment (re-verification 1, finding 2b). RSS 0.91's Netscape DOCTYPE goes too.
        raise _RefusedError("the feed has a DOCTYPE")

    def entity(*args: object) -> None:  # pragma: no cover - only inside a subset, refused first
        raise _RefusedError("the feed declares entities")

    if len(body) > MAX_FEED_BYTES:
        raise ConnectorError("too-large", f"the feed is larger than {MAX_FEED_BYTES} bytes")
    if _ENTITY.search(body) or (_maybe_utf16(body) and _ENTITY.search(_as_utf8(body))):
        raise ConnectorError("unsafe-feed", "the feed declares entities")  # backstop, 2b
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.StartDoctypeDeclHandler = doctype
    parser.EntityDeclHandler = entity
    try:
        parser.Parse(body, True)
    except _RefusedError as exc:
        raise ConnectorError("unsafe-feed", str(exc)) from None
    except (expat.ExpatError, ValueError):
        raise ConnectorError("malformed-feed", "the feed is not well-formed XML") from None


def plain_text(value: Any, limit: int) -> str | None:
    """Markup from a feed as one line of plain text, or None when nothing is left."""
    if not isinstance(value, str) or not value:
        return None
    text = value[: limit * 4]  # cut first: cleaning cost grows with the input (finding 2)
    for _ in range(CLEAN_ROUNDS):
        cleaned = html.unescape(nh3.clean(text, tags=set()))
        if cleaned == text:
            break
        text = cleaned
    else:
        return None  # still changing: markup hidden under layers of encoding (finding 4)
    text = "".join(c if c.isprintable() else " " for c in text)
    return " ".join(text.split())[:limit] or None


def identifier(value: Any) -> str | None:
    """An entry id as given, controls removed; a long one is kept as its hash, so two long ids
    with the same start never collide (finding 7)."""
    if not isinstance(value, str):
        return None
    text = " ".join("".join(c if c.isprintable() else " " for c in value).split())
    if not text:
        return None
    return text if len(text) <= MAX_ID else "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def language_tag(value: Any) -> str | None:
    text = plain_text(value, 35)
    return text if text is not None and _LANGUAGE.fullmatch(text) else None


def entry_link(entry: Any, base: str) -> str | None:
    """The entry's link, resolved against the feed URL and rebuilt from SafeFetcher's parsed
    parts, or None when SafeFetcher would refuse it (finding 5)."""
    link = entry.get("link")
    if not isinstance(link, str) or not link.strip() or "\\" in link:
        return None
    if any(unicodedata.category(c) in ("Cf", "Cc", "Zl", "Zp") for c in link):
        return None  # bidi overrides and other invisible controls (re-verification 11)
    try:
        target = parse_target(urljoin(base, link.strip()))
        if is_ip(target.host):
            check_address(target.host)
        elif _NUMERIC_HOST.match(target.host) or "%" in target.host or _local_name(target.host):
            return None
    except (FetchRefusedError, ValueError):
        return None
    url = target.origin + target.path
    return url if len(url) <= MAX_URL else None


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
    """Check, then parse from a stream: feedparser opens strings and bytes as paths first."""
    if not isinstance(body, bytes):
        raise TypeError("feeds are parsed from bytes only")
    precheck(body)
    # The media type only: with the HTTP charset, feedparser decodes the body differently from
    # the expat pre-pass (a UTF-7 body looks like plain ASCII to expat), so the checked text
    # would not be the parsed text (re-verification 1, finding 2a). Both now go by the XML
    # declaration or byte-order mark.
    media = content_type.split(";", 1)[0].strip()
    try:
        return feedparser.parse(io.BytesIO(body), response_headers={
            "content-location": url, "content-type": media})  # fmt: skip
    except Exception:  # noqa: BLE001 - any parser failure; its text may quote the feed (6)
        raise ConnectorError("malformed-feed", "the feed could not be parsed") from None


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
        feed = await anyio.to_thread.run_sync(
            _parse, got.body, got.url, got.headers.get("content-type", ""))  # fmt: skip
        if not feed.version:  # well-formed, but not RSS or Atom: XHTML, an error document
            raise ConnectorError("malformed-feed", "the answer is not an RSS or Atom feed")
        language = language_tag(feed.feed.get("language"))
        seen: set[str] = set()
        entries = feed.entries[: max(0, min(config.max_entries, job.max_items))]  # finding 8
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
                external_id=identifier(entry.get("id")),
                summary=summary,
                language=language_tag(entry.get("language")) or language,
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
        if not 200 <= got.status < 300:  # an error page is not the document (review info)
            raise ConnectorError("http-status", f"the page answered HTTP {got.status}")
        key = f"raw/{job.source_id}/{hashlib.sha256(got.body).hexdigest()}"
        await ctx.store(key, got.body)
        return RawDocument(url=candidate.url, fetched_at=now, status=got.status, body_ref=key,
                           mime=got.mime or "application/octet-stream", final_url=got.url,
                           headers={k: v for k, v in got.headers.items()
                                    if k in ("content-type", "last-modified", "etag")})  # fmt: skip

    def health(self, job: JobSettings) -> HealthReport:
        return HealthReport("unknown", "health comes from the job's runs")


register(RssConnector())
