"""Per-host rate limits and CaptureFetcher (M3 acceptance 5; 7.1: 100 percent)."""

from __future__ import annotations

import httpx
import pytest

from regwatch.capture.safe_fetch import (
    CaptureFetcher,
    FetchRefusedError,
    MemoryRateLimiter,
    RobotsPolicy,
    SafeFetcher,
)
from regwatch.capture.safe_fetch import rate as rate_module
from tests.unit.test_safe_fetch_fetch import UA, dns


class Clock:
    """A fake clock: ``sleep`` moves it forward instead of waiting."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_interval_takes_the_slower_of_rate_and_crawl_delay() -> None:
    assert rate_module.interval(30) == 2.0
    assert rate_module.interval(30, crawl_delay=10) == 10.0
    assert rate_module.interval(60, crawl_delay=0.5) == 1.0
    with pytest.raises(ValueError, match="at least 1"):
        rate_module.interval(0)


async def test_slots_are_spaced_and_long_waits_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    monkeypatch.setattr(rate_module.time, "monotonic", clock.monotonic)
    limiter = MemoryRateLimiter()
    assert await limiter.take("a.example", 6.0) == 0.0
    assert await limiter.take("a.example", 6.0) == 6.0
    assert await limiter.take("b.example", 6.0) == 0.0  # another host is not held up
    await rate_module.wait_turn(limiter, "c.example", 6.0, 60, sleep=clock.sleep)
    assert clock.slept == []
    await rate_module.wait_turn(limiter, "c.example", 6.0, 60, sleep=clock.sleep)
    assert clock.slept == [6.0]
    for _ in range(20):
        await limiter.take("d.example", 6.0)
    with pytest.raises(FetchRefusedError) as exc:
        await rate_module.wait_turn(limiter, "d.example", 6.0, 60, sleep=clock.sleep)
    assert exc.value.reason == "rate-limited"


def allow_all_robots(fetcher: SafeFetcher) -> RobotsPolicy:
    policy = RobotsPolicy(fetcher)

    async def check(url: str, override_reason: str | None = None) -> float | None:
        return None

    policy.check = check  # type: ignore[method-assign]
    return policy


async def test_a_200_page_crawl_keeps_to_10_per_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    """Acceptance 5: 200 requests to one host, at most 10 in any minute."""
    clock = Clock()
    monkeypatch.setattr(rate_module.time, "monotonic", clock.monotonic)
    times: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        times.append(clock.now)
        return httpx.Response(200, stream=httpx.ByteStream(b"page"))

    fetcher = SafeFetcher(UA, resolver=dns, transport=httpx.MockTransport(handler))
    capture = CaptureFetcher(fetcher, MemoryRateLimiter(), robots=allow_all_robots(fetcher),
                             rate_per_minute=10, sleep=clock.sleep)  # fmt: skip
    for n in range(200):
        await capture.fetch(f"https://example.org/page/{n}")
    assert len(times) == 200
    assert all(b - a >= 6.0 for a, b in zip(times, times[1:], strict=False))
    worst = max(sum(1 for t in times if start <= t < start + 60) for start in times)
    assert worst <= 10


async def test_robots_and_rates_apply_to_every_redirect_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    monkeypatch.setattr(rate_module.time, "monotonic", clock.monotonic)

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        if request.url.path == "/robots.txt":
            body = b"User-agent: *\nDisallow: /blocked\n" if host == "other.example" else b""
            return httpx.Response(200, stream=httpx.ByteStream(body))
        if host == "example.org":
            return httpx.Response(302, headers={"Location": "https://other.example/blocked"})
        return httpx.Response(200, stream=httpx.ByteStream(b"never"))  # pragma: no cover

    fetcher = SafeFetcher(UA, resolver=dns, transport=httpx.MockTransport(handler))
    capture = CaptureFetcher(fetcher, MemoryRateLimiter(), sleep=clock.sleep)
    with pytest.raises(FetchRefusedError) as exc:
        await capture.fetch("https://example.org/start")
    assert exc.value.reason == "robots"  # the redirect target's robots.txt was checked


async def test_an_override_skips_robots_but_not_the_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    monkeypatch.setattr(rate_module.time, "monotonic", clock.monotonic)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, stream=httpx.ByteStream(b"User-agent: *\nDisallow: /\n"))
        return httpx.Response(200, stream=httpx.ByteStream(b"ok"))

    fetcher = SafeFetcher(UA, resolver=dns, transport=httpx.MockTransport(handler))
    capture = CaptureFetcher(fetcher, MemoryRateLimiter(), sleep=clock.sleep, rate_per_minute=60)
    for _ in range(3):
        got = await capture.fetch("https://example.org/doc", robots_override="Owner approved")
        assert got.body == b"ok"
    assert clock.slept == [1.0, 1.0]
    with pytest.raises(FetchRefusedError):
        await capture.fetch("https://example.org/doc")  # without the override: robots applies


async def test_the_default_sleep_is_asyncio(monkeypatch: pytest.MonkeyPatch) -> None:
    fetcher = SafeFetcher(UA, resolver=dns, transport=httpx.MockTransport(
        lambda r: httpx.Response(404 if r.url.path == "/robots.txt" else 200,
                                 stream=httpx.ByteStream(b""))))  # fmt: skip
    capture = CaptureFetcher(fetcher, MemoryRateLimiter(), rate_per_minute=6000)
    await capture.fetch("https://example.org/a")
    await capture.fetch("https://example.org/b")  # waits 10 ms through asyncio.sleep


async def test_the_valkey_limiter_runs_one_script_per_slot() -> None:
    """The Lua script itself runs in tests/integration/test_valkey_rate.py against Valkey."""
    calls: list[tuple[list[str], list[int]]] = []

    class Client:
        def register_script(self, source: str):  # noqa: ANN201 - a stand-in for redis-py
            assert "redis.call('TIME')" in source

            async def script(keys: list[str], args: list[int]) -> int:
                calls.append((keys, args))
                return 2500

            return script

    from regwatch.capture.safe_fetch import ValkeyRateLimiter

    assert await ValkeyRateLimiter(Client()).take("example.org", 6.0) == 2.5
    assert calls == [(["regwatch:rate:example.org"], [6000])]
