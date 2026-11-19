"""SafeFetcher.fetch: pinning, redirects, size and time caps (M3; 8.1; 7.1: 100 percent)."""

from __future__ import annotations

import asyncio
import gzip
import ipaddress
import os
import ssl
import subprocess
import tracemalloc
import zlib
from pathlib import Path

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
        return httpx.Response(
            200, stream=httpx.ByteStream(b"ok"), headers={"Content-Type": "text/html; charset=x"}
        )

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
        return httpx.Response(200, stream=httpx.ByteStream(b"done"))

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
    no_location = lambda r: httpx.Response(302, stream=httpx.ByteStream(b""))  # noqa: E731
    result = await fetcher(no_location).fetch("https://example.org/")
    assert result.status == 302 and result.body == b""


async def test_bodies_are_capped_by_header_and_by_stream() -> None:
    small = FetchLimits(max_bytes=10)
    declared = fetcher(
        lambda r: httpx.Response(
            200, headers={"Content-Length": "11"}, stream=httpx.ByteStream(b"x" * 11)
        )
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

    def reset(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("connection reset", request=request)

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("illegal header line", request=request)

    with pytest.raises(FetchRefusedError) as exc:  # any other transport error: connect
        await fetcher(reset).fetch("https://example.org/")
    assert exc.value.reason == "connect"
    with pytest.raises(FetchRefusedError) as exc:  # not valid HTTP: never retried (run review 9)
        await fetcher(broken).fetch("https://example.org/")
    assert exc.value.reason == "protocol"

    def dropped(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.",
                                        request=request)  # fmt: skip

    with pytest.raises(FetchRefusedError) as exc:  # dropped before answering: transient (R5)
        await fetcher(dropped).fetch("https://example.org/")
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


class PinnedFetcher(SafeFetcher):
    """Test only: listed made-up names reach 127.0.0.1; every other host is checked as usual,
    so redirects to ``127.0.0.1``, ``localhost`` or ``2130706433`` are still refused."""

    def __init__(self, pins: dict[str, str], tls: ssl.SSLContext | None = None, **kw: object):
        super().__init__(UA, **kw)  # type: ignore[arg-type]
        self.pins = pins
        self.tls = tls

    async def _resolve(self, target):  # noqa: ANN001, ANN202 - test override
        if target.host in self.pins:
            return [ipaddress.ip_address(self.pins[target.host])]
        return await super()._resolve(target)

    def _tls(self):  # noqa: ANN202 - test override
        return self.tls if self.tls is not None else super()._tls()


def local(**kw: object) -> SafeFetcher:
    """Only the made-up name ``fixtures.example`` reaches the fixture server on 127.0.0.1."""
    return PinnedFetcher({FIXTURES: "127.0.0.1"}, **kw)


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


async def test_hops_do_not_share_connections(server: FixtureServer) -> None:
    """Review finding 6: with the real transport, two hops to names on one address use two
    connections, so the second hop's TLS certificate is checked for its own name."""
    from urllib.parse import quote

    f = PinnedFetcher({FIXTURES: "127.0.0.1", "second.example": "127.0.0.1"})
    server.state.reset()
    target = quote(f"http://second.example:{server.port}/pages/page_v1.html", safe="")
    assert (await f.fetch(at(server, f"/redirect/to?url={target}"))).status == 200
    ports = [r.client_port for r in server.state.requests if r.listener == "app"]
    assert len(ports) == 2 and ports[0] != ports[1]


async def test_environment_proxies_are_ignored(
    server: FixtureServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.setenv(name, "http://10.255.255.1:3128")
    assert (await local().fetch(at(server, "/pages/page_v1.html"))).status == 200


async def test_the_redirect_cap_is_exactly_five(server: FixtureServer) -> None:
    assert len((await local().fetch(at(server, "/redirect/chain/4"))).redirects) == 5
    with pytest.raises(FetchRefusedError) as exc:
        await local().fetch(at(server, "/redirect/chain/5"))
    assert exc.value.reason == "redirects"


async def test_stacked_and_unknown_encodings_are_refused() -> None:
    def body(encoding: str, data: bytes):  # noqa: ANN202 - a handler factory
        return lambda r: httpx.Response(
            200, headers={"Content-Encoding": encoding}, stream=httpx.ByteStream(data)
        )

    twice = gzip.compress(gzip.compress(b"x"))
    with pytest.raises(FetchRefusedError) as exc:
        await fetcher(body("gzip, gzip", twice)).fetch("https://example.org/")
    assert exc.value.reason == "encoding"
    with pytest.raises(FetchRefusedError) as exc:
        await fetcher(body("br", b"\x0b")).fetch("https://example.org/")
    assert exc.value.reason == "encoding"
    with pytest.raises(FetchRefusedError) as exc:
        await fetcher(body("gzip", b"not gzip at all")).fetch("https://example.org/")
    assert exc.value.reason == "encoding"
    ok = await fetcher(body("deflate", zlib.compress(b"deflated"))).fetch("https://example.org/")
    assert ok.body == b"deflated"
    ok = await fetcher(body("identity", b"plain")).fetch("https://example.org/")
    assert ok.body == b"plain"


async def test_a_nested_gzip_bomb_never_grows_past_the_cap(server: FixtureServer) -> None:
    """Review finding 1: decompression is bounded, so memory stays near the 1 MB cap."""
    limits = FetchLimits(max_bytes=1024 * 1024)
    tracemalloc.start()
    try:
        with pytest.raises(FetchRefusedError) as exc:
            await local(limits=limits).fetch(at(server, "/bomb/gzip?mib=400&nested=1"))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert exc.value.reason == "encoding"  # nested: refused as a stacked encoding
    assert peak < 32 * 1024 * 1024, f"peak {peak} bytes"


async def test_a_single_layer_gzip_bomb_stays_within_the_cap(server: FixtureServer) -> None:
    """Review finding 10: the bounded decompression itself, not the stacked-encoding refusal."""
    limits = FetchLimits(max_bytes=1024 * 1024)
    tracemalloc.start()
    try:
        with pytest.raises(FetchRefusedError) as exc:
            await local(limits=limits).fetch(at(server, "/bomb/gzip?mib=400"))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert exc.value.reason == "too-large"
    assert peak < 32 * 1024 * 1024, f"peak {peak} bytes"


def streamed(encoding: str, *parts: bytes):  # noqa: ANN201 - a MockTransport handler
    async def body():  # noqa: ANN202
        for part in parts:
            yield part

    return lambda r: httpx.Response(200, headers={"Content-Encoding": encoding}, content=body())


async def test_data_after_a_gzip_body_is_refused_without_piling_up() -> None:
    """Review finding 8: 50 MiB of junk after a tiny gzip body is refused, memory stays small."""
    junk = (b"\x00" * 1024 for _ in range(50 * 1024))  # 50 MiB in 1 KiB chunks
    tracemalloc.start()
    try:
        with pytest.raises(FetchRefusedError) as exc:
            f = fetcher(streamed("gzip", gzip.compress(b"x"), *junk),
                        limits=FetchLimits(max_bytes=1024 * 1024))  # fmt: skip
            await f.fetch("https://example.org/")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert exc.value.reason == "encoding"
    assert peak < 16 * 1024 * 1024, f"peak {peak} bytes"


async def test_raw_bytes_count_against_the_cap_too() -> None:
    """Review finding 8: incompressible input cannot exceed the cap before decoding catches it."""
    big = gzip.compress(os.urandom(2 * 1024 * 1024))  # random data: barely compresses
    with pytest.raises(FetchRefusedError) as exc:
        f = fetcher(streamed("gzip", big), limits=FetchLimits(max_bytes=1024 * 1024))
        await f.fetch("https://example.org/")
    assert exc.value.reason == "too-large"


async def test_gzip_members_truncation_and_deflate_forms() -> None:
    """Review finding 9: several members decode; truncated streams and trailing data refuse;
    raw deflate is accepted; decoded bodies do not keep their encoding headers."""
    two = gzip.compress(b"first ") + gzip.compress(b"second")
    ok = await fetcher(streamed("gzip", two[:7], two[7:])).fetch("https://example.org/")
    assert ok.body == b"first second"
    assert "content-encoding" not in ok.headers and "content-length" not in ok.headers
    with pytest.raises(FetchRefusedError, match="ends early"):
        await fetcher(streamed("gzip", gzip.compress(b"hello world")[:-6])).fetch(
            "https://example.org/"
        )
    with pytest.raises(FetchRefusedError, match="after the end of the gzip"):
        await fetcher(streamed("gzip", gzip.compress(b"x") + b"Z")).fetch("https://example.org/")
    with pytest.raises(FetchRefusedError, match="after the end of the gzip"):
        await fetcher(streamed("gzip", gzip.compress(b"x") + b"junk")).fetch("https://example.org/")
    raw = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    deflated = raw.compress(b"raw deflate") + raw.flush()
    assert (
        await fetcher(streamed("deflate", deflated)).fetch("https://example.org/")
    ).body == b"raw deflate"
    with pytest.raises(FetchRefusedError, match="after the end of the deflate"):
        await fetcher(streamed("deflate", zlib.compress(b"x") + b"tail")).fetch(
            "https://example.org/"
        )
    assert (await fetcher(streamed("gzip")).fetch("https://example.org/")).body == b""
    with pytest.raises(FetchRefusedError, match="damaged compressed body"):
        await fetcher(streamed("gzip", b"\x1f\x8b\x08\x00garbage-not-deflate")).fetch(
            "https://example.org/"
        )


async def test_deflate_split_at_awkward_places() -> None:
    """Review finding 12: a one-byte first chunk, and data after a stream ending on a boundary."""
    body = zlib.compress(b"zlib-wrapped deflate")
    one = await fetcher(streamed("deflate", body[:1], body[1:])).fetch("https://example.org/")
    assert one.body == b"zlib-wrapped deflate"
    with pytest.raises(FetchRefusedError, match="after the end of the deflate"):
        await fetcher(streamed("deflate", body, zlib.compress(b"second"))).fetch(
            "https://example.org/"
        )
    with pytest.raises(FetchRefusedError, match="after the end of the deflate"):
        await fetcher(streamed("deflate", body, b"j")).fetch("https://example.org/")
    with pytest.raises(FetchRefusedError, match="ends early"):
        await fetcher(streamed("deflate", b"x")).fetch("https://example.org/")


async def test_a_tls_context_that_checks_less_is_refused() -> None:
    """Review finding 11: the test hook can add an authority, never switch the checks off."""
    lax = ssl.create_default_context()
    lax.check_hostname = False
    lax.verify_mode = ssl.CERT_NONE
    with pytest.raises(ValueError, match="never fetches without"):
        await PinnedFetcher({}, lax).fetch("https://example.org/")


async def test_a_slow_name_server_is_named_in_the_timeout() -> None:
    async def slow(host: str, port: int) -> list[str]:
        await asyncio.sleep(2)
        return ["93.184.215.14"]  # pragma: no cover - the deadline ends it first

    f = SafeFetcher(UA, FetchLimits(total_s=0.05), resolver=slow,
                    transport=httpx.MockTransport(lambda r: httpx.Response(200)))  # fmt: skip
    with pytest.raises(FetchRefusedError, match="DNS for example.org"):
        await f.fetch("https://example.org/")


async def test_dns_counts_against_the_deadline() -> None:
    """Review finding 3: a slow name server cannot hold the worker past the hop deadline."""

    async def slow(host: str, port: int) -> list[str]:
        await asyncio.sleep(2)
        return ["93.184.215.14"]  # pragma: no cover - the deadline ends it first

    f = SafeFetcher(UA, FetchLimits(total_s=0.05), resolver=slow,
                    transport=httpx.MockTransport(lambda r: httpx.Response(200)))  # fmt: skip
    with pytest.raises(FetchRefusedError) as exc:
        await f.fetch("https://example.org/")
    assert exc.value.reason == "timeout"


@pytest.mark.parametrize(
    ("path", "reason"),
    [("/raw/hang?seconds=5", "timeout"), ("/raw/slow-headers?interval_ms=200", "timeout"),
     ("/raw/garbage", "protocol"), ("/lie/short", "protocol")],
)  # fmt: skip
async def test_misbehaving_servers_are_refusals(server: FixtureServer, path: str,
                                                reason: str) -> None:  # fmt: skip
    """Review finding 6: the raw listener's broken answers end as refusals, not hangs."""
    f = PinnedFetcher({FIXTURES: "127.0.0.1"}, limits=FetchLimits(read_s=1, total_s=2))
    with pytest.raises(FetchRefusedError) as exc:
        await f.fetch(f"http://{FIXTURES}:{server.raw_port}{path}")
    assert exc.value.reason == reason


async def test_a_body_longer_than_declared_is_cut_at_the_declared_length(
    server: FixtureServer,
) -> None:
    """``/lie/long`` declares 10 bytes and sends 1 MiB: exactly 10 are read, the rest ignored."""
    f = PinnedFetcher({FIXTURES: "127.0.0.1"}, limits=FetchLimits(read_s=1, total_s=2))
    result = await f.fetch(f"http://{FIXTURES}:{server.raw_port}/lie/long")
    assert result.status == 200 and result.body == b"y" * 10


def _certificates(tmp: Path) -> tuple[Path, Path, Path]:
    """A test authority and a server certificate for ``good.example``, made with openssl."""
    run = lambda *a: subprocess.run(a, check=True, capture_output=True, cwd=tmp)  # noqa: E731, S603 - fixed openssl arguments
    run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj",
        "/CN=regwatch test CA", "-keyout", "ca.key", "-out", "ca.pem")  # fmt: skip
    run("openssl", "req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=good.example",
        "-keyout", "srv.key", "-out", "srv.csr")  # fmt: skip
    (tmp / "ext").write_text("subjectAltName=DNS:good.example\n")
    run("openssl", "x509", "-req", "-in", "srv.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
        "-CAcreateserial", "-days", "1", "-extfile", "ext", "-out", "srv.pem")  # fmt: skip
    return tmp / "ca.pem", tmp / "srv.pem", tmp / "srv.key"


async def test_a_certificate_for_another_name_is_refused(tmp_path: Path) -> None:
    """Review finding 5: TLS is checked against the requested name, not the pinned address."""
    ca, cert, key = _certificates(tmp_path)
    server_tls = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_tls.load_cert_chain(cert, key)

    async def answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError, ssl.SSLError):
            pass
        finally:
            writer.close()

    srv = await asyncio.start_server(answer, "127.0.0.1", 0, ssl=server_tls)
    port = srv.sockets[0].getsockname()[1]
    client_tls = ssl.create_default_context(cafile=str(ca))
    pins = {"good.example": "127.0.0.1", "bad.example": "127.0.0.1"}
    try:
        good = await PinnedFetcher(pins, client_tls).fetch(f"https://good.example:{port}/")
        assert good.status == 200 and good.body == b"ok"
        with pytest.raises(FetchRefusedError) as exc:
            await PinnedFetcher(pins, client_tls).fetch(f"https://bad.example:{port}/")
        assert exc.value.reason == "tls"  # the certificate names good.example only
        with pytest.raises(FetchRefusedError):  # and an unknown authority is refused too
            await PinnedFetcher(pins).fetch(f"https://good.example:{port}/")
    finally:
        srv.close()
        await srv.wait_closed()


def test_tls_failures_are_found_along_the_cause_chain() -> None:
    """Re-verification R5: httpx raises from httpcore's error, not from the ssl.SSLError."""
    from regwatch.capture.safe_fetch.fetch import _is_tls

    def chained(inner: BaseException, text: str = "connect failed") -> BaseException:
        middle = OSError("httpcore says no")
        middle.__cause__ = inner
        outer = httpx.ConnectError(text)
        outer.__context__ = middle
        return outer

    assert _is_tls(chained(ssl.SSLError(1, "unexpected eof")))
    assert _is_tls(chained(OSError("x"), "[SSL: WRONG_VERSION_NUMBER] wrong version number"))
    assert _is_tls(chained(OSError("sslv3 alert handshake failure")))
    assert not _is_tls(chained(ConnectionRefusedError(111, "Connection refused")))
    looped = httpx.ConnectError("refused")
    looped.__context__ = looped  # a cycle ends the walk
    assert not _is_tls(looped)


async def test_allowlisted_request_headers_are_sent_on_every_hop() -> None:
    """Accept and Accept-Language for Cellar (EUR-Lex); conditional headers for BL-91 (a)."""
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        if request.url.path == "/first":
            return httpx.Response(302, headers={"Location": "/second"})
        return httpx.Response(200, stream=httpx.ByteStream(b"ok"))

    got = await fetcher(handler).fetch("https://example.org/first", headers={
        "Accept": "application/xhtml+xml", "Accept-Language": "eng"})  # fmt: skip
    assert got.status == 200 and len(seen) == 2
    assert all(h["accept"] == "application/xhtml+xml" and h["accept-language"] == "eng"
               and h["host"] == "example.org" and h["user-agent"] == UA for h in seen)  # fmt: skip


@pytest.mark.parametrize(
    "headers",
    [{"Host": "evil.example"}, {"Cookie": "a=b"}, {"Authorization": "Bearer x"},
     {"User-Agent": "spoof"}, {"Accept": "a\r\nInjected: 1"}, {"Accept": "x" * 300},
     {"Accept": "é"}, {"Accept": "text/html", "accept": "application/json"}],
)  # fmt: skip
async def test_other_headers_and_bad_values_are_refused(headers: dict[str, str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nothing may be sent")

    with pytest.raises(ValueError):
        await fetcher(handler).fetch("https://example.org/", headers=headers)


async def test_http_redirects_are_upgraded_only_on_the_named_hosts() -> None:
    """R-06 E-EU-9 and E-EU-13: Cellar's redirect points at plain http; https works."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(f"{request.url.scheme}://{request.headers['host']}{request.url.path}")
        if request.url.path == "/resource":
            return httpx.Response(303, headers={"Location": "http://example.org/doc"})
        return httpx.Response(200, stream=httpx.ByteStream(b"ok"))

    await fetcher(handler).fetch("https://example.org/resource",
                                 upgrade_hosts=frozenset({"example.org"}))  # fmt: skip
    assert paths[-1] == "https://example.org/doc"


@pytest.mark.parametrize(
    ("url", "expected"),
    [("http://example.org/a?b=1", "https://example.org/a?b=1"),
     ("http://example.org:80/a", "https://example.org/a"),
     ("http://example.org:8080/a", "http://example.org:8080/a"),  # another port: unchanged
     ("http://other.example/a", "http://other.example/a"),  # another host: unchanged
     ("https://example.org/a", "https://example.org/a")],
)  # fmt: skip
def test_upgraded(url: str, expected: str) -> None:
    from regwatch.capture.safe_fetch.fetch import upgraded

    assert upgraded(url, frozenset({"example.org"})) == expected


async def test_a_post_body_is_sent_once_and_never_redirected() -> None:
    """M4 translation: POST with a body, at most MAX_CONTENT bytes, no redirect ever."""
    import httpx

    from regwatch.capture.safe_fetch.fetch import MAX_CONTENT

    seen: list[tuple[str, bytes, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.read(), request.headers.get("content-type", "")))
        if request.url.path == "/moved":
            return httpx.Response(307, headers={"location": "https://other.example/x"})
        return httpx.Response(200, stream=httpx.ByteStream(b"{}"))

    fetcher = PinnedFetcher({FIXTURES: "127.0.0.1"}, transport=httpx.MockTransport(handler))
    got = await fetcher.fetch(f"http://{FIXTURES}/translate", method="POST", content=b'{"q":1}',
                              headers={"content-type": "application/json"})  # fmt: skip
    assert got.status == 200 and seen == [("POST", b'{"q":1}', "application/json")]
    with pytest.raises(FetchRefusedError) as exc:
        await fetcher.fetch(f"http://{FIXTURES}/moved", method="POST", content=b"k")
    assert exc.value.reason == "redirects" and len(seen) == 2  # other.example never asked
    with pytest.raises(ValueError):
        await fetcher.fetch(f"http://{FIXTURES}/x", content=b"body on a GET")
    with pytest.raises(ValueError):
        await fetcher.fetch(f"http://{FIXTURES}/x", method="POST", content=b"x" * (MAX_CONTENT + 1))
    with pytest.raises(ValueError):
        await fetcher.fetch(f"http://{FIXTURES}/x", headers={"authorization": "Bearer k"})
