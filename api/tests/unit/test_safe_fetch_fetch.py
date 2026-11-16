"""SafeFetcher.fetch: pinning, redirects, size and time caps (M3; 8.1; 7.1: 100 percent)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from regwatch.capture.safe_fetch import FetchLimits, FetchRefusedError, SafeFetcher
from tests.support.fixture_server import FixtureServer

UA = "regwatch/0.1 (+https://regwatch.example; ops@example.org)"
HOSTS = {"example.org": "93.184.215.14", "other.example": "93.184.215.15",
         "evil.example": "10.0.0.5", "v6.example": "2606:4700::1"}  # fmt: skip


async def dns(host: str, port: int) -> list[str]:
    return [HOSTS[host]]


def fetcher(handler, **kw) -> SafeFetcher:  # noqa: ANN001 - a MockTransport handler
    return SafeFetcher(UA, resolver=dns, transport=httpx.MockTransport(handler), **kw)


async def test_the_connection_is_pinned_to_the_checked_address() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="ok", headers={"Content-Type": "text/html; charset=x"})

    result = await fetcher(handler).fetch("https://example.org/a?b=1")
    req = seen[0]
    assert str(req.url) == "https://93.184.215.14/a?b=1"
    assert req.headers["host"] == "example.org" and req.headers["user-agent"] == UA
    assert req.extensions["sni_hostname"] == "example.org"  # TLS checks the name, not the IP
    assert result.status == 200 and result.body == b"ok" and result.mime == "text/html"
    await fetcher(handler).fetch("http://v6.example:8080/")
    assert (
        str(seen[1].url) == "http://[2606:4700::1]:8080/"
        and "sni_hostname" not in seen[1].extensions
    )
    assert seen[1].headers["host"] == "v6.example:8080"


async def test_redirects_are_followed_and_each_hop_is_checked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(303, headers={"Location": "https://other.example/next"})
        if request.url.path == "/next":
            assert request.method == "GET"  # 303 turns the method into GET
            return httpx.Response(302, headers={"Location": "/final"})
        return httpx.Response(200, text="done")

    result = await fetcher(handler).fetch("https://example.org/start", method="POST")
    assert result.url == "https://other.example/final"
    assert result.redirects == ["https://other.example/next", "https://other.example/final"]


async def test_a_redirect_to_a_private_host_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://evil.example/internal"})

    with pytest.raises(FetchRefusedError) as exc:
        await fetcher(handler).fetch("https://example.org/")
    assert exc.value.reason == "private-address"


async def test_redirects_are_capped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        n = int(request.url.path.strip("/") or 0)
        return httpx.Response(302, headers={"Location": f"/{n + 1}"})

    with pytest.raises(FetchRefusedError) as exc:
        await fetcher(handler, limits=FetchLimits(max_redirects=5)).fetch("https://example.org/0")
    assert exc.value.reason == "redirects"


async def test_a_redirect_without_location_is_the_answer() -> None:
    result = await fetcher(lambda r: httpx.Response(302)).fetch("https://example.org/")
    assert result.status == 302 and result.body == b""


async def test_bodies_are_capped_by_header_and_by_stream() -> None:
    small = FetchLimits(max_bytes=10)
    declared = fetcher(
        lambda r: httpx.Response(200, headers={"Content-Length": "11"}, content=b"x" * 11)
    )
    with pytest.raises(FetchRefusedError, match="larger than 10 bytes"):
        await SafeFetcher(UA, small, resolver=dns, transport=declared._transport).fetch(
            "https://example.org/"
        )

    def chunked(request: httpx.Request) -> httpx.Response:
        async def body():  # noqa: ANN202 - an async byte stream
            for _ in range(3):
                yield b"x" * 5

        return httpx.Response(200, content=body())

    with pytest.raises(FetchRefusedError) as exc:
        await fetcher(chunked, limits=small).fetch("https://example.org/")
    assert exc.value.reason == "too-large"


async def test_timeouts_and_connection_errors_are_refusals() -> None:
    def read_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(FetchRefusedError) as exc:
        await fetcher(read_timeout).fetch("https://example.org/")
    assert exc.value.reason == "timeout"
    with pytest.raises(FetchRefusedError) as exc:
        await fetcher(refused).fetch("https://example.org/")
    assert exc.value.reason == "connect"

    async def stalls(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200)  # pragma: no cover - the deadline ends it first

    with pytest.raises(FetchRefusedError, match="longer than 0.05 s"):
        await fetcher(stalls, limits=FetchLimits(total_s=0.05)).fetch("https://example.org/")


async def test_dns_failures_and_private_first_hosts_are_refused() -> None:
    with pytest.raises(FetchRefusedError) as exc:
        await fetcher(lambda r: httpx.Response(200)).fetch("https://evil.example/")
    assert exc.value.reason == "private-address"
    with pytest.raises(FetchRefusedError) as exc:
        await fetcher(lambda r: httpx.Response(200)).fetch("ftp://example.org/")
    assert exc.value.reason == "scheme"


@pytest.fixture(scope="module")
def server() -> FixtureServer:
    srv = FixtureServer().start()
    yield srv
    srv.stop()


FIXTURES = "fixtures.example"


def local(**kw: object) -> SafeFetcher:
    """Only the made-up name ``fixtures.example`` reaches the fixture server on 127.0.0.1."""
    return SafeFetcher(UA, pinned_hosts={FIXTURES: "127.0.0.1"}, **kw)  # type: ignore[arg-type]


def at(server: FixtureServer, path: str) -> str:
    return f"http://{FIXTURES}:{server.port}{path}"


async def test_against_the_fixture_server(server: FixtureServer) -> None:
    ok = await local().fetch(at(server, "/redirect/chain/3"))
    assert ok.status == 200 and len(ok.redirects) == 4  # chain/3, 2, 1, 0, then the page
    with pytest.raises(FetchRefusedError) as exc:
        await local().fetch(at(server, "/redirect/loop/a"))
    assert exc.value.reason == "redirects"


@pytest.mark.parametrize(
    "name",
    ["loopback", "localhost", "metadata", "metadata_ipv6", "ipv6_loopback", "ipv4_mapped_ipv6",
     "unspecified", "decimal_ip", "hex_ip", "private_10", "private_192", "private_172",
     "link_local", "file_scheme", "gopher_scheme"],
)  # fmt: skip
async def test_every_private_redirect_target_is_refused(server: FixtureServer, name: str) -> None:
    """The fixture contract: each target in private_redirect.json is refused by SafeFetcher."""
    with pytest.raises(FetchRefusedError) as exc:
        await local().fetch(at(server, f"/redirect/private/{name}"))
    assert exc.value.reason in {"private-address", "scheme"}


async def test_gzip_bombs_and_slow_bodies_from_the_fixture_server(server: FixtureServer) -> None:
    limits = FetchLimits(max_bytes=1024 * 1024, read_s=2, total_s=3)
    with pytest.raises(FetchRefusedError) as exc:
        await local(limits=limits).fetch(at(server, "/bomb/gzip?mib=50"))
    assert exc.value.reason == "too-large"  # stopped after 1 MB of decoded bytes
    with pytest.raises(FetchRefusedError) as exc:
        await local(limits=limits).fetch(at(server, "/slow/body?chunks=100&interval_ms=500"))
    assert exc.value.reason == "timeout"  # a trickling body hits the per-hop deadline
    with pytest.raises(FetchRefusedError) as exc:
        await local(limits=limits).fetch(at(server, "/size/5000000?chunked=1"))
    assert exc.value.reason == "too-large"


async def test_the_default_fetcher_refuses_the_local_fixture_server(server: FixtureServer) -> None:
    with pytest.raises(FetchRefusedError) as exc:
        await SafeFetcher(UA).fetch(server.url("/health"))
    assert exc.value.reason == "private-address"


async def test_hops_do_not_share_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    """No kept-alive connections, so each hop's TLS certificate is checked for its own name."""
    from regwatch.capture.safe_fetch import fetch as fetch_module

    made: list[dict[str, object]] = []
    real = httpx.AsyncClient

    def client(**kw: object) -> httpx.AsyncClient:
        made.append(kw)
        return real(**kw)  # type: ignore[arg-type]

    monkeypatch.setattr(fetch_module.httpx, "AsyncClient", client)
    await fetcher(lambda r: httpx.Response(200)).fetch("https://example.org/")
    limits = made[0]["limits"]
    assert isinstance(limits, httpx.Limits) and limits.max_keepalive_connections == 0
    assert made[0]["trust_env"] is False and made[0]["follow_redirects"] is False
