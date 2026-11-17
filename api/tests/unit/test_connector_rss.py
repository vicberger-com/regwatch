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


@pytest.fixture
def no_files_or_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parsing may not open a file or a socket: either would bypass SafeFetcher (finding 9)."""
    import builtins
    import socket

    real_open = builtins.open

    def guarded_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(file, (str, bytes)) and not str(file).endswith((".py", ".pyc")):
            raise AssertionError(f"the parser opened {file!r}")
        return real_open(file, *args, **kwargs)

    def no_connect(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the parser opened a socket")

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(socket.socket, "connect", no_connect)


@pytest.mark.parametrize(
    "doctype",
    [b'<!DOCTYPE rss [<!ENTITY file SYSTEM "file:///etc/passwd">]>',
     b'<!DOCTYPE rss [<!ENTITY web SYSTEM "http://10.0.0.5/secret">]>',
     b'<!DOCTYPE rss [<!ENTITY a "x">]>', b'<!DOCTYPE rss [<!ELEMENT rss ANY>]>',
     b'<!DOCTYPE rss [<!ENTITY % p SYSTEM "http://10.0.0.5/x.dtd"> %p;]>'],
)  # fmt: skip
async def test_dtds_and_entities_are_refused(doctype: bytes, no_files_or_sockets: None) -> None:
    """XXE and entity bombs (findings 2 and 9): any DTD of the feed's own is refused before
    feedparser sees it, so nothing is read, fetched or expanded."""
    body = b"<title>x</title><link>https://example.org/x</link>"
    feed = (b'<?xml version="1.0"?>' + doctype + b'<rss version="2.0"><channel><item>'
            + body + b"</item></channel></rss>")  # fmt: skip
    with pytest.raises(ConnectorError) as exc:
        await discover(Site(feed))
    assert exc.value.reason == "unsafe-feed"


async def test_entity_bombs_are_refused_at_once() -> None:
    lol = b'<!ENTITY a0 "lol">' + b"".join(
        b'<!ENTITY a%d "%s">' % (n, (b"&a%d;" % (n - 1)) * 10) for n in range(1, 10))  # fmt: skip
    feed = (b'<?xml version="1.0"?><!DOCTYPE rss [' + lol + b']><rss version="2.0"><channel>'
            + b"<item><title>&a9;</title><link>https://example.org/x</link></item>" * 2000
            + b"</channel></rss>")  # fmt: skip
    started = time.monotonic()
    with pytest.raises(ConnectorError):
        await discover(Site(feed))
    assert time.monotonic() - started < 1


@pytest.mark.parametrize(
    "body",
    [b"<rss>" + b"<a>" * 100 + b"</a>" * 100 + b"</rss>",  # deeper than MAX_DEPTH
     b"<rss><channel>" + b"<i/>" * 200_001 + b"</channel></rss>"],  # more than MAX_ELEMENTS
)  # fmt: skip
async def test_deep_or_huge_trees_are_refused(body: bytes) -> None:
    with pytest.raises(ConnectorError) as exc:
        await discover(Site(body))
    assert exc.value.reason == "unsafe-feed"


async def test_tag_soup_is_refused_quickly() -> None:
    """Finding 3: 9 MB of tag soup took 77 s in feedparser's loose parser; refused at once."""
    soup = b"<rss><channel>" + b"<item><title>x<b>y</i></item>" * 300_000
    started = time.monotonic()
    with pytest.raises(ConnectorError) as exc:
        await discover(Site(soup))
    assert exc.value.reason == "malformed-feed"
    assert time.monotonic() - started < 3


def test_feedparser_reads_a_stream_never_a_path(no_files_or_sockets: None) -> None:
    """Finding 1: feedparser opens strings and bytes as paths, so it only gets a stream."""
    with pytest.raises(TypeError):
        _parse("file:///etc/passwd", FEED_URL, "")  # type: ignore[arg-type]
    for path in (b"/dev/zero", b"/etc/passwd"):  # bodies that name local files
        with pytest.raises(ConnectorError):
            _parse(path, FEED_URL, "")
    assert _parse(RSS, FEED_URL, "application/rss+xml").entries


def test_parser_errors_never_escape_with_feed_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Finding 6: a content type that makes feedparser raise becomes a clean error."""
    from regwatch.capture.connectors import rss

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise UnicodeError("secret page text")

    monkeypatch.setattr(rss.feedparser, "parse", boom)
    with pytest.raises(ConnectorError) as exc:
        _parse(RSS, FEED_URL, "application/rss+xml; charset=punycode")
    assert "secret" not in exc.value.detail


@pytest.mark.parametrize("body", [b"not a feed at all", b"<html><body>hi</body></html>",
                                  b"<?xml version='1.0'?><rss><channel><item>",
                                  b"<rss version='2.0'>&nbsp;</rss>"])  # fmt: skip
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


@pytest.mark.parametrize(
    ("link", "expected"),
    [("https://example.org/a", "https://example.org/a"), ("/b", "https://example.org/b"),
     ("javascript:alert(1)", None), ("  ", None), ("https://[bad", None),
     ("https://example.org/" + "a" * 3000, None), ("https://example.org/a b", None),
     ("mailto:x@example.org", None), ("ftp://example.org/x", None),
     ("https://user:pw@example.org/x", None), ("https://evil.example\\@example.org/", None),
     ("http://10.0.0.5/admin", None), ("http://[::1]/", None), ("http://2130706433/", None),
     ("http://0x7f.1/", None), ("http://017700000001/", None), ("http://1.2.3.4.example/", "http://1.2.3.4.example/"),
     ("https://BÜCHER.example/a#frag", "https://xn--bcher-kva.example/a"),
     ("https://example.org:443/a?q=1", "https://example.org/a?q=1")],
)  # fmt: skip
def test_entry_links(link: str, expected: str | None) -> None:
    assert entry_link({"link": link}, FEED_URL) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("", None), ("<b>a</b>\u202e\x00 b", "a b"), ("&amp;lt;", "<"),
     ("<script>x</script>", None), (5, None),
     ("&amp;lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;", None),
     ("&amp;lt;img src=x onerror=alert(1)&amp;gt;ok", "ok"),
     ("&amp;amp;amp;amp;amp;amp;lt;b&amp;amp;amp;amp;amp;amp;gt;", None)],
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


@pytest.mark.parametrize(
    ("value", "expected"),
    [("en-GB", "en-GB"), ('x" onmouseover="alert(1)', None), ("e" * 40, None), (None, None)],
)  # fmt: skip
def test_language_tags(value: Any, expected: str | None) -> None:
    from regwatch.capture.connectors.rss import language_tag

    assert language_tag(value) == expected


def test_long_ids_keep_their_identity() -> None:
    from regwatch.capture.connectors.rss import identifier

    a, b = "x" * 600 + "a", "x" * 600 + "b"
    assert identifier(a) != identifier(b) and identifier(a).startswith("sha256:")  # type: ignore[union-attr]
    assert (
        identifier("  id\x00 1 ") == "id 1" and identifier(None) is None and identifier("") is None
    )


async def test_a_negative_limit_gives_no_entries() -> None:
    assert await discover(Site(RSS), max_entries=-1) == []


async def test_error_pages_are_not_stored() -> None:
    class Broken(Site):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/a":
                return httpx.Response(404, stream=httpx.ByteStream(b"gone"))
            return super().__call__(request)

    ctx, stored = context(Broken(RSS))
    with pytest.raises(ConnectorError) as exc:
        await RssConnector().fetch(Candidate(url="https://example.org/a"), job(), ctx)
    assert exc.value.reason == "http-status" and stored == {}


async def test_an_external_dtd_is_named_but_never_fetched(no_files_or_sockets: None) -> None:
    feed = (b'<?xml version="1.0"?><!DOCTYPE rss SYSTEM "http://10.0.0.5/rss.dtd">'
            b'<rss version="2.0"><channel><item><title>x</title>'
            b"<link>https://example.org/x</link></item></channel></rss>")  # fmt: skip
    site = Site(feed)
    assert [c.url for c in await discover(site)] == ["https://example.org/x"]
    assert site.paths == ["/robots.txt", "/feeds/news.xml"]


async def test_a_broken_feed_without_usable_links_is_refused() -> None:
    """feedparser flags a feed served as text/plain (bozo); with no usable link it is refused."""
    feed = b'<rss version="2.0"><channel><item><title>x</title></item></channel></rss>'

    class Plain(Site):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/feeds/news.xml":
                return httpx.Response(200, headers={"content-type": "text/plain"},
                                      stream=httpx.ByteStream(self.feed))  # fmt: skip
            return super().__call__(request)

    with pytest.raises(ConnectorError) as exc:
        await discover(Plain(feed))
    assert exc.value.reason == "malformed-feed"
