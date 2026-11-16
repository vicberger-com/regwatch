"""SafeFetcher address and URL policy (M3 acceptance 3; 8.1 SSRF; 7.1: 100 percent)."""

from __future__ import annotations

import pytest

from regwatch.capture.safe_fetch import (
    FetchRefusedError,
    Target,
    check_address,
    parse_target,
    resolve,
    validate_source_url,
)


def resolver(*answers: str):  # noqa: ANN201 - a test resolver
    async def fake(host: str, port: int) -> list[str]:
        return list(answers)

    return fake


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1", "10.0.0.1", "172.16.5.4", "192.168.1.1", "169.254.169.254", "100.64.0.1",
        "0.0.0.0",  # noqa: S104 - an address to refuse, not to bind
        "224.0.0.1", "255.255.255.255", "198.18.0.1", "192.0.2.1",
        "::1", "::", "fe80::1", "fe80::1%eth0", "fc00::1", "ff02::1", "2001:db8::1",
        "::ffff:127.0.0.1", "::ffff:169.254.169.254", "2002:7f00:1::1", "64:ff9b::a9fe:a9fe",
        "2001:0:4136:e378:8000:63bf:3fff:fdd2",
    ],
)  # fmt: skip
def test_private_and_special_addresses_are_refused(address: str) -> None:
    with pytest.raises(FetchRefusedError) as exc:
        check_address(address)
    assert exc.value.reason == "private-address"


@pytest.mark.parametrize("address", ["93.184.215.14", "2606:4700:4700::1111", "8.8.8.8"])
def test_public_addresses_pass(address: str) -> None:
    assert str(check_address(address)) == address


def test_a_non_address_is_refused() -> None:
    with pytest.raises(FetchRefusedError, match="not an IP address"):
        check_address("example.org")


def test_parse_target_normalises() -> None:
    t = parse_target("HTTPS://Exämple.ORG./path?q=1#frag")
    assert t == Target("https", "xn--exmple-cua.org", 443, "/path?q=1")
    assert t.origin == "https://xn--exmple-cua.org"
    assert parse_target("http://[2606:4700::1]:8080").origin == "http://[2606:4700::1]:8080"
    assert parse_target("http://example.org").path == "/"


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("ftp://example.org/x", "scheme"),
        ("file:///etc/passwd", "scheme"),
        ("gopher://example.org", "scheme"),
        ("javascript:alert(1)", "scheme"),
        ("https://user:pw@example.org/", "userinfo"),
        ("https://user@example.org/", "userinfo"),
        ("https:///nohost", "url"),
        ("https://exa mple.org/", "url"),
        ("https://example.org/\r\nHost: evil", "url"),
        ("http://example.org:99999/", "url"),
        ("https://" + "a" * 2050 + ".org/", "url"),
        ("https://\udcff.org/", "url"),
    ],
)
def test_bad_urls_are_refused(url: str, reason: str) -> None:
    with pytest.raises(FetchRefusedError) as exc:
        parse_target(url)
    assert exc.value.reason == reason


async def test_resolve_refuses_any_private_answer() -> None:
    target = parse_target("https://example.org/")
    assert [str(a) for a in await resolve(target, resolver("93.184.215.14"))] == ["93.184.215.14"]
    with pytest.raises(FetchRefusedError, match="not a public address"):
        await resolve(target, resolver("93.184.215.14", "10.0.0.1"))  # mixed: rebinding setup
    with pytest.raises(FetchRefusedError, match="no addresses"):
        await resolve(target, resolver())


async def test_resolve_reports_dns_failures() -> None:
    async def fails(host: str, port: int) -> list[str]:
        raise OSError("name not known")

    with pytest.raises(FetchRefusedError) as exc:
        await resolve(parse_target("https://example.invalid/"), fails)
    assert exc.value.reason == "dns"


@pytest.mark.parametrize(
    "url", ["http://2130706433/", "http://0x7f000001/", "http://017700000001/", "http://127.1/",
            "http://localhost/", "http://[::1]/", "http://169.254.169.254/latest/meta-data/"],
)  # fmt: skip
async def test_numeric_and_local_spellings_resolve_to_refused_addresses(url: str) -> None:
    """The system resolver turns every spelling into an address, and the address is refused."""
    with pytest.raises(FetchRefusedError) as exc:
        await validate_source_url(url)
    assert exc.value.reason == "private-address"


async def test_validate_source_url_accepts_public_hosts() -> None:
    target = await validate_source_url("https://www.example.org/feed", resolver("93.184.215.14"))
    assert target.host == "www.example.org"
