"""The legislation.gov.uk adapter (R-06 section 3; connectors/legislation.py)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest

from regwatch.capture.connectors import legislation
from regwatch.capture.connectors.api_feed import ApiFeedConnector, check_params
from regwatch.capture.connectors.base import (
    Candidate,
    ConnectorContext,
    ConnectorError,
    JobSettings,
)
from regwatch.capture.connectors.config import ApiFeedConfig, ExtractionRules
from regwatch.capture.safe_fetch import CaptureFetcher, MemoryRateLimiter, SafeFetcher

NOW = datetime(2026, 11, 17, tzinfo=UTC)
LEG = "https://www.legislation.gov.uk"


def entry(n: int, **extra: str) -> str:
    link = extra.get("link", f"{LEG}/uksi/2026/{n}/made")
    xml = extra.get("xml", f"{LEG}/uksi/2026/{n}/made/data.xml")
    return (f"<entry><id>http://www.legislation.gov.uk/id/uksi/2026/{n}</id>"
            f"<title>The Cyber &lt;b&gt;Regulations&lt;/b&gt; {n}</title>"
            f'<link rel="alternate" href="{link}"/>'
            f'<link rel="alternate" type="application/xml" href="{xml}"/>'
            f"<published>2026-11-{n:02d}T00:00:00Z</published>"
            f"<summary>Summary {n}</summary></entry>")  # fmt: skip


def feed(entries: list[str], following: str | None = None) -> bytes:
    # An attribute value in XML: & must be &amp; (a bare one is not well-formed, and refused).
    nxt = f'<link rel="next" href="{following.replace("&", "&amp;")}"/>' if following else ""
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom"><title>Search</title>'
            f"{nxt}{''.join(entries)}</feed>").encode()  # fmt: skip


class Site:
    """A fake www.legislation.gov.uk: robots.txt with Crawl-delay, feeds per term and page."""

    def __init__(self, pages: dict[tuple[str, str], bytes]) -> None:
        self.pages = pages
        self.paths: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(f"{request.url.path}?{request.url.query.decode()}")
        if request.url.path == "/robots.txt":
            body = b"User-agent: *\nCrawl-delay: 5\nDisallow: */data.pdf\n"
            return httpx.Response(200, stream=httpx.ByteStream(body))
        if request.url.path.endswith("/data.xml"):
            return httpx.Response(200, headers={"content-type": "application/xml"},
                                  stream=httpx.ByteStream(b"<Legislation/>"))  # fmt: skip
        q = dict(parse_qsl(request.url.query.decode()))
        body = self.pages.get((q.get("title", ""), q.get("page", "1")), feed([]))
        return httpx.Response(200, headers={"content-type": "application/atom+xml"},
                              stream=httpx.ByteStream(body))  # fmt: skip


def context(site: Site, agent: str = "regwatch-test (+ops@example.org)",
            ) -> tuple[ConnectorContext, dict[str, bytes]]:  # fmt: skip
    async def public(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    async def no_wait(seconds: float) -> None:
        return None

    stored: dict[str, bytes] = {}

    async def store(key: str, body: bytes) -> None:
        stored[key] = body

    fetcher = SafeFetcher(agent, resolver=public, transport=httpx.MockTransport(site))
    capture = CaptureFetcher(fetcher, MemoryRateLimiter(), rate_per_minute=6000, sleep=no_wait)
    return ConnectorContext(fetcher=capture, store=store, now=lambda: NOW), stored


PARAMS = {"feed": "search", "type": "all", "title_terms": ["cyber", "data protection"],
          "sort": "published", "max_pages_per_term": 2, "fetch_format": "data.xml"}  # fmt: skip


def job(**params: Any) -> JobSettings:
    config = ApiFeedConfig(provider="legislation_gov_uk", params={**PARAMS, **params})  # type: ignore[arg-type]
    return JobSettings(source_id="s1", kind="api_feed", config=config, rules=ExtractionRules(),
                       rate_per_minute=6000)  # fmt: skip


async def discover(site: Site, notes: set[str] | None = None, agent: str | None = None,
                   **params: Any) -> list[Candidate]:  # fmt: skip
    ctx, _ = context(site, *([agent] if agent else []))
    if notes is not None:
        ctx.notes = notes
    return [c async for c in ApiFeedConnector().discover(job(**params), ctx)]


async def test_each_term_is_searched_and_pages_follow_rel_next() -> None:
    page2 = f"{LEG}/all/data.feed?title=cyber&sort=published&page=2"
    site = Site({("cyber", "1"): feed([entry(1), entry(2)], page2),
                 ("cyber", "2"): feed([entry(3)]),
                 ("data protection", "1"): feed([entry(2), entry(4)])})  # fmt: skip
    notes: set[str] = set()
    got = await discover(site, notes)
    assert [c.external_id for c in got] == [f"http://www.legislation.gov.uk/id/uksi/2026/{n}"
                                            for n in (1, 2, 3, 4)]  # fmt: skip
    first = got[0]
    assert first.title == "The Cyber Regulations 1" and first.summary == "Summary 1"
    assert first.published_at == datetime(2026, 11, 1, tzinfo=UTC)
    assert first.hints["fetch"] == f"{LEG}/uksi/2026/1/made/data.xml"
    assert notes == set()  # every term ran out of pages


async def test_pages_past_the_cap_make_the_run_truncated() -> None:
    site = Site({("cyber", str(n)): feed([entry(n)],
                                         f"{LEG}/all/data.feed?title=cyber&page={n + 1}")
                 for n in range(1, 6)})  # fmt: skip
    notes: set[str] = set()
    got = await discover(site, notes, title_terms=["cyber"], max_pages_per_term=2)
    assert len(got) == 2 and notes == {"truncated"}


@pytest.mark.parametrize(
    "following",
    ["https://evil.example/all/data.feed?page=2", f"{LEG}/uksi/data.feed?page=2",
     f"{LEG}/all/data.feed?title=cyber&sort=published"],
)  # fmt: skip
async def test_a_next_page_must_be_the_same_feed_and_new(following: str) -> None:
    site = Site({("cyber", "1"): feed([entry(1)], following)})
    with pytest.raises(ConnectorError) as exc:
        await discover(site, title_terms=["cyber"])
    assert exc.value.reason == "malformed-answer"


async def test_links_must_be_https_on_legislation_gov_uk() -> None:
    site = Site({("cyber", "1"): feed([
        entry(1, link="javascript:alert(1)"), entry(2, link="https://evil.example/x"),
        entry(3, link="http://www.legislation.gov.uk/uksi/2026/3/made"),
        entry(4, xml="http://10.0.0.5/data.xml"), entry(5)])})  # fmt: skip
    got = await discover(site, title_terms=["cyber"])
    # Review finding 2: an http link on the host is kept, as https; other hosts are dropped.
    assert [c.external_id.rsplit("/", 1)[1] for c in got if c.external_id] == ["3", "4", "5"]
    assert got[0].url == f"{LEG}/uksi/2026/3/made"
    assert got[1].hints["fetch"] == f"{LEG}/uksi/2026/4/made"  # its data.xml was refused


async def test_an_anonymous_user_agent_is_refused() -> None:
    """E-UK-3: anonymous user agents are not accepted (BL-29)."""
    site = Site({})
    with pytest.raises(ConnectorError) as exc:
        await discover(site, agent="regwatch/0.1.0")
    assert exc.value.reason == "needs-contact" and site.paths == []  # nothing was requested


async def test_unsafe_and_non_feed_answers_are_refused() -> None:
    bomb = (b'<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY a "x">]>'
            b'<feed xmlns="http://www.w3.org/2005/Atom"><title>&a;</title></feed>')  # fmt: skip
    with pytest.raises(ConnectorError) as exc:
        await discover(Site({("cyber", "1"): bomb}), title_terms=["cyber"])
    assert exc.value.reason == "unsafe-feed"
    with pytest.raises(ConnectorError) as exc:
        await discover(Site({("cyber", "1"): b"<html><body>hi</body></html>"}),
                       title_terms=["cyber"])  # fmt: skip
    assert exc.value.reason == "malformed-feed"


async def test_fetch_stores_data_xml_or_the_page() -> None:
    ctx, stored = context(Site({}))
    xml = Candidate(url=f"{LEG}/uksi/2026/1/made", summary="S",
                    hints={"provider": "legislation_gov_uk",
                           "fetch": f"{LEG}/uksi/2026/1/made/data.xml"})  # fmt: skip
    raw = await ApiFeedConnector().fetch(xml, job(), ctx)
    assert raw.mime == "application/xml" and stored[raw.body_ref] == b"<Legislation/>"
    assert raw.text is None and raw.metadata["summary"] == "S"  # the body is the act (finding 9)
    assert raw.metadata["fetched"].endswith("/data.xml")
    bad = {"provider": "legislation_gov_uk", "fetch": "http://10.0.0.5/x"}
    sneaky = Candidate(url=f"{LEG}/uksi/2026/2/made", hints=bad)
    page = await ApiFeedConnector().fetch(sneaky, job(), ctx)
    assert page.metadata["fetched"] == f"{LEG}/uksi/2026/2/made"  # never the refused link


@pytest.mark.parametrize(
    "params",
    [{"title_terms": []}, {"title_terms": ["x" * 101]}, {"title_terms": "cyber"},
     {"title_terms": ["a"] * 21}, {"type": "../etc"}, {"feed": "update"}, {"sort": "random"},
     {"max_pages_per_term": 0}, {"max_pages_per_term": 9}, {"max_pages_per_term": True},
     {"fetch_format": "data.pdf"}, {"unknown": 1}, {"type": "uksi\n"},
     {"title_terms": ["cyber", " Cyber "]}],
)  # fmt: skip
def test_settings_are_checked_when_saved(params: dict[str, Any]) -> None:
    with pytest.raises(ConnectorError) as exc:
        check_params(ApiFeedConfig(provider="legislation_gov_uk", params={**PARAMS, **params}))  # type: ignore[arg-type]
    assert exc.value.reason == "bad-config"
    check_params(ApiFeedConfig(provider="legislation_gov_uk", params=PARAMS))  # type: ignore[arg-type]


def test_the_contact_check_finds_the_user_agent_through_wrappers() -> None:
    class Inner:
        user_agent = "regwatch (+a@b.example)"

    class Wrapper:
        inner = Inner()

    class Loose:
        user_agent = "regwatch/0.1 @"  # an "@" alone is no contact address (finding 5)

    ctx = ConnectorContext(fetcher=Wrapper(), store=None, now=lambda: NOW)  # type: ignore[arg-type]
    assert legislation.user_agent_has_contact(ctx)
    loose = ConnectorContext(fetcher=Loose(), store=None, now=lambda: NOW)  # type: ignore[arg-type]
    assert not legislation.user_agent_has_contact(loose)
    bare = ConnectorContext(fetcher=object(), store=None, now=lambda: NOW)  # type: ignore[arg-type]
    assert not legislation.user_agent_has_contact(bare)


async def test_entries_without_data_xml_and_feeds_with_other_links() -> None:
    plain = ("<entry><id>http://www.legislation.gov.uk/id/uksi/2026/9</id><title>Nine</title>"
             f'<link rel="alternate" href="{LEG}/uksi/2026/9/made"/></entry>')  # fmt: skip
    body = ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>S</title>'
            f'<link rel="self" href="{LEG}/all/data.feed"/>{plain}</feed>').encode()  # fmt: skip
    got = await discover(Site({("cyber", "1"): body}), title_terms=["cyber"])
    assert got[0].hints["fetch"] == f"{LEG}/uksi/2026/9/made"  # no data.xml: the page


async def test_error_statuses_are_refused() -> None:
    class Failing(Site):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return super().__call__(request)
            return httpx.Response(503, stream=httpx.ByteStream(b"down"))

    with pytest.raises(ConnectorError) as exc:
        await discover(Failing({}), title_terms=["cyber"])
    assert exc.value.reason == "http-status"
    ctx, stored = context(Failing({}))
    page = Candidate(url=f"{LEG}/uksi/2026/1/made", hints={"provider": "legislation_gov_uk"})
    with pytest.raises(ConnectorError) as exc:
        await ApiFeedConnector().fetch(page, job(), ctx)
    assert exc.value.reason == "http-status" and stored == {}


@pytest.mark.parametrize(
    "xml",
    [f"{LEG}/uksi/2026/1/made/data.pdf", f"{LEG}/uksi/2026/1/made/data.pdf#/data.xml",
     f"{LEG}/uksi/2026/1/made/DATA.DOCX"],
)  # fmt: skip
async def test_disallowed_documents_are_never_fetch_targets(xml: str) -> None:
    """Review finding 1: robots.txt's exclusions hold in the adapter itself."""
    site = Site({("cyber", "1"): feed([entry(1, xml=xml)])})
    got = await discover(site, title_terms=["cyber"])
    assert got[0].hints["fetch"] == f"{LEG}/uksi/2026/1/made"
    assert legislation._own(xml) is None


async def test_the_rate_is_capped_and_robots_is_always_obeyed() -> None:
    """Review finding 1: 12 a minute (Crawl-delay 5) and no robots.txt override."""
    calls: list[dict[str, Any]] = []

    class Recording:
        user_agent = "regwatch-test (+ops@example.org)"

        async def fetch(self, url: str, **kwargs: Any) -> Any:
            calls.append(kwargs)
            from regwatch.capture.safe_fetch import FetchResult

            return FetchResult(url, 200, {"content-type": "application/atom+xml"}, feed([]))

    ctx = ConnectorContext(fetcher=Recording(), store=None, now=lambda: NOW)  # type: ignore[arg-type]
    settings = JobSettings(source_id="s", kind="api_feed",
                           config=ApiFeedConfig(provider="legislation_gov_uk", params=PARAMS),  # type: ignore[arg-type]
                           rules=ExtractionRules(), rate_per_minute=120,
                           robots_override="Owner said so")  # fmt: skip
    [c async for c in ApiFeedConnector().discover(settings, ctx)]
    assert calls and all(c["rate_per_minute"] == 12 and c["robots_override"] is None
                         and c["allow_hop"] is legislation._strict for c in calls)  # fmt: skip


async def test_answers_from_another_host_are_refused() -> None:
    """Review finding 3: a redirect off www.legislation.gov.uk is never stored."""

    class Redirects(Site):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(404, stream=httpx.ByteStream(b""))
            if request.headers.get("host") == "www.legislation.gov.uk":
                return httpx.Response(302, headers={"Location": "https://mirror.example/feed"})
            return httpx.Response(200, headers={"content-type": "application/atom+xml"},
                                  stream=httpx.ByteStream(feed([entry(1)])))  # fmt: skip

    with pytest.raises(ConnectorError) as exc:
        await discover(Redirects({}), title_terms=["cyber"])
    assert exc.value.reason == "off-host"


async def test_a_next_page_must_be_the_same_search() -> None:
    """Review finding 4: dropping or changing the title would read the unfiltered feed."""
    site = Site({("cyber", "1"): feed([entry(1)], f"{LEG}/all/data.feed?sort=published&page=2")})
    with pytest.raises(ConnectorError) as exc:
        await discover(site, title_terms=["cyber"])
    assert exc.value.reason == "malformed-answer"


async def test_a_page_with_no_usable_entry_is_an_error() -> None:
    """Review finding 2: never a silent success that captured nothing."""
    site = Site({("cyber", "1"): feed([entry(1, link="https://evil.example/x")])})
    with pytest.raises(ConnectorError) as exc:
        await discover(site, title_terms=["cyber"])
    assert exc.value.reason == "malformed-answer"


async def test_a_document_off_the_host_is_refused() -> None:
    ctx, stored = context(Site({}))
    off = Candidate(url="https://evil.example/x", hints={"provider": "legislation_gov_uk"})
    with pytest.raises(ConnectorError) as exc:
        await ApiFeedConnector().fetch(off, job(), ctx)
    assert exc.value.reason == "bad-link" and stored == {}


@pytest.mark.parametrize(
    "location",
    [f"{LEG}/uksi/2026/1/made/data.pdf",  # robots.txt would allow it here: it answers 404
     "http://www.legislation.gov.uk/uksi/2026/1/made/data.xml",  # plain http
     "https://www.legislation.gov.uk:8443/uksi/2026/1/made/data.xml",  # another port
     "https://mirror.example/back"],  # another host, even if it redirects back
)  # fmt: skip
async def test_every_redirect_hop_must_stay_on_the_allowed_addresses(location: str) -> None:
    """Re-verification R1: each hop, before it is contacted, not only the final URL."""
    hosts: list[str] = []

    class Redirecting(Site):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            hosts.append(f"{request.headers.get('host')}{request.url.path}")
            if request.url.path == "/robots.txt":
                return httpx.Response(404, stream=httpx.ByteStream(b""))
            if request.url.path.endswith("/data.xml"):
                return httpx.Response(302, headers={"Location": location})
            return httpx.Response(200, stream=httpx.ByteStream(b"stored?"))

    ctx, stored = context(Redirecting({}))
    doc = Candidate(url=f"{LEG}/uksi/2026/1/made",
                    hints={"provider": "legislation_gov_uk",
                           "fetch": f"{LEG}/uksi/2026/1/made/data.xml"})  # fmt: skip
    with pytest.raises(ConnectorError) as exc:
        await ApiFeedConnector().fetch(doc, job(), ctx)
    assert exc.value.reason == "off-host" and stored == {}
    assert all("data.pdf" not in h and "mirror.example" not in h and "8443" not in h
               for h in hosts)  # the refused hop was never contacted  # fmt: skip


@pytest.mark.parametrize(
    "path",
    ["/uksi/2026/1/made/data.pdf/", "/uksi/2026/1/made/data.pdf;x", "/uksi/2026/1/made/data%2Epdf",
     "/uksi/2026/1/data.docx/made"],
)  # fmt: skip
def test_disallowed_names_are_found_anywhere_in_the_decoded_path(path: str) -> None:
    assert legislation._own(f"{LEG}{path}") is None and not legislation._strict(f"{LEG}{path}")


@pytest.mark.parametrize(
    "query",
    ["title=other&title=cyber&sort=published", "title=cyber&sort=title",
     "title=cyber&sort=published&text=x", "title=cyber&sort=published&sort=title"],
)  # fmt: skip
async def test_a_next_page_may_only_add_the_page(query: str) -> None:
    """Re-verification R2."""
    site = Site({("cyber", "1"): feed([entry(1)], f"{LEG}/all/data.feed?{query}&page=2")})
    with pytest.raises(ConnectorError) as exc:
        await discover(site, title_terms=["cyber"])
    assert exc.value.reason == "malformed-answer"
