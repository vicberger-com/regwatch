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
        return ConnectorContext(fetcher=capture, store=store, now=lambda: NOW, load=load)

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
