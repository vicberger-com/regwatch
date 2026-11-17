"""The EUR-Lex adapter: Cellar SPARQL (R-06 section 1; connectors/eurlex.py)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from regwatch.capture.connectors import eurlex
from regwatch.capture.connectors.api_feed import ApiFeedConnector, check_params
from regwatch.capture.connectors.base import (
    Candidate,
    ConnectorContext,
    ConnectorError,
    JobSettings,
)
from regwatch.capture.connectors.config import ApiFeedConfig, ExtractionRules
from regwatch.capture.safe_fetch import CaptureFetcher, FetchResult, MemoryRateLimiter, SafeFetcher

NOW = datetime(2026, 11, 17, tzinfo=UTC)
PARAMS: dict[str, Any] = {
    "method": "sparql",
    "sparql_endpoint": eurlex.ENDPOINT,
    "eurovoc_concepts": ["http://eurovoc.europa.eu/17280", "http://eurovoc.europa.eu/c_04ae3ba8"],
    "celex_sectors": ["3", "5"],
    "exclude_celex_regex": "^5\\d{4}M",
    "lookback_days": 14,
    "limit": 500,
    "content_language": "ENG",
}


def row(celex: str, day: str = "2026-11-10", title: str | None = "A <b>Regulation</b>") -> Any:
    cells = {
        "celex": {"type": "literal", "value": celex},
        "date": {"type": "literal", "value": day},
    }
    if title is not None:
        cells["title"] = {"type": "literal", "value": title}
    return cells


class Cellar:
    """A fake publications.europa.eu: SPARQL JSON, and content that redirects to plain http."""

    def __init__(
        self, rows: list[Any], headers: dict[str, str] | None = None, body: bytes | None = None
    ) -> None:
        self.rows, self.extra, self.body = rows, headers or {}, body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(404, stream=httpx.ByteStream(b""))
        if path == "/webapi/rdf/sparql":
            body = (
                self.body
                or json.dumps(
                    {"head": {"vars": ["celex"]}, "results": {"bindings": self.rows}}
                ).encode()
            )
            return httpx.Response(
                200,
                headers={"content-type": "application/sparql-results+json", **self.extra},
                stream=httpx.ByteStream(body),
            )
        if path.startswith("/resource/celex/"):  # 303 to plain http, as Cellar does (E-EU-9)
            return httpx.Response(
                303,
                headers={
                    "Location": "http://publications.europa.eu/resource/cellar/abc.0006.03/DOC_1"
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/xhtml+xml"},
            stream=httpx.ByteStream(b"<html>act</html>"),
        )


def context(site: Any) -> tuple[ConnectorContext, dict[str, bytes]]:
    async def public(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    async def no_wait(seconds: float) -> None:
        return None

    stored: dict[str, bytes] = {}

    async def store(key: str, body: bytes) -> None:
        stored[key] = body

    fetcher = SafeFetcher(
        "regwatch-test (+ops@example.org)", resolver=public, transport=httpx.MockTransport(site)
    )
    capture = CaptureFetcher(fetcher, MemoryRateLimiter(), rate_per_minute=6000, sleep=no_wait)
    return ConnectorContext(fetcher=capture, store=store, now=lambda: NOW), stored


def job(
    cursor: dict[str, Any] | None = None, last: datetime | None = None, **params: Any
) -> JobSettings:
    config = ApiFeedConfig(provider="eur_lex", params={**PARAMS, **params})  # type: ignore[arg-type]
    return JobSettings(
        source_id="s1",
        kind="api_feed",
        config=config,
        rules=ExtractionRules(),
        rate_per_minute=6000,
        cursor=cursor,
        last_success_at=last,
    )


async def discover(site: Any, notes: set[str] | None = None, **kw: Any) -> list[Candidate]:
    ctx, _ = context(site)
    if notes is not None:
        ctx.notes = notes
    return [c async for c in ApiFeedConnector().discover(job(**kw), ctx)]


def query_of(request: httpx.Request) -> str:
    return parse_qs(request.url.query.decode())["query"][0]


async def test_works_become_candidates() -> None:
    site = Cellar(
        [
            row("32026R2354"),
            row("52026M1234"),
            row("32023R2854R(07)", title=None),
            row("32026R2354"),
            row("not a celex"),
            row("32026L0001", day="soon"),
            row("32026L0002", day="2026-02-30"),  # matches the pattern, is no day (finding 2)
        ]
    )
    notes: set[str] = set()
    got = await discover(site, notes)
    assert [c.external_id for c in got] == ["32026R2354", "32023R2854R(07)", "32026L0001",
                                            "32026L0002"]  # fmt: skip
    first = got[0]
    assert first.url == "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32026R2354"
    assert first.title == "A Regulation" and first.language == "en"
    assert first.published_at == datetime(2026, 11, 10, tzinfo=UTC)
    assert first.hints["fetch"] == "https://publications.europa.eu/resource/celex/32026R2354"
    assert got[1].title is None and got[2].published_at is None and got[3].published_at is None
    assert notes == {"resumes"}  # fewer rows than the limit: not truncated
    sparql = [r for r in site.requests if r.url.path == "/webapi/rdf/sparql"]
    assert len(sparql) == 1 and sparql[0].headers["accept"] == "application/sparql-results+json"


async def test_a_full_page_is_truncated() -> None:
    notes: set[str] = set()
    await discover(Cellar([row(f"32026R{n:04d}") for n in range(3)]), notes, limit=3)
    assert notes == {"resumes", "truncated"}


def test_the_query_holds_only_checked_values() -> None:
    q = eurlex.sparql(PARAMS, "2026-11-01")
    assert (
        "VALUES ?concept { <http://eurovoc.europa.eu/17280> <http://eurovoc.europa.eu/c_04ae3ba8> }"
        in q
    )
    assert '"2026-11-01"^^<http://www.w3.org/2001/XMLSchema#date>' in q
    assert 'REGEX(STR(?celex), "^[35]")' in q and "ORDER BY ASC(?date)" in q
    assert q.rstrip().endswith("LIMIT 500") and "language/ENG>" in q


@pytest.mark.parametrize(
    ("cursor", "last", "expected"),
    [
        ({"publication_date": "2026-11-10"}, None, "2026-10-27"),
        (None, datetime(2026, 11, 1, tzinfo=UTC), "2026-10-18"),
        (None, None, "2026-10-04"),
        ({"publication_date": "nope"}, None, "2026-10-04"),
    ],
)
def test_the_window_starts_at_the_cursor(cursor: Any, last: Any, expected: str) -> None:
    """CP-14: the cursor, else the last success, else 30 days back; less the lookback."""
    assert eurlex.since(PARAMS, job(cursor=cursor, last=last), NOW) == expected


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (b"not json", "malformed-answer"),
        (b'{"results": "x"}', "malformed-answer"),
        (b"[]", "malformed-answer"),
    ],
)
async def test_bad_answers_are_refused(body: bytes, reason: str) -> None:
    with pytest.raises(ConnectorError) as exc:
        await discover(Cellar([], body=body))
    assert exc.value.reason == reason


async def test_a_firewall_challenge_is_a_block() -> None:
    with pytest.raises(ConnectorError) as exc:
        await discover(Cellar([], headers={"x-amzn-waf-action": "challenge"}))
    assert exc.value.reason == "blocked-by-provider"


async def test_content_is_fetched_over_https_with_the_language() -> None:
    """E-EU-9 and E-EU-13: Cellar's 303 to plain http is rewritten to https before fetching."""
    site = Cellar([])
    ctx, stored = context(site)
    doc = Candidate(
        url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32026R2354",
        external_id="32026R2354",
        hints={
            "provider": "eur_lex",
            "fetch": "https://publications.europa.eu/resource/celex/32026R2354",
        },
    )
    raw = await ApiFeedConnector().fetch(doc, job(), ctx)
    assert stored[raw.body_ref] == b"<html>act</html>" and raw.mime == "application/xhtml+xml"
    content = [r for r in site.requests if r.url.path != "/robots.txt"]
    assert [r.url.scheme for r in content] == ["https", "https"]  # the http hop was upgraded
    assert all(
        r.headers["accept"] == "application/xhtml+xml" and r.headers["accept-language"] == "eng"
        for r in content
    )
    assert raw.metadata["celex"] == "32026R2354"


async def test_a_hop_off_cellar_is_refused() -> None:
    class Elsewhere(Cellar):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.startswith("/resource/celex/"):
                return httpx.Response(302, headers={"Location": "https://eur-lex.europa.eu/x"})
            return super().__call__(request)

    ctx, stored = context(Elsewhere([]))
    doc = Candidate(
        url="https://eur-lex.europa.eu/x",
        hints={"provider": "eur_lex", "fetch": "https://publications.europa.eu/resource/celex/3"},
    )
    with pytest.raises(ConnectorError) as exc:
        await ApiFeedConnector().fetch(doc, job(), ctx)
    assert exc.value.reason == "off-host" and stored == {}
    bad = Candidate(
        url="https://eur-lex.europa.eu/x",
        hints={"provider": "eur_lex", "fetch": "http://10.0.0.5/x"},
    )
    with pytest.raises(ConnectorError) as exc:
        await ApiFeedConnector().fetch(bad, job(), ctx)
    assert exc.value.reason == "bad-link"


async def test_error_statuses_and_other_refusals() -> None:
    class Down(Cellar):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, stream=httpx.ByteStream(b"User-agent: *\nDisallow: /\n"))
            return httpx.Response(500, stream=httpx.ByteStream(b"no"))

    from regwatch.capture.safe_fetch import FetchRefusedError

    with pytest.raises(FetchRefusedError):  # robots.txt disallows it: the run's decision
        await discover(Down([]))

    class Failing(Cellar):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return super().__call__(request)
            return httpx.Response(503, stream=httpx.ByteStream(b"down"))

    with pytest.raises(ConnectorError) as exc:
        await discover(Failing([]))
    assert exc.value.reason == "http-status"


@pytest.mark.parametrize(("code", "two"), [("ENG", "en"), ("EST", "et"), ("SLK", "sk"),
                                           ("GLE", "ga")])  # fmt: skip
async def test_the_language_is_the_two_letter_code(code: str, two: str) -> None:
    """Review finding 9: not the first two letters of Cellar's code."""
    got = await discover(Cellar([row("32026R2354")]), content_language=code)
    assert got[0].language == two


@pytest.mark.parametrize("status", [404, 406])
async def test_a_document_cellar_does_not_have_is_unavailable(status: int) -> None:
    """Review finding 1: a skip for the run, not a failure; the query itself is still an error."""

    class Missing(Cellar):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.startswith("/resource/"):
                return httpx.Response(status, stream=httpx.ByteStream(b"no"))
            return super().__call__(request)

    ctx, stored = context(Missing([]))
    doc = Candidate(url="https://eur-lex.europa.eu/x",
                    hints={"provider": "eur_lex",
                           "fetch": "https://publications.europa.eu/resource/celex/3"})  # fmt: skip
    with pytest.raises(ConnectorError) as exc:
        await ApiFeedConnector().fetch(doc, job(), ctx)
    assert exc.value.reason == "unavailable" and stored == {}

    class QueryMissing(Cellar):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/webapi/rdf/sparql":
                return httpx.Response(status, stream=httpx.ByteStream(b"no"))
            return super().__call__(request)

    with pytest.raises(ConnectorError) as exc:
        await discover(QueryMissing([]))
    assert exc.value.reason == "http-status"


def test_the_starter_number_of_concepts_fits_in_one_query() -> None:
    """Review finding 5: R-06's starter has 12 concepts; the URL stays under the limit."""
    concepts = [f"http://eurovoc.europa.eu/c_{n:08x}" for n in range(12)]
    many = {**PARAMS, "eurovoc_concepts": concepts}
    check_params(ApiFeedConfig(provider="eur_lex", params=many))  # type: ignore[arg-type]
    assert len(eurlex.query_url(many, "2026-01-01")) <= eurlex.MAX_QUERY_URL


async def test_the_rate_is_capped_at_ten() -> None:
    calls: list[dict[str, Any]] = []

    class Recording:
        async def fetch(self, url: str, **kwargs: Any) -> FetchResult:
            calls.append(kwargs)
            body = json.dumps({"results": {"bindings": []}}).encode()
            return FetchResult(url, 200, {"content-type": "application/json"}, body)

    ctx = ConnectorContext(fetcher=Recording(), store=None, now=lambda: NOW)  # type: ignore[arg-type]
    settings = job()
    settings = JobSettings(**{**settings.__dict__, "rate_per_minute": 120})
    [c async for c in ApiFeedConnector().discover(settings, ctx)]
    assert calls[0]["rate_per_minute"] == 10 and calls[0]["allow_hop"] is eurlex._cellar_hop


@pytest.mark.parametrize(
    "params",
    [
        {"method": "rest"},
        {"sparql_endpoint": "https://evil.example/sparql"},
        {"content_url_template": "https://evil.example/{celex}"},
        {"display_url_template": "javascript:{celex}"},
        {"eurovoc_concepts": []},
        {"eurovoc_concepts": ["http://eurovoc.europa.eu/1> } INSERT {"]},
        {"eurovoc_concepts": ["https://evil.example/1"]},
        {"celex_sectors": ["3]"]},
        {"celex_sectors": ["٣"]},
        {"exclude_celex_regex": "(a)\\1"},
        {"exclude_celex_regex": "x" * 201},
        {"lookback_days": 91},
        {"limit": 0},
        {"limit": 5000},
        {"limit": True},
        {"content_language": 'eng"'},
        {"content_language": "XYZ"},
        {"eurovoc_concepts": [f"http://eurovoc.europa.eu/c_{n:08x}" for n in range(25)]},
        {"unknown": 1},
    ],
)
def test_settings_are_checked_when_saved(params: dict[str, Any]) -> None:
    with pytest.raises(ConnectorError) as exc:
        check_params(ApiFeedConfig(provider="eur_lex", params={**PARAMS, **params}))  # type: ignore[arg-type]
    assert exc.value.reason == "bad-config"
    check_params(ApiFeedConfig(provider="eur_lex", params=PARAMS))  # type: ignore[arg-type]


def test_without_an_exclusion_and_with_a_broken_hop() -> None:
    no_exclusion = {k: v for k, v in PARAMS.items() if k != "exclude_celex_regex"}
    check_params(ApiFeedConfig(provider="eur_lex", params=no_exclusion))  # type: ignore[arg-type]
    assert not eurlex._cellar_hop("https://[bad")
    assert not eurlex._cellar_hop("http://publications.europa.eu/x")  # never plain http
    assert eurlex._cellar_hop("https://publications.europa.eu/x")
