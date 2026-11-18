"""The search query connector (ADR-0010; R-07 section 4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from regwatch.capture import execution
from regwatch.capture.connectors import search_query
from regwatch.capture.connectors.base import ConnectorContext, ConnectorError, JobSettings
from regwatch.capture.connectors.config import ExtractionRules, SearchQueryConfig
from regwatch.capture.models import CaptureJob, Source
from regwatch.capture.safe_fetch import CaptureFetcher, MemoryRateLimiter, SafeFetcher
from regwatch.core.internal import InternalError

NOW = datetime(2026, 11, 18, tzinfo=UTC)


def result(url: str, title: str = "A <b>title</b>", engines: tuple[str, ...] = ("duckduckgo",),
           content: str = "A snippet") -> dict[str, Any]:  # fmt: skip
    return {"url": url, "title": title, "content": content, "engines": list(engines)}


class Searx:
    """Stands in for the internal client: answers per page, or raises."""

    def __init__(self, pages: list[Any] | None = None, error: Exception | None = None) -> None:
        self.pages, self.error = pages or [], error
        self.asked: list[dict[str, str]] = []

    async def get_json(self, path: str, params: dict[str, str]) -> Any:
        assert path == "/search"
        self.asked.append(params)
        if self.error is not None:
            raise self.error
        page = int(params["pageno"]) - 1
        return self.pages[page] if page < len(self.pages) else {"results": []}


def site(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(404, stream=httpx.ByteStream(b""))
    page = b"<title>Page</title><main><p>" + b"word " * 50 + b"</p></main>"
    return httpx.Response(200, headers={"content-type": "text/html"},
                          stream=httpx.ByteStream(page))  # fmt: skip


def context(searx: Searx | None, official: frozenset[str] = frozenset(),
            paced: list[float] | None = None, handler: Any = None) -> ConnectorContext:  # fmt: skip
    async def public(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    async def store(key: str, body: bytes) -> None:
        return None

    async def pace(key: str, interval_s: float) -> None:
        assert key == "search"
        if paced is not None:
            paced.append(interval_s)

    fetcher = SafeFetcher("regwatch-test (+ops@example.org)", resolver=public,
                          transport=httpx.MockTransport(handler or site))  # fmt: skip
    capture = CaptureFetcher(fetcher, MemoryRateLimiter(), rate_per_minute=6000)
    return ConnectorContext(fetcher=capture, store=store, now=lambda: NOW, search=searx,
                            official_hosts=official, pace=pace)  # fmt: skip


def job(**config: Any) -> JobSettings:
    return JobSettings(source_id="s", kind="search_query",
                       config=SearchQueryConfig.model_validate({"query": "AI act", **config}),
                       rules=ExtractionRules(), rate_per_minute=6000,
                       robots_override="An override that must never apply")  # fmt: skip


async def found(searx: Searx, ctx: ConnectorContext | None = None, **config: Any) -> list[Any]:
    ctx = ctx or context(searx)
    return [c async for c in search_query.SearchQueryConnector().discover(job(**config), ctx)]


async def test_results_become_checked_candidates() -> None:
    searx = Searx([{"results": [
        result("https://reg.example/act"), result("https://news.example/story"),
        result("https://reg.example/act"), result("javascript:alert(1)"),
        result("http://10.0.0.5/x"), {"no": "url"}]}])  # fmt: skip
    paced: list[float] = []
    got = await found(searx, context(searx, frozenset({"reg.example"}), paced))
    assert [c.url for c in got] == ["https://reg.example/act", "https://news.example/story"]
    assert [c.hints["credibility"] for c in got] == ["official", "secondary"]
    assert got[0].title == "A title" and got[0].summary == "A snippet"
    assert len(paced) == 1 and 60 <= paced[0] <= 90  # one paced query (R-07)
    assert searx.asked[0] == {"q": "AI act", "format": "json", "safesearch": "0",
                              "language": "all", "time_range": "month", "pageno": "1"}  # fmt: skip


async def test_site_filters_languages_and_official_only() -> None:
    searx = Searx([{"results": [result("https://reg.example/a"), result("https://sub.reg.example/b"),
                                result("https://other.example/c")]}])  # fmt: skip
    got = await found(searx, site_filters=["reg.example"], languages=["de"], time_range="any")
    assert [c.url for c in got] == ["https://reg.example/a", "https://sub.reg.example/b"]
    assert searx.asked[0]["q"] == "AI act (site:reg.example)"
    assert (searx.asked[0]["language"], searx.asked[0]["time_range"]) == ("de", "")
    searx = Searx(
        [{"results": [result("https://reg.example/a"), result("https://other.example/c")]}]
    )
    only = await found(
        searx, context(searx, frozenset({"reg.example"})), official_domains_only=True
    )
    assert [c.url for c in only] == ["https://reg.example/a"]


async def test_pages_up_to_max_results() -> None:
    page = {"results": [result(f"https://reg.example/{n}") for n in range(10)]}
    page2 = {"results": [result(f"https://reg.example/x{n}") for n in range(10)]}
    searx = Searx([page, page2, page])
    paced: list[float] = []
    got = await found(searx, context(searx, paced=paced), max_results=15)
    assert len(got) == 15 and len(searx.asked) == 2 and len(paced) == 2


@pytest.mark.parametrize(
    ("answer", "reason"),
    [({"results": [], "unresponsive_engines": [["duckduckgo", "CAPTCHA"], ["brave", "timeout"]]},
      "search-unavailable"),
     ({"results": [result("https://reg.example/a", engines=("bing",))]}, "search-unavailable"),
     ({"no": "results"}, "malformed-answer"), (["not", "a", "dict"], "malformed-answer")],
)  # fmt: skip
async def test_unusable_answers_fail_the_run(answer: Any, reason: str) -> None:
    with pytest.raises(ConnectorError) as exc:
        await found(Searx([answer]))
    assert exc.value.reason == reason
    if reason == "search-unavailable" and answer["results"] == []:
        assert "duckduckgo, brave" in exc.value.detail


async def test_engine_names_are_checked_before_they_reach_the_message() -> None:
    answer = {"results": [], "unresponsive_engines": [["<script>", "x"], "qwant", 5]}
    with pytest.raises(ConnectorError) as exc:
        await found(Searx([answer]))
    assert "script" not in exc.value.detail and "qwant" in exc.value.detail


async def test_without_search_or_official_sources() -> None:
    with pytest.raises(ConnectorError) as exc:
        await found(Searx(), context(None))
    assert exc.value.reason == "search-disabled"
    with pytest.raises(ConnectorError) as exc:
        await found(Searx(), official_domains_only=True)
    assert exc.value.reason == "bad-config"
    with pytest.raises(ConnectorError) as exc:
        await found(Searx(error=InternalError("sidecar-timeout", "slow")))
    assert exc.value.reason == "sidecar-timeout"


@pytest.mark.parametrize(
    "config",
    [{"query": "   "}, {"query": "a\x00b"}, {"site_filters": ["reg.example/"]},
     {"site_filters": ["*.reg.example"]}, {"site_filters": ["a.example"] * 21},
     {"languages": ["english"]}, {"languages": ["en"] * 6}],
)  # fmt: skip
def test_settings_are_checked_when_saved(config: dict[str, Any]) -> None:
    with pytest.raises(ConnectorError):
        search_query.check(SearchQueryConfig.model_validate({"query": "AI act", **config}))
    search_query.check(SearchQueryConfig.model_validate({"query": "AI act",
                                                         "site_filters": ["reg.example"],
                                                         "languages": ["de-AT"]}))  # fmt: skip


async def test_a_run_fetches_each_result_without_any_override() -> None:
    """Through run_connector: pages fetched by SafeFetcher, read in the child, robots obeyed."""
    searx = Searx([{"results": [result("https://reg.example/a")]}])

    async def make(settings: JobSettings) -> ConnectorContext:
        return context(searx, frozenset({"reg.example"}))

    source = Source(id=uuid.UUID(int=3), kind="search_query", robots_policy="override",
                    config={"query": "AI act"},
                    override_reason="saved before it was refused")  # fmt: skip
    row = CaptureJob(max_items_per_run=10, rate_limit_per_minute=6000, render_js=False,
                     extraction_rules={})  # fmt: skip
    assert execution.job_settings(row, source).robots_override is None
    got = await execution.run_connector(uuid.uuid4(), row, source, make)
    assert (got.status, got.items_new) == ("success", 1)
    doc = got.documents[0]
    assert doc.metadata["credibility"] == "official" and doc.metadata["search"] is True
    assert doc.text and doc.text.startswith("word")
    assert search_query.SearchQueryConnector().health(job()).status == "unknown"


async def test_filtered_pages_run_out_at_the_page_limit() -> None:
    other = {"results": [result(f"https://other.example/{n}") for n in range(10)]}
    searx = Searx([other, other])
    got = await found(searx, site_filters=["reg.example"], max_results=20)
    assert got == [] and len(searx.asked) == 2


def redirecting(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(404, stream=httpx.ByteStream(b""))
    if request.url.path == "/exit":
        return httpx.Response(302, headers={"location": "https://evil.example/fake-rule"})
    return site(request)


async def test_redirects_are_held_to_the_filters_and_credibility_to_the_end() -> None:
    """Search review finding 2."""
    from regwatch.capture.connectors.base import Candidate

    ctx = context(Searx(), frozenset({"reg.example"}), handler=redirecting)
    candidate = Candidate(url="https://reg.example/exit", hints={"kind": "url"})
    connector = search_query.SearchQueryConnector()
    with pytest.raises(ConnectorError) as exc:  # the filter refuses the hop before contact
        await connector.fetch(candidate, job(site_filters=["reg.example"]), ctx)
    assert exc.value.reason == "off-filter"
    doc = await connector.fetch(candidate, job(), ctx)  # no filter: fetched, but not official
    assert doc.final_url == "https://evil.example/fake-rule"
    assert doc.metadata["credibility"] == "secondary"


@pytest.mark.parametrize(
    ("url", "credibility"),
    [("https://reg.example/a", "official"), ("https://reg.example:8443/a", None),
     ("http://reg.example:443/a", None), ("https://lookalike-reg.example/a", "secondary")],
)  # fmt: skip
async def test_only_default_ports_on_official_hosts_are_official(
    url: str, credibility: str | None
) -> None:
    """Finding 5: another port is not the official host's (and is not taken at all)."""
    searx = Searx([{"results": [result(url)]}])
    got = await found(searx, context(searx, frozenset({"reg.example"})))
    assert [c.hints["credibility"] for c in got] == ([credibility] if credibility else [])


@pytest.mark.parametrize("engines", [5, "bing", None, [5, None]])
async def test_engines_of_the_wrong_type_are_not_usable_engines(engines: Any) -> None:
    """Finding 6: never a TypeError, and a string is not read letter by letter."""
    answer = {"results": [{"url": "https://reg.example/a", "engines": engines}]}
    with pytest.raises(ConnectorError) as exc:
        await found(Searx([answer]))
    assert exc.value.reason == "search-unavailable"


def test_a_url_that_does_not_parse_has_no_host() -> None:
    assert search_query._host("ftp://reg.example/") is None


async def test_a_busy_search_slot_is_a_skip_not_a_failure() -> None:
    """Search re-verification R1: a refused pace is FetchRefusedError("rate-limited")."""
    from regwatch.capture.safe_fetch import FetchRefusedError

    searx = Searx([{"results": [result("https://reg.example/a")]}])
    ctx = context(searx)

    async def busy(key: str, interval_s: float) -> None:
        raise FetchRefusedError("rate-limited", "busy")

    ctx.pace = busy

    async def make(settings: JobSettings) -> ConnectorContext:
        return ctx

    source = Source(id=uuid.UUID(int=4), kind="search_query", robots_policy="respect",
                    config={"query": "AI act"}, override_reason=None)  # fmt: skip
    row = CaptureJob(max_items_per_run=10, rate_limit_per_minute=6000, render_js=False,
                     extraction_rules={})  # fmt: skip
    got = await execution.run_connector(uuid.uuid4(), row, source, make)
    assert (got.status, got.error_class) == ("skipped", "rate-limited")
