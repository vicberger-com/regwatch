"""Per-host rate limits and CaptureFetcher (M3 acceptance 5; 7.1: 100 percent)."""

from __future__ import annotations

import asyncio

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
from regwatch.capture.safe_fetch.fetch import FetchLimits
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
    assert await limiter.take("a.example", 6.0, 60) == 0.0
    assert await limiter.take("a.example", 6.0, 60) == 6.0
    assert await limiter.take("b.example", 6.0, 60) == 0.0  # another host is not held up
    await rate_module.wait_turn(limiter, "c.example", 6.0, 60, sleep=clock.sleep)
    assert clock.slept == []
    await rate_module.wait_turn(limiter, "c.example", 6.0, 60, sleep=clock.sleep)
    assert clock.slept == [6.0]
    for _ in range(11):
        await limiter.take("d.example", 6.0, 60)
    with pytest.raises(FetchRefusedError) as exc:
        await rate_module.wait_turn(limiter, "d.example", 6.0, 60, sleep=clock.sleep)
    assert exc.value.reason == "rate-limited"


async def test_refused_attempts_reserve_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding 14: 50 refusals leave the host's queue where it was."""
    clock = Clock()
    monkeypatch.setattr(rate_module.time, "monotonic", clock.monotonic)
    limiter = MemoryRateLimiter()
    for _ in range(11):
        await limiter.take("busy.example", 6.0, 60)  # queued up to 60 s ahead
    for _ in range(50):
        assert await limiter.take("busy.example", 6.0, 60) is None
    clock.now += 6
    assert await limiter.take("busy.example", 6.0, 60) == 60.0  # not 360 s


def test_huge_crawl_delays_and_rates_are_clamped() -> None:
    """Review finding 17 and 22: an hour at most, a millisecond at least."""
    assert rate_module.interval(10, crawl_delay=1e20) == rate_module.MAX_INTERVAL_S
    assert rate_module.interval(10**9) == 0.001


def allow_all_robots(fetcher: SafeFetcher) -> RobotsPolicy:
    policy = RobotsPolicy(fetcher)

    async def check(url: str, override_reason: str | None = None,
                    before_fetch: object = None) -> float | None:  # fmt: skip
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
    with pytest.raises(ValueError, match="at least 1"):
        await capture.fetch("https://example.org/a", rate_per_minute=0)  # 0 is not "default"
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
                return -1 if args[1] < 1000 else 2500

            return script

    from regwatch.capture.safe_fetch import ValkeyRateLimiter

    limiter = ValkeyRateLimiter(Client())
    assert await limiter.take("example.org", 6.0004, 120) == 2.5
    assert calls == [(["regwatch:rate:example.org"], [6001, 120000])]  # ceil, never shorter
    assert await limiter.take("example.org", 6.0, 0.5) is None
    await limiter.take("example.org", 1e20, 120)  # review finding 25 (b): clamped here too
    await limiter.take("example.org", 0.0, 120)
    assert [args[0] for _, args in calls[-2:]] == [3_600_000, 1]


async def test_the_memory_limiter_clamps_intervals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding 25 (b): an hour at most, a millisecond at least, NaN as an hour."""
    clock = Clock()
    monkeypatch.setattr(rate_module.time, "monotonic", clock.monotonic)
    limiter = MemoryRateLimiter()
    for host, seconds, spacing in (("a", 1e20, 3600.0), ("b", float("nan"), 3600.0),
                                   ("c", -5.0, 0.001)):  # fmt: skip
        await limiter.take(host, seconds, 10)
        assert limiter._free[host] == pytest.approx(clock.now + spacing)


async def test_a_private_redirect_is_reported_as_such(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding 19: the address check runs before robots and the rate slot."""
    clock = Clock()
    monkeypatch.setattr(rate_module.time, "monotonic", clock.monotonic)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404, stream=httpx.ByteStream(b""))
        return httpx.Response(302, headers={"Location": "http://evil.example/admin"})

    limiter = MemoryRateLimiter()
    fetcher = SafeFetcher(UA, resolver=dns, transport=httpx.MockTransport(handler))
    capture = CaptureFetcher(fetcher, limiter, sleep=clock.sleep)
    with pytest.raises(FetchRefusedError) as exc:
        await capture.fetch("https://example.org/", robots_override="reason")
    assert exc.value.reason == "private-address"
    assert "evil.example" not in limiter._free  # no slot was taken for the private host


async def test_a_slow_name_server_is_cut_off_before_the_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review finding 23: ``check_url``'s lookup has the hop's deadline too."""
    import time

    async def slow_dns(host: str, port: int) -> list[str]:
        await asyncio.sleep(1.0)
        return ["93.184.215.14"]

    fetcher = SafeFetcher(UA, FetchLimits(total_s=0.05), resolver=slow_dns,
                          transport=httpx.MockTransport(lambda r: httpx.Response(200)))  # fmt: skip
    capture = CaptureFetcher(fetcher, MemoryRateLimiter())
    started = time.monotonic()
    with pytest.raises(FetchRefusedError) as exc:
        await capture.fetch("https://example.org/", robots_override="reason")
    assert exc.value.reason == "timeout" and "DNS for example.org" in exc.value.detail
    assert time.monotonic() - started < 0.5


async def test_concurrent_first_requests_reserve_one_robots_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review finding 25 (a): 30 concurrent pages to an uncached site take 31 slots, not 60."""
    clock = Clock()
    monkeypatch.setattr(rate_module.time, "monotonic", clock.monotonic)
    paths: list[str] = []

    async def yielding_dns(host: str, port: int) -> list[str]:
        await asyncio.sleep(0)  # as real DNS does, so the coroutines interleave
        return await dns(host, port)

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        body = b"User-agent: *\nAllow: /\n" if request.url.path == "/robots.txt" else b"page"
        return httpx.Response(200, stream=httpx.ByteStream(body))

    limiter = MemoryRateLimiter()
    fetcher = SafeFetcher(UA, resolver=yielding_dns, transport=httpx.MockTransport(handler))
    capture = CaptureFetcher(fetcher, limiter, rate_per_minute=600, sleep=clock.sleep)
    await asyncio.gather(*[capture.fetch(f"https://example.org/p/{n}") for n in range(30)])
    assert paths.count("/robots.txt") == 1 and len(paths) == 31
    assert limiter._free["example.org"] == pytest.approx(1000.0 + 31 * 0.1)  # 31 slots taken
    assert capture.robots._locks == {}


async def test_robots_fetches_take_a_rate_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding 18: with a real robots.txt, 30 pages at 10 a minute stay at 10."""
    clock = Clock()
    monkeypatch.setattr(rate_module.time, "monotonic", clock.monotonic)
    times: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        times.append(clock.now)
        body = b"User-agent: *\nAllow: /\n" if request.url.path == "/robots.txt" else b"page"
        return httpx.Response(200, stream=httpx.ByteStream(body))

    fetcher = SafeFetcher(UA, resolver=dns, transport=httpx.MockTransport(handler))
    capture = CaptureFetcher(fetcher, MemoryRateLimiter(), rate_per_minute=10, sleep=clock.sleep)
    for n in range(30):
        await capture.fetch(f"https://example.org/p/{n}")
    assert len(times) == 31  # one robots.txt, 30 pages
    assert max(sum(1 for t in times if s <= t < s + 60) for s in times) <= 10


@pytest.mark.parametrize("wait", [float("nan"), -1.0, float("inf")])
async def test_the_longest_wait_must_be_finite(wait: float) -> None:
    """Review finding 27: both limiters refuse a NaN, negative or infinite ``max_wait_s``."""
    from regwatch.capture.safe_fetch import ValkeyRateLimiter

    class Client:
        def register_script(self, source: str):  # noqa: ANN201 - a stand-in for redis-py
            async def script(keys: list[str], args: list[int]) -> int:
                raise AssertionError("not reached")

            return script

    for limiter in (MemoryRateLimiter(), ValkeyRateLimiter(Client())):
        with pytest.raises(ValueError, match="longest wait"):
            await limiter.take("example.org", 1.0, wait)


async def test_refused_hosts_are_never_contacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """API feed review 5: a host in refuse_hosts is refused before robots.txt, the rate slot
    and the request, also when a redirect leads there."""
    clock = Clock()
    monkeypatch.setattr(rate_module.time, "monotonic", clock.monotonic)
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(str(request.headers.get("host")))
        if request.url.path == "/robots.txt":
            return httpx.Response(404, stream=httpx.ByteStream(b""))
        return httpx.Response(302, headers={"Location": "https://other.example/blocked"})

    limiter = MemoryRateLimiter()
    fetcher = SafeFetcher(UA, resolver=dns, transport=httpx.MockTransport(handler))
    capture = CaptureFetcher(fetcher, limiter, sleep=clock.sleep)
    with pytest.raises(FetchRefusedError) as exc:
        await capture.fetch("https://example.org/", refuse_hosts=frozenset({"other.example"}))
    assert exc.value.reason == "refused-host"
    assert "other.example" not in hosts and "other.example" not in limiter._free
