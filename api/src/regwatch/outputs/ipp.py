"""Network printing (M8.5b; BL-15, CP-33, BL-145): a PDF to an administrator's IPP printer,
from the outputs worker, with ippx (MIT, pinned in pyproject; register 3.6).

A printer is an address the server connects to, so it is treated as an outbound request to a
host an administrator chose, never one a user chose:
- ``ipps://`` with certificate verification, or the printer's pinned SHA-256 fingerprint for a
  self-signed certificate; ``ipp://`` (clear text) only with ``outputs.printer_plain_ipp``, and
  then sent to the address checked here, so DNS cannot move it (rebinding).
- The address must resolve, every answer, into ``outputs.printer_networks`` (empty by
  default: an administrator names the printers' subnets), and never to a loopback,
  link-local, multicast or unspecified address, into a network the worker itself is on (its
  routes and gateways), or to an address of the stack's own services, whose names are refused
  outright; only ports 631 and 443. Checked when a printer is saved and before each send.
- No user information in the URL, no query or fragment, no redirects, one attempt, 30 s a
  phase and 60 s a job, and a printer's answer is read to at most ``MAX_ANSWER`` bytes (ippx
  reads whole answers).
- TLS keeps the full default policy (``SECLEVEL=2``), not ippx's relaxed default for old
  printers.
"""

from __future__ import annotations

import ipaddress
import ssl
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import anyio
import httpx
import ippx

from regwatch.core.schemas import has_control

MAX_ANSWER = 1_000_000
TIMEOUT_S = 30.0  # each phase of a call (connect, each read)
TOTAL_S = 60.0  # a whole job, however slowly a printer answers (review of 182bf1c)
CIPHERS = "DEFAULT:@SECLEVEL=2"
PORTS = frozenset({631, 443})  # IPP and IPP over HTTPS: never another service's port
Network = ipaddress.IPv4Network | ipaddress.IPv6Network
# deploy/compose.yaml's services: never a printer, whatever the networks allow.
STACK_NAMES = frozenset({"localhost", "proxy", "api", "web", "worker", "beat", "db", "queue",
                         "pdf", "search", "translate", "mailpit", "ippeveprinter"})  # fmt: skip
TEST_PRINTER = "ippeveprinter"  # the test printer of the `print-test` profile (dev and QA)


class PrinterError(Exception):
    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.message = message


@dataclass(frozen=True)
class Target:
    scheme: str  # ipps or ipp
    host: str
    port: int
    path: str

    def url(self, host: str | None = None) -> str:
        name = host or self.host
        netloc = f"[{name}]:{self.port}" if ":" in name else f"{name}:{self.port}"
        return urlunsplit((self.scheme, netloc, self.path, "", ""))


def parse(url: str, allow_plain: bool, allow_test_printer: bool = False) -> Target:
    """The printer's address, or a ``ValueError`` saying what is wrong."""
    text = url.strip()
    if has_control(text) or len(text) > 500:
        raise ValueError("one line, at most 500 characters")
    parts = urlsplit(text)
    if parts.scheme not in ("ipps", "ipp"):
        raise ValueError("an ipps:// address, such as ipps://printer.example.internal/ipp/print")
    if parts.scheme == "ipp" and not allow_plain:
        raise ValueError("ipps:// only: clear-text ipp:// is off (outputs.printer_plain_ipp)")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("no user name, password, query or fragment in the address")
    host = (parts.hostname or "").rstrip(".").lower()
    try:
        port = parts.port or 631
    except ValueError:
        raise ValueError("a port from 1 to 65535") from None
    if not host:
        raise ValueError("a printer host name or address")
    if host in STACK_NAMES and not (allow_test_printer and host == TEST_PRINTER):
        raise ValueError("not one of the application's own services")
    if port not in PORTS:
        raise ValueError("port 631 (IPP) or 443")
    path = parts.path or "/ipp/print"
    return Target(parts.scheme, host, port, path)


def networks_of(values: Iterable[str]) -> list[Network]:
    return [ipaddress.ip_network(v.strip(), strict=False) for v in values if v.strip()]


def address_of(address: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """The address, an IPv4-mapped IPv6 one as its IPv4 form, so every check sees one value
    (review of 4f325f7: a mapped address skipped the own-network check)."""
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return ip.ipv4_mapped
    return ip


def allowed(address: str, networks: list[Network]) -> bool:
    ip = address_of(address)
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return False
    return any(ip in n for n in networks if n.version == ip.version)


async def lookup(host: str) -> set[str]:
    """The addresses of ``host``; empty when it does not resolve. Tests replace it."""
    try:
        with anyio.fail_after(5):
            infos = await anyio.getaddrinfo(host, None, type=0)
    except (OSError, TimeoutError):
        return set()
    return {str(info[4][0]) for info in infos}


def _routes_v4(text: str) -> list[Network]:
    """``/proc/net/route``: every routed network and gateway (little-endian hex)."""
    found: list[Network] = []
    for line in text.splitlines()[1:]:
        cols = line.split()
        if len(cols) < 8:
            continue
        dest, gateway, mask = (ipaddress.IPv4Address(int(c, 16).to_bytes(4, "little"))
                               for c in (cols[1], cols[2], cols[7]))  # fmt: skip
        if int(mask):  # the default route (0/0) is not a subnet of the stack's
            found.append(ipaddress.ip_network(f"{dest}/{mask}", strict=False))
        if int(gateway):
            found.append(ipaddress.ip_network(f"{gateway}/32"))
    return found


def _routes_v6(text: str) -> list[Network]:
    """``/proc/net/ipv6_route``: destination, prefix length, next hop, in hex."""
    found: list[Network] = []
    for line in text.splitlines():
        cols = line.split()
        if len(cols) < 10 or cols[-1] == "lo":
            continue
        dest = ipaddress.IPv6Address(int(cols[0], 16))
        prefix, hop = int(cols[1], 16), ipaddress.IPv6Address(int(cols[4], 16))
        if prefix and not dest.is_multicast and not dest.is_link_local:
            found.append(ipaddress.ip_network(f"{dest}/{prefix}", strict=False))
        if int(hop) and not hop.is_link_local:
            found.append(ipaddress.ip_network(f"{hop}/128"))
    return found


def own_networks() -> list[Network]:
    """The networks the worker itself is on, with their gateways: never printers (review of
    182bf1c). ``REGWATCH_STACK_NETWORKS`` when set; else the kernel's route tables. Fails
    closed: without either, nothing can be checked, so nothing is printed."""
    from regwatch.core.settings import get_settings

    given = get_settings().stack_networks
    if given:
        return networks_of(given)
    found: list[Network] = []
    read = False
    for path, parse_routes in (
        ("/proc/net/route", _routes_v4),
        ("/proc/net/ipv6_route", _routes_v6),
    ):
        try:
            with open(path, encoding="ascii") as routes:  # noqa: PTH123 - a kernel table
                found += parse_routes(routes.read())
            read = True
        except OSError:
            continue
    if not read:
        raise PrinterError("stack-unknown", "the server's own networks could not be read; set "
                           "REGWATCH_STACK_NETWORKS")  # fmt: skip
    return found


async def stack_addresses() -> set[str]:
    """The addresses of the application's own services, on the stack's private network: a
    printer is never one of them, whatever the allowed networks say."""
    found: set[str] = set()
    for name in sorted(STACK_NAMES - {"localhost", TEST_PRINTER}):
        found |= await lookup(name)
    return found


async def resolve(target: Target, networks: list[Network]) -> str:
    """One checked address of the printer; a ``PrinterError`` unless every answer is allowed."""
    try:
        found = {str(address_of(target.host))}
    except ValueError:
        found = {str(address_of(a)) for a in await lookup(target.host)}
    if not found:
        raise PrinterError("printer-not-found", "the printer's name does not resolve")
    if not networks:
        raise PrinterError("printer-address-refused", "no printer networks are allowed yet: an "
                           "administrator sets outputs.printer_networks")  # fmt: skip
    own = {address_of(a) for a in await stack_addresses()}
    mine = own_networks()

    def ok(text: str) -> bool:
        ip = address_of(text)
        return (allowed(text, networks) and ip not in own
                and not any(ip in n for n in mine if n.version == ip.version))  # fmt: skip

    if not all(ok(a) for a in found):
        raise PrinterError("printer-address-refused", "the printer's address is outside "
                           "the allowed printer networks")  # fmt: skip
    return sorted(found)[0]


class _Capped(httpx.AsyncBaseTransport):
    """Reads a printer's whole answer, as ippx does, but never more than ``MAX_ANSWER``."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.inner.handle_async_request(request)
        body = bytearray()
        try:
            async for chunk in response.stream:  # type: ignore[union-attr]
                body += chunk
                if len(body) > MAX_ANSWER:
                    raise PrinterError("printer-answer-too-large", "the printer's answer is "
                                       "larger than expected") from None  # fmt: skip
        finally:
            await response.aclose()
        return httpx.Response(response.status_code, headers=response.headers,
                              content=bytes(body), request=request)  # fmt: skip

    async def aclose(self) -> None:
        await self.inner.aclose()


def transport_factory(verify: bool | str | ssl.SSLContext) -> httpx.AsyncBaseTransport:
    """The connection to the printer; tests replace it with a mock printer."""
    return httpx.AsyncHTTPTransport(verify=verify, retries=0)


def _tls(fingerprint: str | None) -> ippx.TlsConfig:
    return ippx.TlsConfig(fingerprint=fingerprint or None, ciphers=CIPHERS)


async def send(*, ipp_url: str, tls_sha256: str | None, pdf: bytes, job_name: str, copies: int,
               media: str, networks: Iterable[str], allow_plain: bool,
               allow_test_printer: bool = False) -> int:  # fmt: skip
    """Print ``pdf``; the printer's job id once it accepts the job."""
    try:
        target = parse(ipp_url, allow_plain, allow_test_printer)
    except ValueError as exc:
        raise PrinterError("printer-address-refused", str(exc)) from None
    nets = networks_of(networks)
    if target.host == TEST_PRINTER and allow_test_printer:
        # The stack's own test printer, on the stack's network: by its address, as clear text
        # is sent to any printer (it accepts a numeric Host header, not its bare name).
        address = min(await lookup(target.host), default=target.host)
    else:
        address = await resolve(target, nets)
    # Clear text has no certificate to hold the name to its printer: send to the address that
    # was checked. ipps keeps the name, which the certificate (or the pin) is checked against.
    url = target.url(address if target.scheme == "ipp" else None)
    tls = _tls(tls_sha256)
    client = ippx.AsyncIppClient(url, tls=tls, timeout=TIMEOUT_S, requesting_user_name="regwatch")
    await client._http.aclose()  # noqa: SLF001 - ippx 0.1.1 (pinned): replace its client
    client._http = httpx.AsyncClient(  # noqa: SLF001
        transport=_Capped(transport_factory(tls.httpx_verify())), timeout=TIMEOUT_S,
        follow_redirects=False, headers={"Content-Type": "application/ipp",
                                         "Accept": "application/ipp"})  # fmt: skip
    try:
        with anyio.fail_after(TOTAL_S):
            async with client:
                job = await client.print_job(
                    pdf, document_format="application/pdf", job_name=job_name[:200],
                    job_attributes={"copies": copies, "media": media})  # fmt: skip
    except PrinterError:
        raise
    except ippx.IppResponseError as exc:
        raise PrinterError("printer-refused", f"the printer refused the job ({exc})"[:300]) \
            from None  # fmt: skip
    except (ippx.IppError, httpx.HTTPError, ssl.SSLError, OSError, TimeoutError) as exc:
        raise PrinterError("printer-unavailable", "the printer could not be reached "
                           f"({type(exc).__name__})") from None  # fmt: skip
    return int(job.job_id)
