"""Fixture server behaviour (issue #12, REQ-25): start-up time and every route group."""

from __future__ import annotations

import gzip
import time
import zlib

import httpx
import pytest

from tests.support.fixture_server import FixtureServer, gzip_bomb


def test_starts_in_under_two_seconds() -> None:
    start = time.perf_counter()
    server = FixtureServer().start()
    try:
        elapsed = time.perf_counter() - start
        assert httpx.get(server.url("/health")).text == "ok"
    finally:
        server.stop()
    assert elapsed < 2.0


@pytest.fixture
def client() -> httpx.Client:
    return httpx.Client(timeout=10, follow_redirects=False)


def test_serves_fixture_files_with_types(
    fixture_server: FixtureServer, client: httpx.Client
) -> None:
    rss = client.get(fixture_server.url("/feeds/valid_rss.xml"))
    assert rss.status_code == 200 and rss.headers["content-type"].startswith("application/rss+xml")
    latin = client.get(fixture_server.url("/feeds/encoding_latin1.xml"))
    assert "ISO-8859-1" in latin.headers["content-type"]
    assert client.get(fixture_server.url("/corpus/001.json")).json()["language"] == "en"
    assert client.get(fixture_server.url("/pages/missing.html")).status_code == 404
    assert client.get(fixture_server.url("/pages/..%2Fcorpus%2F001.json")).status_code == 404


def test_generated_feeds_are_served(fixture_server: FixtureServer, client: httpx.Client) -> None:
    assert len(client.get(fixture_server.url("/feeds/huge_10mb.xml")).content) >= 10 * 1024 * 1024
    assert b"<!ENTITY lol9" in client.get(fixture_server.url("/feeds/entity_expansion.xml")).content


def test_status_delay_and_override(fixture_server: FixtureServer, client: httpx.Client) -> None:
    r = client.get(fixture_server.url("/status/429?retry_after=7"))
    assert r.status_code == 429 and r.headers["retry-after"] == "7"
    assert client.get(fixture_server.url("/pages/page_v1.html?status=500")).status_code == 500
    start = time.perf_counter()
    assert client.get(fixture_server.url("/delay/300")).status_code == 200
    assert time.perf_counter() - start >= 0.3
    with pytest.raises(httpx.ReadTimeout):
        client.get(fixture_server.url("/pages/page_v1.html?delay_ms=2000"), timeout=0.3)


def test_redirect_chain_loop_and_open_redirect(
    fixture_server: FixtureServer, client: httpx.Client
) -> None:
    r = client.get(fixture_server.url("/redirect/chain/5"), follow_redirects=True)
    assert r.status_code == 200 and len(r.history) == 6
    assert {h.status_code for h in r.history} <= {301, 302, 303, 307, 308}
    limited = httpx.Client(follow_redirects=True, max_redirects=5)
    with pytest.raises(httpx.TooManyRedirects):
        limited.get(fixture_server.url("/redirect/chain/6"))
    with pytest.raises(httpx.TooManyRedirects):
        limited.get(fixture_server.url("/redirect/loop/a"))
    r = client.get(fixture_server.url("/redirect/to?url=http://10.0.0.1/&code=307"))
    assert r.status_code == 307 and r.headers["location"] == "http://10.0.0.1/"


@pytest.mark.parametrize(
    ("name", "host"),
    [
        ("loopback", "127.0.0.1"),
        ("metadata", "169.254.169.254"),
        ("ipv6_loopback", "[::1]"),
        ("decimal_ip", "2130706433"),
        ("file_scheme", "file:"),
    ],
)
def test_private_redirects(
    fixture_server: FixtureServer, client: httpx.Client, name: str, host: str
) -> None:
    r = client.get(fixture_server.url(f"/redirect/private/{name}"))
    assert r.status_code == 302 and host in r.headers["location"]
    assert "{port}" not in r.headers["location"]


def test_slow_body_and_size(fixture_server: FixtureServer, client: httpx.Client) -> None:
    start = time.perf_counter()
    r = client.get(fixture_server.url("/slow/body?chunks=3&interval_ms=150&chunk_bytes=10"))
    assert r.content == b"s" * 30 and time.perf_counter() - start >= 0.3
    sized = client.get(fixture_server.url("/size/123456"))
    assert len(sized.content) == 123456 and sized.headers["content-length"] == "123456"
    chunked = client.get(fixture_server.url("/size/1000?chunked=1"))
    assert "content-length" not in chunked.headers and len(chunked.content) == 1000


def test_gzip_bomb_is_small_on_the_wire(
    fixture_server: FixtureServer, client: httpx.Client
) -> None:
    with client.stream("GET", fixture_server.url("/bomb/gzip?mib=32")) as r:
        assert r.headers["content-encoding"] == "gzip"
        wire = b"".join(r.iter_raw())
    assert len(wire) < 64 * 1024
    assert gzip.decompress(wire) == b"\0" * (32 * 1024 * 1024)  # also checks CRC and size
    bounded = zlib.decompressobj(31).decompress(wire, 1024 * 1024)
    assert len(bounded) == 1024 * 1024, "a capped decoder stops at its limit"
    with client.stream("GET", fixture_server.url("/pages/zip_bomb.html.gz?mib=8")) as r:
        assert r.headers["content-type"].startswith("text/html")
        assert len(gzip.decompress(b"".join(r.iter_raw()))) == 8 * 1024 * 1024
    nested = client.get(fixture_server.url("/bomb/gzip?mib=4&nested=1"))
    assert nested.headers["content-encoding"] == "gzip, gzip"
    assert len(nested.content) == 4 * 1024 * 1024


def test_gzip_bomb_default_size_without_downloading() -> None:
    assert (
        len(b"".join(gzip_bomb(1024))) < 1.1 * 1024 * 1024
    )  # 1 GiB inflated, about 1 MiB on the wire


def test_robots_variants_and_sequence(fixture_server: FixtureServer, client: httpx.Client) -> None:
    assert "Allow: /" in client.get(fixture_server.url("/robots.txt")).text
    assert client.put(fixture_server.url("/_control/robots/disallow")).status_code == 200
    assert "Disallow: /" in client.get(fixture_server.url("/robots.txt")).text
    assert client.put(fixture_server.url("/_control/robots/nope")).status_code == 404
    bodies = [client.get(fixture_server.url("/sequence/change_detection")).text for _ in range(5)]
    assert bodies[0] == bodies[1] != bodies[2] != bodies[3] == bodies[4]
    assert "Consultation closed" in bodies[3]
    client.post(fixture_server.url("/_control/reset"))
    assert client.get(fixture_server.url("/sequence/change_detection")).text == bodies[0]
    assert "Allow: /" in client.get(fixture_server.url("/robots.txt")).text


def test_listing_items_and_request_log(fixture_server: FixtureServer, client: httpx.Client) -> None:
    assert "Notice 07" in client.get(fixture_server.url("/pages/listing/item-07.html")).text
    assert client.get(fixture_server.url("/pages/listing/item-31.html")).status_code == 404
    client.get(fixture_server.url("/health"), headers={"User-Agent": "regwatch-test/1"})
    last = fixture_server.state.requests[-1]
    assert last.path == "/health" and last.headers["user-agent"] == "regwatch-test/1"


def test_raw_listener_lies_and_hangs(fixture_server: FixtureServer) -> None:
    def get(path: str, timeout: float = 10) -> httpx.Response:
        with httpx.Client(timeout=timeout) as fresh:  # a broken connection must not be pooled
            return fresh.get(fixture_server.raw(path))

    with pytest.raises(httpx.RemoteProtocolError):
        get("/lie/short")
    assert len(get("/lie/content-length?declared=5&actual=50").content) == 5
    with pytest.raises(httpx.ReadTimeout):
        get("/raw/hang?seconds=5", timeout=0.3)
    with pytest.raises(httpx.ReadTimeout):
        get("/raw/slow-headers?interval_ms=1000", timeout=0.3)
    with pytest.raises(httpx.RemoteProtocolError):
        get("/raw/garbage")
    assert get("/nothing").status_code == 404
    assert any(r.listener == "raw" for r in fixture_server.state.requests)
