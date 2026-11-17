"""The API feed connector's Federal Register adapter (R-06 section 2; M3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest

from regwatch.capture.connectors.api_feed import (
    FEDERAL_REGISTER,
    MAX_JSON_BYTES,
    MAX_JSON_DEPTH,
    MAX_PAGES,
    ApiFeedConnector,
    parse_json,
    query,
)
from regwatch.capture.connectors.base import (
    REGISTRY,
    Candidate,
    ConnectorContext,
    ConnectorError,
    JobSettings,
)
from regwatch.capture.connectors.config import ApiFeedConfig, ExtractionRules
from regwatch.capture.safe_fetch import CaptureFetcher, MemoryRateLimiter, SafeFetcher

NOW = datetime(2026, 11, 17, 12, tzinfo=UTC)
UA = "regwatch-test (+ops@example.org)"


def doc(n: int, **extra: Any) -> dict[str, Any]:
    return {"document_number": f"2026-{n:05d}", "title": f"Rule <b>{n}</b>", "type": "Rule",
            "abstract": f"About &amp; {n}", "publication_date": "2026-11-16",
            "html_url": f"https://www.federalregister.gov/documents/2026/11/16/{n}",
            "agencies": [{"name": "Cybersecurity Agency"}], **extra}  # fmt: skip


class FR:
    """A fake federalregister.gov: robots.txt allows all, documents.json answers as set."""

    def __init__(self, pages: list[Any], status: int = 200,
                 headers: dict[str, str] | None = None) -> None:  # fmt: skip
        self.pages, self.status, self.headers = pages, status, headers or {}
        self.requests: list[httpx.URL] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, stream=httpx.ByteStream(b"User-agent: *\nAllow: /\n"))
        page = int(dict(parse_qsl(request.url.query.decode())).get("page", "1"))
        body = self.pages[min(page, len(self.pages)) - 1]
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        return httpx.Response(self.status, headers={"content-type": "application/json",
                                                    **self.headers},
                              stream=httpx.ByteStream(raw))  # fmt: skip


def page(docs: list[dict[str, Any]], following: str | None = None) -> dict[str, Any]:
    return {"count": len(docs), "results": docs, **({"next_page_url": following} if following
                                                     else {})}  # fmt: skip


def context(site: FR) -> tuple[ConnectorContext, dict[str, bytes]]:
    async def public(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    async def no_wait(seconds: float) -> None:
        return None

    stored: dict[str, bytes] = {}

    async def store(key: str, body: bytes) -> None:
        stored[key] = body

    fetcher = SafeFetcher(UA, resolver=public, transport=httpx.MockTransport(site))
    capture = CaptureFetcher(fetcher, MemoryRateLimiter(), rate_per_minute=6000, sleep=no_wait)
    return ConnectorContext(fetcher=capture, store=store, now=lambda: NOW), stored


def job(params: dict[str, Any] | None = None, provider: str = "federal_register",
        last_success_at: datetime | None = None) -> JobSettings:  # fmt: skip
    config = ApiFeedConfig(provider=provider, params=params or {"per_page": "100"})  # type: ignore[arg-type]
    return JobSettings(source_id="s1", kind="api_feed", config=config, rules=ExtractionRules(),
                       rate_per_minute=6000, last_success_at=last_success_at)  # fmt: skip


async def discover(site: FR, notes: set[str] | None = None, **kw: Any) -> list[Candidate]:
    ctx, _ = context(site)
    if notes is not None:
        ctx.notes = notes
    return [c async for c in ApiFeedConnector().discover(job(**kw), ctx)]


async def test_pages_are_followed_by_next_page_url_only() -> None:
    nxt = f"{FEDERAL_REGISTER}?page=2&per_page=100"
    site = FR([page([doc(1), doc(2)], nxt), page([doc(3), doc(2)])])
    got = await discover(site)
    assert [c.external_id for c in got] == ["2026-00001", "2026-00002", "2026-00003"]
    first = got[0]
    assert first.title == "Rule 1" and first.summary == "About & 1"  # plain text
    assert first.published_at == datetime(2026, 11, 16, tzinfo=UTC)
    assert first.hints["record"]["agencies"] == ["Cybersecurity Agency"]
    assert [u.path for u in site.requests] == ["/robots.txt", "/api/v1/documents.json",
                                               "/api/v1/documents.json"]  # fmt: skip
    assert REGISTRY["api_feed"].kind == "api_feed"


async def test_paging_is_capped_and_reported_as_truncated() -> None:
    """Review findings 2 and 12: each page names a new next page; the cap stops paging and the
    connector says it stopped early, so the run is partial, not success."""
    pages = [page([doc(n)], f"{FEDERAL_REGISTER}?page={n + 1}") for n in range(1, MAX_PAGES + 5)]
    site = FR(pages)
    notes: set[str] = set()
    got = await discover(site, notes)
    assert len(site.requests) == 1 + MAX_PAGES and len(got) == MAX_PAGES
    assert notes == {"truncated"}
    done: set[str] = set()
    await discover(FR([page([doc(1)])]), done)
    assert done == set()  # the last page offered no next page: not truncated


@pytest.mark.parametrize(
    "following",
    [f"{FEDERAL_REGISTER}?per_page=100",  # the same URL as the first page
     "https://www.federalregister.gov/api/v1/other.json?page=2"],  # another path
)  # fmt: skip
async def test_a_next_page_must_be_new_and_the_same_endpoint(following: str) -> None:
    """Review finding 9."""
    with pytest.raises(ConnectorError) as exc:
        await discover(FR([page([doc(1)], following), page([doc(2)], following)]))
    assert exc.value.reason == "malformed-answer"


async def test_a_next_page_on_another_host_is_refused() -> None:
    site = FR([page([doc(1)], "https://evil.example/api/v1/documents.json?page=2")])
    with pytest.raises(ConnectorError) as exc:
        await discover(site)
    assert exc.value.reason == "malformed-answer"


@pytest.mark.parametrize(
    ("status", "headers"),
    [(202, {"x-amzn-waf-action": "challenge"}), (403, {"x-amzn-waf-action": "block"}),
     (405, {"X-Amzn-Waf-Action": "captcha"})],
)  # fmt: skip
async def test_a_firewall_block_is_a_typed_failure(status: int, headers: dict[str, str]) -> None:
    """R-06 note 2: blocked_by_provider at any status, never content, never worked around."""
    with pytest.raises(ConnectorError) as exc:
        await discover(FR([b"<html>captcha</html>"], status=status, headers=headers))
    assert exc.value.reason == "blocked-by-provider"


async def test_a_redirect_to_the_unblock_page_is_a_block() -> None:
    """Review finding 5: the block page and its robots.txt are never contacted."""
    hosts: list[str] = []

    class Redirecting(FR):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            # SafeFetcher connects to the checked address; the name is in Host.
            hosts.append(str(request.headers.get("host")))
            if request.url.path == "/robots.txt":
                return httpx.Response(404, stream=httpx.ByteStream(b""))
            return httpx.Response(302, headers={"Location": "https://unblock.federalregister.gov/"})

    with pytest.raises(ConnectorError) as exc:
        await discover(Redirecting([]))
    assert exc.value.reason == "blocked-by-provider"
    assert hosts and "unblock.federalregister.gov" not in hosts


@pytest.mark.parametrize(
    ("body", "status", "reason"),
    [(b"not json", 200, "malformed-answer"), (b'{"results": "nope"}', 200, "malformed-answer"),
     (b"[]", 200, "malformed-answer"), (b"{}", 500, "http-status"),
     (b"[" * (MAX_JSON_DEPTH + 2) + b"]" * (MAX_JSON_DEPTH + 2), 200, "malformed-answer"),
     (b'{"results": [], "pad": "' + b"x" * (MAX_JSON_BYTES + 1) + b'"}', 200, "too-large")],
)  # fmt: skip
async def test_bad_answers_are_refused(body: bytes, status: int, reason: str) -> None:
    with pytest.raises(ConnectorError) as exc:
        await discover(FR([body], status=status))
    assert exc.value.reason == reason


async def test_unsafe_links_and_odd_records_are_dropped() -> None:
    """Review finding 4: links are checked and kept to the provider's hosts, in the candidate
    and in the stored record."""
    records: list[Any] = [
        doc(1, html_url="javascript:alert(1)"), doc(2, html_url="http://10.0.0.5/x"),
        doc(4, html_url="https://evil.example/x"), "not a record",
        doc(3, agencies="nope", publication_date="soon",
            pdf_url="http://169.254.169.254/latest/meta-data"),
    ]  # fmt: skip
    got = await discover(FR([page(records)]))
    assert [c.external_id for c in got] == ["2026-00003"]
    record = got[0].hints["record"]
    assert got[0].published_at is None and "agencies" not in record and "pdf_url" not in record
    ok = await discover(FR([page([doc(5, pdf_url="https://www.govinfo.gov/content/x.pdf")])]))
    assert ok[0].hints["record"]["pdf_url"] == "https://www.govinfo.gov/content/x.pdf"


async def test_one_document_under_two_links_is_one_candidate() -> None:
    """Review finding 10, and long ids are kept as a hash."""
    twin = doc(1, html_url="https://www.federalregister.gov/d/2026-00001")
    long_id = doc(9, document_number="X" * 600)
    got = await discover(FR([page([doc(1), twin, long_id])]))
    assert len(got) == 2 and (got[1].external_id or "").startswith("sha256:")


def test_the_query_fills_the_last_success_placeholder_and_checks_types() -> None:
    since = {"conditions[publication_date][gte]": "{last_success_date - 3 days}",
             "conditions[type][]": ["RULE", "NOTICE"], "per_page": "100"}  # fmt: skip
    q = dict(parse_qsl(query(since, datetime(2026, 11, 10, tzinfo=UTC), NOW)))
    assert q["conditions[publication_date][gte]"] == "2026-11-06"  # US Eastern date
    first = dict(parse_qsl(query(since, None, NOW)))  # first run: 30 days back, less 3
    assert first["conditions[publication_date][gte]"] == "2026-10-15"
    assert parse_qsl(query({"t": ["A", "B"]}, None, NOW)) == [("t", "A"), ("t", "B")]
    numbers = dict(parse_qsl(query({"per_page": 100, "flag": True}, None, NOW)))
    assert numbers == {"per_page": "100", "flag": "true"}  # as R-06 writes them (finding 7)
    bad_params: list[dict[str, Any]] = [
        {"n": {"a": 1}}, {"x": "y" * 3000}, {f"k{i}": "v" for i in range(60)},
        {"l": [{"x": 1}]}, {"page": "2"}, {"l": ["v"] * 60},
        {"d": "{last_success_date minus a week}"}, {f"k{i}": "v" * 100 for i in range(20)},
        {"k" * 300: "v"},
    ]  # fmt: skip
    for bad in bad_params:
        with pytest.raises(ConnectorError) as exc:
            query(bad, None, NOW)
        assert exc.value.reason == "bad-config"


def test_json_depth_is_bounded() -> None:
    assert parse_json(b'{"a": [1, {"b": 2}]}') == {"a": [1, {"b": 2}]}
    with pytest.raises(ConnectorError):
        parse_json(b'{"a":' * 40 + b"1" + b"}" * 40)


@pytest.mark.parametrize("provider", ["eur_lex", "legislation_gov_uk", "generic_json"])
async def test_other_providers_say_they_are_not_built_yet(provider: str) -> None:
    with pytest.raises(ConnectorError) as exc:
        await discover(FR([]), provider=provider)
    assert exc.value.reason == "not-implemented"


async def test_the_document_is_the_api_record() -> None:
    """Full text is blocked (E-FR-14): the stored body is the record, as JSON."""
    ctx, stored = context(FR([]))
    candidate = Candidate(url="https://www.federalregister.gov/documents/1",
                          summary="About", hints={"record": {"title": "Rule 1"}})  # fmt: skip
    raw = await ApiFeedConnector().fetch(candidate, job(), ctx)
    assert raw.mime == "application/json" and raw.text == "About"
    assert json.loads(stored[raw.body_ref]) == {"title": "Rule 1"}
    assert ApiFeedConnector().health(job()).status == "unknown"


async def test_a_job_for_another_kind_is_refused() -> None:
    from regwatch.capture.connectors.config import ManualConfig

    ctx, _ = context(FR([]))
    other = JobSettings(source_id="s", kind="manual", config=ManualConfig(),
                        rules=ExtractionRules())  # fmt: skip
    with pytest.raises(TypeError):
        [c async for c in ApiFeedConnector().discover(other, ctx)]


def test_the_endpoint_is_fixed() -> None:
    assert urlsplit(FEDERAL_REGISTER).hostname == "www.federalregister.gov"


def test_records_keep_only_known_text_fields() -> None:
    from regwatch.capture.connectors.api_feed import _published, _record

    record = _record({"title": "<script>x</script>", "abstract": "Kept", "secret": "dropped",
                      "type": 7})  # fmt: skip
    assert record == {"abstract": "Kept"}  # empty after cleaning, unknown, or not text: left out
    assert _published(20261116) is None and _published("2026-11-16T09:00") is not None


@pytest.mark.parametrize(
    ("config", "ok"),
    [({"provider": "federal_register", "params": {"conditions[publication_date][gte]":
       "{last_success_date - 3 days}", "per_page": 100}}, True),
     ({"provider": "federal_register", "params": {"per_page": 100}}, False),  # no date bound
     ({"provider": "federal_register", "params": {"page": "2",
       "conditions[publication_date][gte]": "2026-01-01"}}, False),
     ({"provider": "federal_register", "endpoint_url": "https://x.example/",
       "params": {"conditions[publication_date][gte]": "2026-01-01"}}, False),
     ({"provider": "generic_json", "endpoint_url": "https://x.example/"}, True)],
)  # fmt: skip
def test_settings_are_checked_when_saved(config: dict[str, Any], ok: bool) -> None:
    """Review findings 7 and 8."""
    from regwatch.capture.connectors.api_feed import check_params

    parsed = ApiFeedConfig.model_validate(config)
    if ok:
        check_params(parsed)
    else:
        with pytest.raises(ConnectorError):
            check_params(parsed)


async def test_other_refusals_pass_through() -> None:
    """robots.txt disallowing the API is the run's robots decision, not a block."""
    from regwatch.capture.safe_fetch import FetchRefusedError

    class Disallowed(FR):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, stream=httpx.ByteStream(b"User-agent: *\nDisallow: /\n"))
            return super().__call__(request)

    with pytest.raises(FetchRefusedError) as exc:
        await discover(Disallowed([page([doc(1)])]))
    assert exc.value.reason == "robots"
