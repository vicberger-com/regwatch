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


async def test_the_cache_expires_and_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(robots_module.time, "monotonic", lambda: clock[0])
    policy = mocked(404)
    await policy.check("https://example.org/x")
    clock[0] += robots_module.CACHE_SECONDS + 1
    await policy.check("https://example.org/x")
    assert policy.calls == ["/robots.txt", "/robots.txt"]  # type: ignore[attr-defined]
    policy._cache.update({f"https://h{i}.example": policy._cache["https://example.org"]
                          for i in range(10_001)})  # fmt: skip
    clock[0] += robots_module.CACHE_SECONDS + 1
    await policy.check("https://example.org/x")
    assert len(policy._cache) == 1


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
