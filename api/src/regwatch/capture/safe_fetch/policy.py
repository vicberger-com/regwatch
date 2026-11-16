"""Which URLs and addresses SafeFetcher may reach (M3 acceptance 3; 8.1 SSRF).

A URL is fetchable when its scheme is http or https, it carries no user name or password, and
every address its host resolves to is a public unicast address. Hosts are always resolved and
the addresses checked, so numeric spellings of private addresses (``2130706433``, ``0x7f.1``,
``017700000001``) are caught by the same rule as ``127.0.0.1``. IPv6 addresses that embed an
IPv4 address (IPv4-mapped, 6to4, Teredo, NAT64) are judged by the embedded address too.

The caller connects to one of the checked addresses itself (``fetch`` pins it), so a DNS answer
that changes between the check and the connection cannot redirect the request (rebinding).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Awaitable[list[str]]]

SCHEMES = {"http": 80, "https": 443}
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
# Every IPv6 address whose top 64 bits are zero embeds IPv4 or is special: IPv4-compatible
# (::/96), IPv4-mapped (::ffff:0:0/96) and IPv4-translated (::ffff:0:0:0/96). No public
# unicast address starts that way (review finding 2). Site-local fec0::/10 is deprecated.
# Not all of ::/8: the NAT64 prefix 64:ff9b::/96 lies inside it, and NAT64 answers stay
# fetchable, judged by the IPv4 address they embed (re-verification, finding 11).
_RESERVED6 = ipaddress.ip_network("::/64")
_SITE_LOCAL = ipaddress.ip_network("fec0::/10")
MAX_URL = 2048


class FetchRefusedError(ValueError):
    """The URL or an address it resolves to may not be fetched; ``reason`` is a stable code."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Target:
    scheme: str
    host: str  # IDNA-encoded, lower case, no brackets
    port: int
    path: str  # path and query, at least "/"

    @property
    def origin(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        default = SCHEMES[self.scheme] == self.port
        return f"{self.scheme}://{host}" + ("" if default else f":{self.port}")


def parse_target(url: str) -> Target:
    """The parts of an absolute http or https URL, or ``FetchRefusedError``."""
    if len(url) > MAX_URL:
        raise FetchRefusedError("url", f"the URL is longer than {MAX_URL} characters")
    if any(ord(c) < 0x21 or c == "\x7f" for c in url):
        raise FetchRefusedError("url", "the URL contains spaces or control characters")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise FetchRefusedError("url", f"not a valid URL: {exc}") from None
    scheme = parts.scheme.lower()
    if scheme not in SCHEMES:
        raise FetchRefusedError("scheme", "only http and https URLs can be fetched")
    if parts.username is not None or parts.password is not None:
        raise FetchRefusedError("userinfo", "URLs with a user name or password are not fetched")
    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise FetchRefusedError("url", "the URL has no host")
    try:
        host = host.encode("idna").decode("ascii").lower() if not _is_ip(host) else host
    except UnicodeError:
        raise FetchRefusedError("url", "the host name is not a valid international name") from None
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return Target(scheme, host, port or SCHEMES[scheme], path)


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _embedded(ip: IPAddress) -> list[IPAddress]:
    if not isinstance(ip, ipaddress.IPv6Address):
        return []
    found: list[IPAddress] = []  # IPv4-mapped and -compatible are inside ::/64, refused above
    if ip.sixtofour is not None:
        found.append(ip.sixtofour)
    if ip.teredo is not None:
        found.extend(ip.teredo)
    if ip in _NAT64:
        found.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return found


def check_address(address: str) -> IPAddress:
    """The address if it is a public unicast address, or ``FetchRefusedError``."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        raise FetchRefusedError("address", f"{address!r} is not an IP address") from None
    if isinstance(ip, ipaddress.IPv6Address) and (ip in _RESERVED6 or ip in _SITE_LOCAL):
        raise FetchRefusedError(
            "private-address", f"{ip} is not a public address and cannot be fetched"
        )
    for candidate in (ip, *_embedded(ip)):
        if not candidate.is_global or candidate.is_multicast:
            raise FetchRefusedError(
                "private-address", f"{ip} is not a public address and cannot be fetched"
            )
    return ip


async def _system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    )
    return [str(info[4][0]) for info in infos]


async def resolve(target: Target, resolver: Resolver | None = None) -> list[IPAddress]:
    """Every address of the target's host, all checked; refused if any one is not public."""
    try:
        found = await (resolver or _system_resolver)(target.host, target.port)
    except (OSError, UnicodeError) as exc:
        raise FetchRefusedError("dns", f"{target.host} could not be resolved: {exc}") from None
    if not found:
        raise FetchRefusedError("dns", f"{target.host} has no addresses")
    # One private answer refuses the host: a mixed answer is how rebinding attacks start.
    return [check_address(a) for a in dict.fromkeys(found)]


async def validate_source_url(url: str, resolver: Resolver | None = None) -> Target:
    """The check when an admin saves a source URL (M3 acceptance 3).

    The URL must parse, and its host must resolve to public addresses only. A host that does
    not resolve yet is refused too, so a source never starts out pointing at nothing.
    """
    target = parse_target(url)
    await resolve(target, resolver)
    return target
