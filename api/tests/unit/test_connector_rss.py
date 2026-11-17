"""The RSS and Atom connector, with hostile feeds (M3 acceptance 1 mapping; test plan: script
in extracted content, malformed feeds; 8.1)."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from regwatch.capture.connectors.base import (
    REGISTRY,
    Candidate,
    ConnectorContext,
    ConnectorError,
    JobSettings,
)
from regwatch.capture.connectors.config import ExtractionRules, RssConfig
from regwatch.capture.connectors.rss import RssConnector, _parse, entry_link, plain_text
from regwatch.capture.safe_fetch import CaptureFetcher, MemoryRateLimiter, SafeFetcher
from tests.unit.test_safe_fetch_fetch import UA, dns

FEED_URL = "https://example.org/feeds/news.xml"

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>News</title><language>en-GB</language>
<item><title>First &amp; <b>bold</b></title><link>https://example.org/a</link>
  <guid isPermaLink="false">id-a</guid><pubDate>Mon, 16 Nov 2026 09:30:00 GMT</pubDate>
  <description>&lt;p&gt;Hello &lt;script&gt;alert(1)&lt;/script&gt;world&lt;/p&gt;
  </description></item>
<item><title>Relative</title><link>/b?x=1</link></item>
<item><title>Script link</title><link>javascript:alert(1)</link></item>
<item><title>Data link</title><link>data:text/html,hi</link></item>
<item><title>File link</title><link>file:///etc/passwd</link></item>
<item><title>Duplicate</title><link>https://example.org/a</link></item>
<item><title>No link</title></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="de"><title>Atom</title>
<entry><title type="html">&lt;i&gt;Regel&lt;/i&gt;</title><id>urn:x:1</id>
  <link href="https://example.org/regel"/><updated>2026-11-15T08:00:00Z</updated>
  <summary>Kurz</summary></entry></feed>"""


class Site:
    """The fake site: robots.txt allows all; the feed and pages answer as set."""

    def __init__(self, feed: bytes, status: int = 200) -> None:
        self.feed, self.status = feed, status
        self.paths: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404, stream=httpx.ByteStream(b""))
        if request.url.path == "/feeds/news.xml":
            return httpx.Response(self.status, headers={"content-type": "application/rss+xml"},
                                  stream=httpx.ByteStream(self.feed))  # fmt: skip
        return httpx.Response(200, headers={"content-type": "text/html"},
                              stream=httpx.ByteStream(b"<html>page</html>"))  # fmt: skip


def context(site: Site) -> tuple[ConnectorContext, dict[str, bytes]]:
    fetcher = SafeFetcher(UA, resolver=dns, transport=httpx.MockTransport(site))

    async def no_wait(seconds: float) -> None:
        return None

    stored: dict[str, bytes] = {}

    async def store(key: str, body: bytes) -> None:
        stored[key] = body

    capture = CaptureFetcher(fetcher, MemoryRateLimiter(), rate_per_minute=6000, sleep=no_wait)
    now = datetime(2026, 11, 17, tzinfo=UTC)
    return ConnectorContext(fetcher=capture, store=store, now=lambda: now), stored


def job(**config: Any) -> JobSettings:
    return JobSettings(source_id="s1", kind="rss",
                       config=RssConfig(feed_url=FEED_URL, **config),  # type: ignore[arg-type]
                       rules=ExtractionRules(), max_items=200, rate_per_minute=6000)  # fmt: skip


async def discover(site: Site, **config: Any) -> list[Candidate]:
    ctx, _ = context(site)
    return [c async for c in RssConnector().discover(job(**config), ctx)]


async def test_entries_become_candidates_with_plain_text() -> None:
    got = await discover(Site(RSS))
    assert [c.url for c in got] == ["https://example.org/a", "https://example.org/b?x=1"]
    first = got[0]
    assert first.title == "First & bold"
    assert first.summary == "Hello world"  # the script and every tag are gone
    assert first.external_id == "id-a" and first.language == "en-GB"
    assert first.published_at == datetime(2026, 11, 16, 9, 30, tzinfo=UTC)
    assert REGISTRY["rss"].kind == "rss"


async def test_atom_feeds_and_their_html_titles() -> None:
    got = await discover(Site(ATOM))
    assert len(got) == 1
    assert got[0].title == "Regel" and got[0].language == "de" and got[0].summary == "Kurz"
    assert got[0].published_at == datetime(2026, 11, 15, 8, tzinfo=UTC)


async def test_limits_apply() -> None:
    items = b"".join(b"<item><title>t</title><link>https://example.org/%d</link></item>" % n
                     for n in range(30))  # fmt: skip
    feed = b'<?xml version="1.0"?><rss version="2.0"><channel>' + items + b"</channel></rss>"
    assert len(await discover(Site(feed), max_entries=5)) == 5


async def test_external_entities_are_not_loaded() -> None:
    """XXE: an entity naming a local file or a URL is never read or fetched."""
    feed = b"""<?xml version="1.0"?>
<!DOCTYPE rss [<!ENTITY file SYSTEM "file:///etc/passwd">
               <!ENTITY web SYSTEM "http://10.0.0.5/secret">]>
<rss version="2.0"><channel><item><title>&file;&web;x</title>
<link>https://example.org/x</link></item></channel></rss>"""
    site = Site(feed)
    got = await discover(site)
    assert all("root:" not in (c.title or "") for c in got)
    assert site.paths == ["/robots.txt", "/feeds/news.xml"]  # nothing else was requested


async def test_entity_expansion_bombs_end_quickly() -> None:
    lol = b'<!ENTITY a0 "lol">' + b"".join(
        b'<!ENTITY a%d "%s">' % (n, (b"&a%d;" % (n - 1)) * 10) for n in range(1, 10))  # fmt: skip
    feed = (b'<?xml version="1.0"?><!DOCTYPE rss [' + lol + b']><rss version="2.0"><channel>'
            b"<item><title>&a9;</title><link>https://example.org/x</link></item>"
            b"</channel></rss>")  # fmt: skip
    started = time.monotonic()
    try:
        got = await discover(Site(feed))
    except ConnectorError:
        got = []
    assert time.monotonic() - started < 5
    assert all(len(c.title or "") <= 1000 for c in got)


@pytest.mark.parametrize("body", [b"not a feed at all", b"<html><body>hi</body></html>",
                                  b"<?xml version='1.0'?><rss><channel><item>"])  # fmt: skip
async def test_malformed_feeds_are_refused(body: bytes) -> None:
    with pytest.raises(ConnectorError) as exc:
        await discover(Site(body))
    assert exc.value.reason == "malformed-feed"


async def test_an_empty_feed_has_no_candidates() -> None:
    feed = b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
    assert await discover(Site(feed)) == []


async def test_http_errors_are_refused() -> None:
    with pytest.raises(ConnectorError) as exc:
        await discover(Site(RSS, status=500))
    assert exc.value.reason == "http-status"


async def test_fetch_stores_the_page_or_the_entry_text() -> None:
    site = Site(RSS)
    ctx, stored = context(site)
    candidate = Candidate(url="https://example.org/a", summary="Hello world")
    page = await RssConnector().fetch(candidate, job(), ctx)
    assert page.status == 200 and page.mime == "text/html"
    assert stored[page.body_ref] == b"<html>page</html>"
    assert page.body_ref.startswith("raw/s1/")
    text = await RssConnector().fetch(candidate, job(fetch_full_page=False), ctx)
    assert text.mime == "text/plain" and text.text == "Hello world"
    assert stored[text.body_ref] == b"Hello world"
    assert RssConnector().health(job()).status == "unknown"


def test_feedparser_never_gets_a_string() -> None:
    """A string would be fetched as a URL or opened as a file by feedparser."""
    with pytest.raises(TypeError):
        _parse("file:///etc/passwd", FEED_URL, "")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("link", "expected"),
    [("https://example.org/a", "https://example.org/a"), ("/b", "https://example.org/b"),
     ("javascript:alert(1)", None), ("  ", None), ("https://[bad", None),
     ("https://example.org/" + "a" * 3000, None), ("https://example.org/a b", None),
     ("mailto:x@example.org", None), ("ftp://example.org/x", None)],
)  # fmt: skip
def test_entry_links(link: str, expected: str | None) -> None:
    assert entry_link({"link": link}, FEED_URL) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("", None), ("<b>a</b>\u202e\x00 b", "a b"), ("&amp;lt;", "&lt;"),
     ("<script>x</script>", None), (5, None)],
)  # fmt: skip
def test_plain_text(value: Any, expected: str | None) -> None:
    assert plain_text(value, 100) == expected


def test_entry_times_out_of_range_are_dropped() -> None:
    from regwatch.capture.connectors.rss import entry_time

    assert entry_time({"published_parsed": (99999, 1, 1, 0, 0, 0, 0, 1, 0)}) is None
    assert entry_time({}) is None


async def test_a_job_for_another_kind_is_refused() -> None:
    from regwatch.capture.connectors.config import ManualConfig

    ctx, _ = context(Site(RSS))
    other = JobSettings(source_id="s1", kind="manual", config=ManualConfig(),
                        rules=ExtractionRules())  # fmt: skip
    with pytest.raises(TypeError):
        [c async for c in RssConnector().discover(other, ctx)]
