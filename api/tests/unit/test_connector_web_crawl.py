"""The bounded web crawl (M3 design notes; acceptance 5; ADR-0009 amendment 2)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from regwatch.capture import execution
from regwatch.capture.connectors import web_crawl
from regwatch.capture.connectors.base import ConnectorContext, ConnectorError, JobSettings
from regwatch.capture.connectors.config import ExtractionRules, WebCrawlConfig
from regwatch.capture.models import CaptureJob, Source
from regwatch.capture.safe_fetch import CaptureFetcher, FetchResult, MemoryRateLimiter, SafeFetcher

NOW = datetime(2026, 11, 18, tzinfo=UTC)
SEED = "https://reg.example/"


class Site:
    """Pages by "host/path": a body of links and text, or a status, a type or a redirect."""

    def __init__(self, pages: dict[str, Any]) -> None:
        self.pages = pages
        self.asked: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        where = f"{request.headers['host']}{request.url.path}"
        self.asked.append(where)
        if request.url.path == "/robots.txt":
            rules = self.pages.get(where, "")
            return httpx.Response(200 if rules else 404, stream=httpx.ByteStream(rules.encode()))
        page = self.pages.get(where)
        if page is None:
            return httpx.Response(404, stream=httpx.ByteStream(b""))
        if isinstance(page[0], int):  # (status, headers)
            return httpx.Response(page[0], headers=page[1], stream=httpx.ByteStream(b"x"))
        text, links = page
        anchors = "".join(f'<a href="{h}">link</a>' for h in links)
        body = f"<div class=c><p>{text}</p></div><nav>{anchors}</nav>".encode()
        return httpx.Response(200, headers={"content-type": "text/html"},
                              stream=httpx.ByteStream(body))  # fmt: skip


CLOCK = [NOW]


def tick() -> datetime:
    """A clock that moves a second on every reading, so checked times never tie (R9)."""
    from datetime import timedelta

    CLOCK[0] += timedelta(seconds=1)
    return CLOCK[0]


async def crawl(site: Site, objects: dict[str, bytes], cursor: Any = None, *,
                override: str | None = None, max_items: int = 100,
                **config: Any) -> execution.Outcome:  # fmt: skip
    async def make(settings: JobSettings) -> ConnectorContext:
        async def public(host: str, port: int) -> list[str]:
            return ["93.184.215.14"]

        async def no_wait(seconds: float) -> None:
            return None

        async def store(key: str, body: bytes) -> None:
            objects[key] = body

        async def load(key: str) -> bytes | None:
            return objects.get(key)

        fetcher = SafeFetcher("regwatch-test (+ops@example.org)", resolver=public,
                              transport=httpx.MockTransport(site))  # fmt: skip
        capture = CaptureFetcher(fetcher, MemoryRateLimiter(), rate_per_minute=6000, sleep=no_wait)
        return ConnectorContext(fetcher=capture, store=store, now=tick, load=load)

    settings = {"seed_urls": [SEED], "allowed_domains": ["reg.example"],
                "politeness_delay_seconds": 0.5, **config}  # fmt: skip
    source = Source(id=uuid.UUID(int=9), kind="web_crawl",
                    robots_policy="override" if override else "respect", config=settings,
                    override_reason=override)  # fmt: skip
    job = CaptureJob(max_items_per_run=max_items, rate_limit_per_minute=6000, render_js=False,
                     extraction_rules={"content_selectors": ["div.c"]}, cursor=cursor)  # fmt: skip
    return await execution.run_connector(uuid.uuid4(), job, source, make)


def names(outcome: execution.Outcome) -> list[str]:
    return [d.url.split("://", 1)[1] for d in outcome.documents]


async def test_breadth_first_within_depth_and_domains() -> None:
    site = Site({
        "reg.example/": ("Home", ["/a", "/b", "https://docs.reg.example/c", "https://other.example/x",
                                  "mailto:x@reg.example", "/a?page=2"]),
        "reg.example/a": ("A", ["/a/deep"]),
        "reg.example/b": ("B", []),
        "docs.reg.example/c": ("C", []),
        "reg.example/a/deep": ("Deep", ["/a/deeper"]),
        "reg.example/a/deeper": ("Deeper", []),
    })  # fmt: skip
    got = await crawl(site, {}, max_depth=2)
    assert got.status == "success"
    assert names(got) == ["reg.example/", "reg.example/a", "reg.example/b", "docs.reg.example/c",
                          "reg.example/a/deep"]  # fmt: skip
    assert not any("other.example" in a for a in site.asked)
    assert "reg.example/a/deeper" not in site.asked  # past max_depth
    assert site.asked.count("reg.example/a") == 1  # fetched once: discovery's page is the document


async def test_a_second_run_is_unchanged_and_a_change_is_found() -> None:
    site = Site({"reg.example/": ("Home", ["/a"]), "reg.example/a": ("A", [])})
    objects: dict[str, bytes] = {}
    first = await crawl(site, objects)
    assert (first.items_new, first.cursor["listing_ref"]) == (2, "state/" + str(uuid.UUID(int=9))
                                                              + "/listing-a.json")  # fmt: skip
    same = await crawl(site, objects, first.cursor)
    assert (same.items_unchanged, same.items_new) == (2, 0)
    site.pages["reg.example/a"] = ("A, amended", [])
    moved = await crawl(site, objects, same.cursor)
    assert (moved.items_changed, moved.items_unchanged) == (1, 1)


async def test_the_page_limit_truncates_and_other_pages_are_passed_over() -> None:
    site = Site({"reg.example/": ("Home", [f"/p{n}" for n in range(5)] + ["/r.pdf", "/gone"]),
                 "reg.example/r.pdf": (200, {"content-type": "application/pdf"}),
                 **{f"reg.example/p{n}": (f"P{n}", []) for n in range(5)}})  # fmt: skip
    cut = await crawl(site, {}, max_pages_per_run=3)
    assert (cut.status, cut.error_class, len(cut.documents)) == ("partial", "truncated", 3)
    whole = await crawl(site, {})
    assert len(whole.documents) == 6 and whole.status == "partial"  # /gone is a 404: failed
    assert "reg.example/r.pdf" not in names(whole)


async def test_redirects_off_the_domains_are_refused() -> None:
    site = Site({"reg.example/": ("Home", ["/out"]),
                 "reg.example/out": (302, {"location": "https://other.example/x"})})  # fmt: skip
    got = await crawl(site, {})
    assert names(got) == ["reg.example/"] and got.status == "partial"
    assert not any("other.example" in a for a in site.asked)


async def test_the_override_is_the_seeds_alone() -> None:
    """8.3: other hosts' robots.txt is obeyed even when the source overrides its own."""
    site = Site({"reg.example/robots.txt": "User-agent: *\nDisallow: /\n",
                 "docs.reg.example/robots.txt": "User-agent: *\nDisallow: /\n",
                 "reg.example/": ("Home", ["https://docs.reg.example/c"]),
                 "docs.reg.example/c": ("C", [])})  # fmt: skip
    got = await crawl(site, {}, override="The regulator agreed in writing")
    assert names(got) == ["reg.example/"]
    assert "docs.reg.example/c" not in site.asked


async def test_three_unreadable_pages_stop_the_run() -> None:
    deep = (b"<div>" * 1000).decode()
    site = Site({"reg.example/": ("Home", [f"/d{n}" for n in range(6)]),
                 **{f"reg.example/d{n}": (deep, []) for n in range(6)}})  # fmt: skip
    got = await crawl(site, {})
    assert (got.status, got.error_class) == ("partial", "unreadable-pages")
    assert sum(1 for a in site.asked if a.startswith("reg.example/d")) == 3


async def test_the_politeness_delay_sets_the_rate() -> None:
    """Acceptance 5: 10 a minute when the delay is 6 s, whatever the job's own rate."""
    calls: list[int] = []

    class Recording:
        async def fetch(self, url: str, **kwargs: Any) -> FetchResult:
            calls.append(kwargs["rate_per_minute"])
            return FetchResult(url, 404, {}, b"")

    config = WebCrawlConfig(seed_urls=[SEED], allowed_domains=["reg.example"],  # type: ignore[list-item]
                            politeness_delay_seconds=6)  # fmt: skip
    job = JobSettings(source_id="s", kind="web_crawl", config=config, rules=ExtractionRules(),
                      rate_per_minute=120)  # fmt: skip
    ctx = ConnectorContext(fetcher=Recording(), store=None, now=lambda: NOW)  # type: ignore[arg-type]
    [c async for c in web_crawl.WebCrawlConnector().discover(job, ctx)]
    assert calls == [10]


@pytest.mark.parametrize(
    ("config", "message"),
    [({"allowed_domains": ["reg.example/"]}, "host names"), ({"allowed_domains": ["*.reg.example"]},
     "host names"), ({"seed_urls": ["https://other.example/"]}, "allowed domain"),
     ({"seed_urls": ["https://reg.example:8443/"]}, "allowed domain"),
     ({"seed_urls": ["ftp://reg.example/"]}, "allowed domain")],
)  # fmt: skip
def test_settings_are_checked_when_saved(config: dict[str, Any], message: str) -> None:
    base = {"seed_urls": [SEED], "allowed_domains": ["reg.example"]}
    parsed = WebCrawlConfig.model_validate({**base, **config})
    with pytest.raises(ConnectorError, match=message):
        web_crawl.check(parsed)
    web_crawl.check(WebCrawlConfig.model_validate(base))


@pytest.mark.parametrize(("config", "render"), [({"follow_sitemaps": True}, False), ({}, True)])
async def test_sitemaps_and_rendering_are_not_built_yet(config: dict[str, Any],
                                                        render: bool) -> None:  # fmt: skip
    parsed = WebCrawlConfig.model_validate({"seed_urls": [SEED], "allowed_domains": ["reg.example"],
                                            **config})  # fmt: skip
    job = JobSettings(source_id="s", kind="web_crawl", config=parsed, rules=ExtractionRules(),
                      render_js=render)  # fmt: skip
    ctx = ConnectorContext(fetcher=None, store=None, now=lambda: NOW)  # type: ignore[arg-type]
    with pytest.raises(ConnectorError) as exc:
        [c async for c in web_crawl.WebCrawlConnector().discover(job, ctx)]
    assert exc.value.reason == "not-implemented"
    assert web_crawl.WebCrawlConnector().health(job).status == "unknown"


async def test_the_override_never_leaves_the_seed_origin_by_redirect() -> None:
    """Review finding 1: the fetcher applies the override to every hop, so none may leave."""
    site = Site({"reg.example/robots.txt": "User-agent: *\nDisallow: /\n",
                 "docs.reg.example/robots.txt": "User-agent: *\nDisallow: /\n",
                 "reg.example/": ("Home", ["/go"]),
                 "reg.example/go": (302, {"location": "https://docs.reg.example/private"}),
                 "docs.reg.example/private": ("Private", [])})  # fmt: skip
    got = await crawl(site, {}, override="The regulator agreed in writing")
    assert names(got) == ["reg.example/"]
    assert "docs.reg.example/private" not in site.asked


async def test_pages_not_reached_keep_their_baseline() -> None:
    """Finding 2: a seed answering 503 once, or a truncated run, does not make pages new."""
    pages = {"reg.example/": ("Home", [f"/p{n}" for n in range(4)]),
             **{f"reg.example/p{n}": (f"P{n}", []) for n in range(4)}}  # fmt: skip
    site = Site(dict(pages))
    objects: dict[str, bytes] = {}
    first = await crawl(site, objects)
    site.pages["reg.example/"] = (503, {})
    down = await crawl(site, objects, first.cursor)
    assert down.status == "failed"
    site.pages = dict(pages)
    after = await crawl(site, objects, down.cursor)
    assert (after.items_new, after.items_unchanged) == (0, 5)


async def test_a_truncated_crawl_reaches_other_pages_next_time() -> None:
    """Finding 3: pages never checked first, then the longest unchecked, within a depth."""
    site = Site({"reg.example/": ("Home", [f"/p{n}" for n in range(6)]),
                 **{f"reg.example/p{n}": (f"P{n}", []) for n in range(6)}})  # fmt: skip
    objects: dict[str, bytes] = {}
    runs: list[list[str]] = []
    cursor = None
    for _ in range(3):
        site.asked.clear()
        got = await crawl(site, objects, cursor, max_pages_per_run=3)
        runs.append([a.rsplit("/", 1)[1] for a in site.asked if not a.endswith("robots.txt")])
        cursor = got.cursor or cursor
    assert runs == [["", "p0", "p1"], ["", "p2", "p3"], ["", "p4", "p5"]]


async def test_every_request_counts_against_the_limits() -> None:
    """Finding 4: 300 PDFs and a limit of 2 make 2 requests, not 300."""
    site = Site({"reg.example/": ("Home", [f"/r{n}.pdf" for n in range(300)]),
                 **{f"reg.example/r{n}.pdf": (200, {"content-type": "application/pdf"})
                    for n in range(300)}})  # fmt: skip
    got = await crawl(site, {}, max_pages_per_run=2)
    assert got.error_class == "truncated"
    assert sum(1 for a in site.asked if a.endswith(".pdf")) == 1


async def test_the_frontier_is_bounded_and_bodies_are_let_go(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding 5."""
    monkeypatch.setattr(web_crawl, "MAX_FRONTIER", 3)
    site = Site({"reg.example/": ("Home", [f"/p{n}" for n in range(10)]),
                 **{f"reg.example/p{n}": (f"P{n}", []) for n in range(10)}})  # fmt: skip
    got = await crawl(site, {})
    assert (got.error_class, len(got.documents)) == ("truncated", 4)
    from regwatch.capture.connectors.base import Candidate

    ctx_objects: dict[str, bytes] = {}
    candidate = Candidate(url="https://reg.example/", hints={})

    class Found:
        text, content_hash, title, method, warnings, published_at = (
            "t",
            "a" * 64,
            None,
            "m",
            [],
            None,
        )

    got_page = FetchResult("https://reg.example/", 200, {"content-type": "text/html"}, b"<p>t</p>")
    candidate.hints.update({"got": got_page, "found": Found(), "previous": [None, None]})

    async def store(key: str, body: bytes) -> None:
        ctx_objects[key] = body

    ctx = ConnectorContext(fetcher=None, store=store, now=lambda: NOW)  # type: ignore[arg-type]
    ctx.scratch["listing"] = {"listed": [], "pages": {}, "previous": {}, "origin": None,
                              "unreadable": 0, "tried": {}}  # fmt: skip
    config = WebCrawlConfig(seed_urls=[SEED], allowed_domains=["reg.example"])  # type: ignore[list-item]
    job = JobSettings(source_id="s", kind="web_crawl", config=config, rules=ExtractionRules())
    await web_crawl.WebCrawlConnector().fetch(candidate, job, ctx)
    assert "got" not in candidate.hints and "found" not in candidate.hints


async def test_a_timeout_in_discovery_is_one_failure_not_three_retries() -> None:
    """Finding 7."""
    from regwatch.capture.safe_fetch import FetchRefusedError

    calls: list[str] = []

    class Slow:
        async def fetch(self, url: str, **kwargs: Any) -> FetchResult:
            calls.append(url)
            raise FetchRefusedError("timeout", "slow")

    config = WebCrawlConfig(seed_urls=[SEED], allowed_domains=["reg.example"])  # type: ignore[list-item]
    job = JobSettings(source_id="s", kind="web_crawl", config=config, rules=ExtractionRules())
    ctx = ConnectorContext(fetcher=Slow(), store=None, now=lambda: NOW)  # type: ignore[arg-type]
    [candidate] = [c async for c in web_crawl.WebCrawlConnector().discover(job, ctx)]
    with pytest.raises(ConnectorError) as exc:
        await web_crawl.WebCrawlConnector().fetch(candidate, job, ctx)
    assert exc.value.reason == "timeout" and calls == [SEED]


@pytest.mark.parametrize(
    "url",
    ["https://evil.example\\.reg.example/", "https://evil.example%2e.reg.example/",
     "http://reg.example:443/", "https://reg.example:80/", "https://[::1]/"],
)  # fmt: skip
def test_hosts_are_judged_as_safe_fetcher_parses_them(url: str) -> None:
    """Finding 8 and the info item on ports."""
    assert not web_crawl._allowed(url, ["reg.example"])
    assert web_crawl._allowed("https://docs.reg.example/x", ["reg.example"])


async def test_the_dry_run_shows_refused_pages_as_warnings() -> None:
    """Finding 6."""
    from regwatch.capture import dryrun

    site = Site({"reg.example/robots.txt": "User-agent: *\nDisallow: /\n"})

    async def make(settings: JobSettings) -> ConnectorContext:
        async def public(host: str, port: int) -> list[str]:
            return ["93.184.215.14"]

        fetcher = SafeFetcher("regwatch-test (+ops@example.org)", resolver=public,
                              transport=httpx.MockTransport(site))  # fmt: skip
        capture = CaptureFetcher(fetcher, MemoryRateLimiter(), rate_per_minute=6000)
        return ConnectorContext(fetcher=capture, store=None, now=lambda: NOW)  # type: ignore[arg-type]

    source = Source(id=uuid.UUID(int=9), kind="web_crawl", robots_policy="respect",
                    config={"seed_urls": [SEED], "allowed_domains": ["reg.example"]},
                    override_reason=None)  # fmt: skip
    job = CaptureJob(max_items_per_run=10, rate_limit_per_minute=6000, render_js=False,
                     extraction_rules={})  # fmt: skip
    got = await dryrun.preview(job, source, make)
    assert got["candidates"] == [] and got["robots_decision"] == "disallowed"
    assert got["warnings"] == ["a page was refused or failed (robots)"]


async def test_files_that_are_not_pages_rotate_back_too() -> None:
    """Re-verification R1: PDFs no longer take the budget on every run."""
    site = Site({"reg.example/": ("Home", [f"/r{n}.pdf" for n in range(10)] + ["/page"]),
                 "reg.example/page": ("Page", []),
                 **{f"reg.example/r{n}.pdf": (200, {"content-type": "application/pdf"})
                    for n in range(10)}})  # fmt: skip
    objects: dict[str, bytes] = {}
    cursor = None
    reached = False
    for _ in range(3):
        site.asked.clear()
        got = await crawl(site, objects, cursor, max_pages_per_run=8)
        cursor = got.cursor or cursor
        reached = reached or "reg.example/page" in site.asked
    assert reached


async def test_deeper_pages_get_their_turn() -> None:
    """R2: six level-1 pages and a limit of 4 still reach level 2 within a few runs."""
    site = Site({"reg.example/": ("Home", [f"/p{n}" for n in range(6)]),
                 **{f"reg.example/p{n}": (f"P{n}", [f"/p{n}/child"]) for n in range(6)},
                 **{f"reg.example/p{n}/child": (f"C{n}", []) for n in range(6)}})  # fmt: skip
    objects: dict[str, bytes] = {}
    cursor = None
    asked: set[str] = set()
    for _ in range(5):
        site.asked.clear()
        got = await crawl(site, objects, cursor, max_pages_per_run=4)
        cursor = got.cursor or cursor
        asked.update(site.asked)
    assert any(a.endswith("/child") for a in asked)


async def test_a_seed_redirect_under_the_override_says_why() -> None:
    """R3."""
    site = Site({"reg.example/": (301, {"location": "https://www.reg.example/"}),
                 "www.reg.example/": ("Home", [])})  # fmt: skip
    got = await crawl(site, {}, override="The regulator agreed in writing")
    assert (got.status, got.error_class) == ("failed", "override-redirect")  # R8: shown
    config = WebCrawlConfig(seed_urls=[SEED], allowed_domains=["reg.example"])  # type: ignore[list-item]

    class Redirected:
        async def fetch(self, url: str, **kwargs: Any) -> FetchResult:
            from regwatch.capture.safe_fetch import FetchRefusedError

            raise FetchRefusedError("refused-host", "the redirect left the address")

    job = JobSettings(source_id="s", kind="web_crawl", config=config, rules=ExtractionRules(),
                      robots_override="The regulator agreed in writing")  # fmt: skip
    ctx = ConnectorContext(fetcher=Redirected(), store=None, now=lambda: NOW)  # type: ignore[arg-type]
    [candidate] = [c async for c in web_crawl.WebCrawlConnector().discover(job, ctx)]
    assert candidate.hints["error"].reason == "override-redirect"


def test_internationalised_top_level_domains_are_host_names() -> None:
    """R5."""
    parsed = WebCrawlConfig.model_validate({"seed_urls": ["https://reg.xn--p1ai/"],
                                            "allowed_domains": ["reg.xn--p1ai"]})  # fmt: skip
    web_crawl.check(parsed)
    assert web_crawl._allowed("https://docs.reg.xn--p1ai/", ["reg.xn--p1ai"])


async def test_the_dry_run_says_partly_disallowed() -> None:
    """R5: some pages refused by robots.txt, others offered."""
    from regwatch.capture import dryrun

    site = Site({"reg.example/robots.txt": "User-agent: *\nDisallow: /private\n",
                 "reg.example/": ("Home", ["/private", "/a"]),
                 "reg.example/a": ("A", [])})  # fmt: skip

    async def make(settings: JobSettings) -> ConnectorContext:
        async def public(host: str, port: int) -> list[str]:
            return ["93.184.215.14"]

        fetcher = SafeFetcher("regwatch-test (+ops@example.org)", resolver=public,
                              transport=httpx.MockTransport(site))  # fmt: skip
        capture = CaptureFetcher(fetcher, MemoryRateLimiter(), rate_per_minute=6000)
        return ConnectorContext(fetcher=capture, store=None, now=lambda: NOW)  # type: ignore[arg-type]

    source = Source(id=uuid.UUID(int=9), kind="web_crawl", robots_policy="respect",
                    config={"seed_urls": [SEED], "allowed_domains": ["reg.example"]},
                    override_reason=None)  # fmt: skip
    job = CaptureJob(max_items_per_run=10, rate_limit_per_minute=6000, render_js=False,
                     extraction_rules={})  # fmt: skip
    got = await dryrun.preview(job, source, make)
    assert got["robots_decision"] == "partly-disallowed" and len(got["candidates"]) == 2


async def test_pages_past_the_state_cap_are_not_admitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-verification R6: scaled down, cap 10 and 15 unchanged pages; nothing is new twice."""
    from regwatch.capture.connectors import web_page

    monkeypatch.setattr(web_crawl, "MAX_STATE", 10)
    monkeypatch.setattr(web_page, "MAX_STATE", 10)
    site = Site({"reg.example/": ("Home", [f"/p{n}" for n in range(15)]),
                 **{f"reg.example/p{n}": (f"P{n}", []) for n in range(15)}})  # fmt: skip
    objects: dict[str, bytes] = {}
    cursor = None
    new = 0
    for _ in range(12):
        got = await crawl(site, objects, cursor, max_pages_per_run=6)
        cursor = got.cursor or cursor
        new += got.items_new
    assert new == 10 and "remembers" in (got.error_message or "")


async def test_a_crawl_limit_says_to_raise_it() -> None:
    """R7: the message no longer promises that the next run continues."""
    site = Site({"reg.example/": ("Home", [f"/p{n}" for n in range(5)]),
                 **{f"reg.example/p{n}": (f"P{n}", []) for n in range(5)}})  # fmt: skip
    got = await crawl(site, {}, max_pages_per_run=2)
    assert "raise max_pages_per_run" in (got.error_message or "")


def test_a_punycode_label_ends_in_a_letter_or_digit() -> None:
    assert not web_crawl._DOMAIN.fullmatch("a.xn---")
    assert web_crawl._DOMAIN.fullmatch("reg.xn--p1ai")
