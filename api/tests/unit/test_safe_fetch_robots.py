"""robots.txt in SafeFetcher (M3 acceptance 4; RFC 9309; 7.1: 100 percent)."""

from __future__ import annotations

import httpx
import pytest

from regwatch.capture.safe_fetch import FetchRefusedError, RobotsPolicy, SafeFetcher
from regwatch.capture.safe_fetch import robots as robots_module
from tests.support.fixture_server import FixtureServer
from tests.unit.test_safe_fetch_fetch import FIXTURES, UA, PinnedFetcher, at, dns


def mocked(status: int, body: bytes = b"") -> RobotsPolicy:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(status, stream=httpx.ByteStream(body))

    policy = RobotsPolicy(SafeFetcher(UA, resolver=dns, transport=httpx.MockTransport(handler)))
    policy.calls = calls  # type: ignore[attr-defined]
    return policy


async def test_rules_apply_and_are_cached() -> None:
    policy = mocked(200, b"User-agent: *\nDisallow: /private\nCrawl-delay: 7\n")
    assert await policy.check("https://example.org/public") == 7.0
    with pytest.raises(FetchRefusedError) as exc:
        await policy.check("https://example.org/private/doc")
    assert exc.value.reason == "robots"
    assert policy.calls == ["/robots.txt"]  # type: ignore[attr-defined]  # fetched once


async def test_a_group_for_regwatch_wins_over_the_default() -> None:
    policy = mocked(200, b"User-agent: *\nDisallow: /\n\nUser-agent: regwatch\nAllow: /\n")
    assert await policy.check("https://example.org/anything") is None


@pytest.mark.parametrize("status", [404, 403, 410])
async def test_a_4xx_robots_file_allows_everything(status: int) -> None:
    assert await mocked(status).check("https://example.org/x") is None


@pytest.mark.parametrize("status", [500, 503])
async def test_a_5xx_robots_file_disallows_everything(status: int) -> None:
    with pytest.raises(FetchRefusedError, match="could not be read"):
        await mocked(status).check("https://example.org/x")


async def test_an_unreachable_robots_file_disallows_everything() -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    policy = RobotsPolicy(SafeFetcher(UA, resolver=dns, transport=httpx.MockTransport(refused)))
    with pytest.raises(FetchRefusedError) as exc:
        await policy.check("https://example.org/x")
    assert exc.value.reason == "robots"


async def test_a_302_without_location_disallows() -> None:
    with pytest.raises(FetchRefusedError):
        await mocked(302).check("https://example.org/x")


async def test_an_override_needs_a_reason_and_skips_the_rules() -> None:
    policy = mocked(200, b"User-agent: *\nDisallow: /\n")
    assert (
        await policy.check("https://example.org/x", override_reason="Public data, owner OK") is None
    )
    assert policy.calls == []  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="needs a reason"):
        await policy.check("https://example.org/x", override_reason="   ")


async def test_the_cache_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(robots_module.time, "monotonic", lambda: clock[0])
    policy = mocked(404)
    await policy.check("https://example.org/x")
    assert policy.is_cached("https://example.org")
    clock[0] += robots_module.CACHE_SECONDS + 1
    assert not policy.is_cached("https://example.org")
    await policy.check("https://example.org/x")
    assert policy.calls == ["/robots.txt", "/robots.txt"]  # type: ignore[attr-defined]


async def test_the_cache_is_bounded_by_bytes_least_recent_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review finding 16: memory, not the number of sites, bounds the cache."""
    monkeypatch.setattr(robots_module, "CACHE_BUDGET", 2500)
    body = b"User-agent: *\nDisallow: /x\n" + b"# pad\n" * 160  # about 1 KB each
    policy = mocked(200, body)
    await policy.check("https://example.org/a")
    await policy.check("https://other.example/a")
    await policy.check("https://example.org/b")  # example.org is now the most recent
    await policy.check("https://v6.example/a")  # over budget: other.example goes first
    assert policy.is_cached("https://example.org") and policy.is_cached("https://v6.example")
    assert not policy.is_cached("https://other.example")
    assert policy._held <= 2500
    for i in range(10_001):  # entries without rules hold no bytes but still count
        policy._store(f"https://h{i}.example", robots_module._Rules(None, False, 1e18))
    assert len(policy._cache) <= 10_000


async def test_large_robots_files_are_parsed_up_to_500_kib() -> None:
    """Review finding 20: a file over 500 KiB is parsed in part, not refused outright."""
    body = b"User-agent: *\nDisallow: /private\n" + b"# padding line\n" * 50_000
    assert len(body) > robots_module.PARSE_BYTES
    policy = mocked(200, body)
    with pytest.raises(FetchRefusedError):
        await policy.check("https://example.org/private/x")
    assert robots_module.PARSE_BYTES - 15 < policy._held <= robots_module.PARSE_BYTES


async def test_a_rule_cut_by_the_parse_limit_is_dropped() -> None:
    """Review finding 24: ``Allow: /public-docs`` cut to ``Allow: /`` must not allow the site."""
    head, rule = b"User-agent: *\nDisallow: /\n", b"Allow: /public-docs\n"
    pad = b"#" * (robots_module.PARSE_BYTES - len(head) - len(b"Allow: /") - 1) + b"\n"
    body = head + pad + rule
    assert body[: robots_module.PARSE_BYTES].endswith(b"Allow: /")
    policy = mocked(200, body)
    with pytest.raises(FetchRefusedError):
        await policy.check("https://example.org/anything")


async def test_a_cr_only_file_is_cut_at_a_line_break_too() -> None:
    """Review finding 26: CR alone ends a line (RFC 9309)."""
    body = b"User-agent: *\rDisallow: /\r" + b"# padding line\r" * 40_000
    assert len(body) > robots_module.PARSE_BYTES and b"\n" not in body
    with pytest.raises(FetchRefusedError):
        await mocked(200, body).check("https://example.org/anything")


async def test_a_file_without_a_line_break_in_the_limit_has_no_rules() -> None:
    assert (
        await mocked(200, b"#" * (robots_module.PARSE_BYTES + 10)).check("https://example.org/x")
        is None
    )


async def test_one_robots_fetch_per_origin_at_a_time() -> None:
    """Review finding 25 (a): concurrent checks share one fetch and one ``before_fetch``; a
    failing ``before_fetch`` leaves the next check to try for itself."""
    import asyncio

    policy = mocked(200, b"User-agent: *\nDisallow: /private\n")
    slots: list[int] = []

    async def slot() -> None:
        slots.append(1)
        await asyncio.sleep(0)
        if len(slots) == 1:
            raise FetchRefusedError("rate-limited", "busy")

    results = await asyncio.gather(
        *[policy.check(f"https://example.org/{n}", before_fetch=slot) for n in range(5)],
        return_exceptions=True,
    )
    assert isinstance(results[0], FetchRefusedError) and results[1:] == [None] * 4
    assert len(slots) == 2 and policy.calls == ["/robots.txt"]  # type: ignore[attr-defined]
    assert policy._locks == {}


async def test_429_means_try_later() -> None:
    with pytest.raises(FetchRefusedError, match="could not be read"):
        await mocked(429).check("https://example.org/x")


async def test_robots_from_the_fixture_server(server: FixtureServer) -> None:
    """Acceptance 4 against the fixture server's robots.txt variants."""
    fetcher = PinnedFetcher({FIXTURES: "127.0.0.1"})
    control = httpx.AsyncClient()
    await control.put(server.url("/_control/robots/disallow"))
    with pytest.raises(FetchRefusedError) as exc:
        await RobotsPolicy(fetcher).check(at(server, "/pages/page_v1.html"))
    assert exc.value.reason == "robots"
    await control.put(server.url("/_control/robots/crawl_delay"))
    assert await RobotsPolicy(fetcher).check(at(server, "/pages/page_v1.html")) is not None
    await control.put(server.url("/_control/robots/allow"))
    assert await RobotsPolicy(fetcher).check(at(server, "/pages/page_v1.html")) is None
    await control.aclose()


@pytest.fixture(scope="module")
def server() -> FixtureServer:
    srv = FixtureServer().start()
    yield srv
    srv.stop()
