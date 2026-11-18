"""The bounded web crawl (M3 design notes; acceptance 5; ADR-0009 amendment 2)."""

from __future__ import annotations

import json
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
                rules: dict[str, Any] | None = None,
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
                     extraction_rules={"content_selectors": ["div.c"], **(rules or {})},
                     cursor=cursor)  # fmt: skip
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
    assert len(whole.documents) == 6 and whole.status == "success"  # /gone is a 404: a skip (R18)
    assert "unavailable 1" in (whole.error_message or "")
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
    # The remembered pages are still asked (R13): the seed alone failed.
    assert (down.status, down.items_unchanged) == ("partial", 4)
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
    with pytest.raises(ConnectorError) as exc:
        [c async for c in web_crawl.WebCrawlConnector().discover(job, ctx)]
    assert exc.value.reason == "override-redirect"


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

    monkeypatch.setattr(web_page, "MAX_STATE", 10)  # the one definition (R12)
    site = Site({"reg.example/": ("Home", [f"/p{n}" for n in range(15)]),
                 **{f"reg.example/p{n}": (f"P{n}", []) for n in range(15)}})  # fmt: skip
    objects: dict[str, bytes] = {}
    cursor = None
    new = 0
    for _ in range(12):
        got = await crawl(site, objects, cursor, max_pages_per_run=6)
        cursor = got.cursor or cursor
        new += got.items_new
    assert new == 10 and "remembers (10)" in (got.error_message or "")


async def test_a_crawl_limit_says_to_raise_it() -> None:
    """R7: the message no longer promises that the next run continues."""
    site = Site({"reg.example/": ("Home", [f"/p{n}" for n in range(5)]),
                 **{f"reg.example/p{n}": (f"P{n}", []) for n in range(5)}})  # fmt: skip
    got = await crawl(site, {}, max_pages_per_run=2)
    assert "covers them over several runs" in (got.error_message or "")


def test_a_punycode_label_ends_in_a_letter_or_digit() -> None:
    assert not web_crawl._DOMAIN.fullmatch("a.xn---")
    assert web_crawl._DOMAIN.fullmatch("reg.xn--p1ai")


async def test_pages_that_are_gone_leave_the_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-verification R10 and R27: a site that replaces two pages a run never fills the state
    for good; a gone page leaves after three runs of 404 while the site serves (6 live, up to
    6 lingering, the seed: 13)."""
    from regwatch.capture.connectors import web_page

    monkeypatch.setattr(web_page, "MAX_STATE", 13)
    objects: dict[str, bytes] = {}
    cursor = None
    live = [f"/d{n}" for n in range(6)]
    for run in range(8):
        site = Site({"reg.example/": ("Home", live),
                     **{f"reg.example{p}": (p, []) for p in live}})  # fmt: skip
        got = await crawl(site, objects, cursor)
        cursor = got.cursor or cursor
        fetched = {a for a in site.asked if a.startswith("reg.example/d")}
        assert fetched >= {f"reg.example{p}" for p in live[-2:]}, run  # new pages found
        gone = live[:2]
        live = live[2:] + [f"/d{6 + 2 * run}", f"/d{7 + 2 * run}"]
        site.pages.update({f"reg.example{p}": (404, {}) for p in gone})
    state = json.loads(objects[cursor["listing_ref"]])
    assert len(state) <= 13


async def test_no_live_page_is_new_twice_behind_a_deep_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-verification R13: cap 10, a seed, 4 sections of 3 unchanged leaves, 6 a run."""
    from regwatch.capture.connectors import web_page

    monkeypatch.setattr(web_page, "MAX_STATE", 10)
    pages: dict[str, Any] = {"reg.example/": ("Home", [f"/s{n}" for n in range(4)])}
    for n in range(4):
        pages[f"reg.example/s{n}"] = (f"S{n}", [f"/s{n}/l{m}" for m in range(3)])
        pages.update({f"reg.example/s{n}/l{m}": (f"L{n}{m}", []) for m in range(3)})
    site = Site(pages)
    objects: dict[str, bytes] = {}
    cursor = None
    counts: dict[str, int] = {}
    for _ in range(16):
        got = await crawl(site, objects, cursor, max_pages_per_run=6)
        cursor = got.cursor or cursor
        for d in got.documents:
            if d.change == "new":
                counts[d.url] = counts.get(d.url, 0) + 1
    assert counts and max(counts.values()) == 1


async def test_a_long_rotation_keeps_every_baseline() -> None:
    """R14: 15 unchanged pages, 6 a run, runs 11 days apart: 15 new in all."""
    from datetime import timedelta

    site = Site({"reg.example/": ("Home", [f"/p{n}" for n in range(14)]),
                 **{f"reg.example/p{n}": (f"P{n}", []) for n in range(14)}})  # fmt: skip
    objects: dict[str, bytes] = {}
    cursor = None
    new = 0
    for _ in range(9):
        CLOCK[0] += timedelta(days=11)
        got = await crawl(site, objects, cursor, max_pages_per_run=6)
        cursor = got.cursor or cursor
        new += got.items_new
    assert new == 15


async def test_several_seeds_go_on_past_one_that_redirects() -> None:
    """R15: with several seeds, one redirecting under the override is one failure."""
    site = Site({"reg.example/": (301, {"location": "https://www.reg.example/"}),
                 "docs.reg.example/": ("Docs", [])})  # fmt: skip
    got = await crawl(site, {}, override="The regulator agreed in writing",
                      seed_urls=[SEED, "https://docs.reg.example/"])  # fmt: skip
    assert names(got) == ["docs.reg.example/"] and got.status == "partial"


async def test_an_inner_redirect_under_the_override_is_one_failure() -> None:
    """R11: sign-in or download links that redirect off the origin do not stop the run."""
    site = Site({"reg.example/": ("Home", ["/go0", "/go1", "/p0", "/p1"]),
                 "reg.example/go0": (302, {"location": "https://login.reg.example/"}),
                 "reg.example/go1": (302, {"location": "https://login.reg.example/"}),
                 "reg.example/p0": ("P0", []), "reg.example/p1": ("P1", [])})  # fmt: skip
    got = await crawl(site, {}, override="The regulator agreed in writing")
    assert got.status == "partial" and got.error_class == "some-failed"
    assert {"reg.example/p0", "reg.example/p1"} <= {n for n in names(got)}


async def test_narrowing_the_patterns_frees_the_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-verification R16 (A): excluded pages leave the state at once."""
    from regwatch.capture.connectors import web_page

    monkeypatch.setattr(web_page, "MAX_STATE", 10)
    pages: dict[str, Any] = {"reg.example/": ("Home", [f"/news/n{n}" for n in range(8)]
                                              + [f"/docs/d{n}" for n in range(4)])}  # fmt: skip
    pages.update({f"reg.example/news/n{n}": (f"N{n}", []) for n in range(8)})
    pages.update({f"reg.example/docs/d{n}": (f"D{n}", []) for n in range(4)})
    site = Site(pages)
    objects: dict[str, bytes] = {}
    first = await crawl(site, objects)
    narrowed = await crawl(site, objects, first.cursor, rules={"exclude_url_patterns": ["/news/"]})
    state = json.loads(objects[narrowed.cursor["listing_ref"]])
    assert not any("/news/" in u for u in state)
    assert {f"https://reg.example/docs/d{n}" for n in range(4)} <= set(state)


async def test_a_page_that_redirects_elsewhere_is_gone() -> None:
    """R16 (B): a removed page answering 301 to the home page leaves the state."""
    site = Site({"reg.example/": ("Home", ["/old"]), "reg.example/old": ("Old", [])})
    objects: dict[str, bytes] = {}
    first = await crawl(site, objects)
    site.pages["reg.example/old"] = (301, {"location": "https://reg.example/"})
    cursor = first.cursor
    for _ in range(3):  # gone after three such runs while the site serves (R27)
        second = await crawl(site, objects, cursor)
        cursor = second.cursor or cursor
        assert [d.url for d in second.documents if d.change != "unchanged"] == []
    state = json.loads(objects[cursor["listing_ref"]])
    assert "https://reg.example/old" not in state
    site.pages["reg.example/"] = ("Home", ["/moved"])
    site.pages["reg.example/moved"] = (301, {"location": "https://reg.example/renamed"})
    site.pages["reg.example/renamed"] = ("Renamed", [])
    third = await crawl(site, objects, cursor)
    assert "https://reg.example/renamed" in [d.url for d in third.documents]  # crawled as itself


async def test_a_page_failing_three_runs_in_a_row_is_forgotten() -> None:
    """R16 (C)."""
    site = Site({"reg.example/": ("Home", ["/flaky"]), "reg.example/flaky": ("F", [])})
    objects: dict[str, bytes] = {}
    cursor = (await crawl(site, objects)).cursor
    site.pages["reg.example/"] = ("Home", [])  # no longer linked, and now refused, while the
    site.pages["reg.example/flaky"] = (400, {})  # same host serves the seed (R24)
    for _ in range(3):
        cursor = (await crawl(site, objects, cursor)).cursor or cursor
    assert "https://reg.example/flaky" not in json.loads(objects[cursor["listing_ref"]])


async def test_a_shallower_link_lowers_a_pages_depth() -> None:
    """R17: x first found at max_depth, later linked from the seed, has its links followed."""
    site = Site({"reg.example/": ("Home", ["/a"]), "reg.example/a": ("A", ["/x"]),
                 "reg.example/x": ("X", ["/y"]), "reg.example/y": ("Y", [])})  # fmt: skip
    objects: dict[str, bytes] = {}
    first = await crawl(site, objects, max_depth=2)
    assert "reg.example/y" not in site.asked
    site.pages["reg.example/"] = ("Home", ["/a", "/x"])
    site.asked.clear()
    await crawl(site, objects, first.cursor, max_depth=2)
    assert "reg.example/y" in site.asked


@pytest.mark.parametrize("status", [503, 429, 408, 403, 401])
async def test_an_outage_never_makes_pages_new_again(status: int) -> None:
    """Re-verification R20: three hours of 5xx or 429 forget nothing."""
    pages = {"reg.example/": ("Home", [f"/p{n}" for n in range(6)]),
             **{f"reg.example/p{n}": (f"P{n}", []) for n in range(6)}}  # fmt: skip
    site = Site(dict(pages))
    objects: dict[str, bytes] = {}
    cursor = (await crawl(site, objects)).cursor
    site.pages.update({f"reg.example/p{n}": (status, {}) for n in range(6)})
    for _ in range(4):
        cursor = (await crawl(site, objects, cursor)).cursor or cursor
    site.pages = dict(pages)
    after = await crawl(site, objects, cursor)
    assert (after.items_new, after.items_unchanged) == (0, 7)


async def test_a_redirect_target_is_normalised_like_a_link() -> None:
    """R22 (a): https://REG.example:443/doc/ and /doc/ are one page."""
    site = Site({"reg.example/": ("Home", ["/doc/", "/old"]),
                 "reg.example/doc/": ("Doc", []),
                 "reg.example/old": (301, {"location": "https://REG.example:443/doc/"})},
                )  # fmt: skip
    got = await crawl(site, {})
    assert [d.url for d in got.documents].count("https://reg.example/doc/") == 1


@pytest.mark.parametrize(
    ("fail", "runs"),
    [({"reg.example/": (404, {}), **{f"reg.example/p{n}": (404, {}) for n in range(6)}}, 1),
     ({"reg.example/": (410, {}), **{f"reg.example/p{n}": (410, {}) for n in range(6)}}, 1),
     ({f"reg.example/p{n}": (404, {}) for n in range(6)}, 1),
     ({"reg.example/": (302, {"location": "https://status.example/"}),
       **{f"reg.example/p{n}": (302, {"location": "https://status.example/"}) for n in range(6)}},
      3)],
)  # fmt: skip
async def test_a_site_wide_failure_forgets_nothing(fail: dict[str, Any], runs: int) -> None:
    """Re-verification 8 R27: a bad deploy, a site-wide 410, a content backend down for a run,
    or an off-site status page for three runs: the recovery run is unchanged."""
    pages = {"reg.example/": ("Home", [f"/p{n}" for n in range(6)]),
             **{f"reg.example/p{n}": (f"P{n}", []) for n in range(6)}}  # fmt: skip
    site = Site(dict(pages))
    objects: dict[str, bytes] = {}
    cursor = (await crawl(site, objects)).cursor
    site.pages.update(fail)
    for _ in range(runs):
        cursor = (await crawl(site, objects, cursor)).cursor or cursor
    site.pages = dict(pages)
    after = await crawl(site, objects, cursor)
    assert (after.items_new, after.items_unchanged) == (0, 7)


async def test_an_extraction_timeout_forgets_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """R25: too-slow can be a busy worker, so it never counts towards forgetting a page."""
    site = Site({"reg.example/": ("Home", ["/a"]), "reg.example/a": ("A", [])})
    objects: dict[str, bytes] = {}
    cursor = (await crawl(site, objects)).cursor
    real = web_crawl._extract

    async def slow(got: Any, job: Any, links: Any = None) -> Any:
        if got.url.endswith("/a"):
            raise ConnectorError("too-slow", "slow")
        return await real(got, job, links)

    monkeypatch.setattr(web_crawl, "_extract", slow)
    for _ in range(4):
        cursor = (await crawl(site, objects, cursor)).cursor or cursor
    assert "https://reg.example/a" in json.loads(objects[cursor["listing_ref"]])


async def test_finish_without_a_crawl_is_harmless() -> None:
    ctx = ConnectorContext(fetcher=None, store=None, now=lambda: NOW)  # type: ignore[arg-type]
    config = WebCrawlConfig(seed_urls=[SEED], allowed_domains=["reg.example"])  # type: ignore[list-item]
    job = JobSettings(source_id="s", kind="web_crawl", config=config, rules=ExtractionRules())
    await web_crawl.WebCrawlConnector().finish(job, ctx)
    assert ctx.state is None


@pytest.mark.parametrize(("job_rate", "politeness"), [(10, 2.0), (30, 6.0)])
async def test_ten_a_minute_under_a_200_page_crawl(monkeypatch: pytest.MonkeyPatch, job_rate: int,
                                                   politeness: float) -> None:  # fmt: skip
    """M3 acceptance 5: on a simulated clock, no 60 s window holds more than 10 requests to the
    host (robots.txt included) across a 200-page crawl. Extraction is stubbed: this measures
    the requests, not the parsing."""
    from regwatch.capture.extract.text import Extracted
    from regwatch.capture.safe_fetch import rate as rate_mod

    clock = [0.0]
    monkeypatch.setattr(rate_mod.time, "monotonic", lambda: clock[0])

    async def sleep(seconds: float) -> None:
        clock[0] += seconds

    async def fast(got: Any, job: Any, links: Any = None) -> Extracted:
        home = got.url.endswith("reg.example/")
        found = [f"/p{n}" for n in range(199)] if home and links else []
        return Extracted(text=got.url, content_hash=f"{abs(hash(got.url)):064d}"[:64],
                         links=found)  # fmt: skip

    monkeypatch.setattr(web_crawl, "_extract", fast)
    times: list[float] = []

    def timed(request: httpx.Request) -> httpx.Response:
        times.append(clock[0])
        clock[0] += 0.05
        if request.url.path == "/robots.txt":
            return httpx.Response(404, stream=httpx.ByteStream(b""))
        return httpx.Response(200, headers={"content-type": "text/html"},
                              stream=httpx.ByteStream(b"<p>x</p>"))  # fmt: skip

    async def make(settings: JobSettings) -> ConnectorContext:
        async def public(host: str, port: int) -> list[str]:
            return ["93.184.215.14"]

        async def nothing(key: str, body: bytes) -> None:
            return None

        fetcher = SafeFetcher("regwatch-test (+ops@example.org)", resolver=public,
                              transport=httpx.MockTransport(timed))  # fmt: skip
        capture = CaptureFetcher(fetcher, MemoryRateLimiter(), sleep=sleep)
        return ConnectorContext(fetcher=capture, store=nothing, now=tick)

    source = Source(id=uuid.UUID(int=9), kind="web_crawl", robots_policy="respect",
                    config={"seed_urls": [SEED], "allowed_domains": ["reg.example"],
                            "politeness_delay_seconds": politeness})  # fmt: skip
    job = CaptureJob(max_items_per_run=500, rate_limit_per_minute=job_rate, render_js=False,
                     extraction_rules={})  # fmt: skip
    got = await execution.run_connector(uuid.uuid4(), job, source, make)
    assert got.status == "success" and len(got.documents) == 200
    worst = max(sum(1 for t in times if start <= t < start + 60) for start in times)
    assert len(times) == 201 and worst <= 10
