"""SafeFetcher's fetch: one pinned connection per hop, re-checked redirects, size and time caps.

For every hop (the first request and each redirect, at most ``max_redirects``):

1. ``parse_target`` and ``resolve`` check the URL and every address of its host (``policy``).
2. The request goes to one checked address, not to the host name, so DNS cannot answer
   differently at connection time (rebinding). ``Host`` carries the name, and for https the
   TLS server name and certificate check use it too (httpcore's ``sni_hostname``).
3. The raw body is read as a stream and decompressed here, never by httpx, with an output
   limit on every step, so neither a gzip bomb nor stacked encodings can grow past
   ``max_bytes`` in memory (review finding 1). Only identity, gzip and deflate are accepted,
   one at a time. A lying ``Content-Length`` cannot help either. Each hop, including its DNS
   lookup, has a total deadline as well as connect and read timeouts, so a slow server or
   name server cannot hold a worker (finding 3).

Connections are not kept alive between hops, so every hop's TLS certificate is checked for its
own name. Environment proxies are ignored (``trust_env=False``): a proxy would see the request
instead of the checked address. Tests reach the local fixture server by overriding ``_resolve`` in a
subclass; the class itself has no way to skip the address check (finding 4).
"""

from __future__ import annotations

import asyncio
import copy
import ssl
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

from regwatch.capture.safe_fetch.policy import (
    FetchRefusedError,
    IPAddress,
    Resolver,
    Target,
    parse_target,
    resolve,
)

REDIRECTS = {301, 302, 303, 307, 308}
HopCheck = Callable[[str], Awaitable[None]]


_GZIP_MAGIC = b"\x1f\x8b"


class _BodyDecoder:
    """Bounded decoding of one ``Content-Encoding`` (review findings 1, 8 and 9).

    Every ``decompress`` call is limited to the room left under the cap, and anything left over
    after the end of a compressed stream is dealt with at once instead of piling up in zlib:
    another gzip member is decoded as gzip allows (RFC 1952), and any other trailing data is
    refused. A stream that ends early is refused too. ``deflate`` takes the zlib wrapper RFC 9110
    names, and raw deflate as many servers send it.
    """

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._d: zlib._Decompress | None = None
        self._pending = b""  # bytes too few to tell what follows (a gzip magic, a zlib header)
        self._ended = False  # deflate: the one stream has ended; any later byte is refused

    def _start(self, data: bytes) -> zlib._Decompress:
        if self.kind == "gzip":
            return zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
        zlib_header = len(data) >= 2 and data[0] & 0x0F == 8 and (data[0] << 8 | data[1]) % 31 == 0
        return zlib.decompressobj() if zlib_header else zlib.decompressobj(wbits=-zlib.MAX_WBITS)

    def feed(self, data: bytes, room: int) -> bytes:
        """Decoded output for ``data``, never more than ``room + 1`` bytes."""
        out = bytearray()
        data = self._pending + data
        self._pending = b""
        while data:
            if self._d is None:
                if self._ended:  # review finding 12 (b)
                    raise FetchRefusedError("encoding", "data after the end of the deflate body")
                if len(data) < 2:  # wait for the second byte (gzip magic, zlib header; 12 (a))
                    self._pending = data
                    break
                if self.kind == "gzip" and not data.startswith(_GZIP_MAGIC):
                    raise FetchRefusedError("encoding", "data after the end of the gzip body")
                self._d = self._start(data)
            out += self._d.decompress(data, max(1, room - len(out) + 1))
            if len(out) > room:
                break
            if self._d.eof:
                data = self._d.unused_data  # handled now, never left to grow inside zlib
                if self.kind != "gzip":
                    if data:
                        raise FetchRefusedError(
                            "encoding", "data after the end of the deflate body"
                        )
                    self._ended = True
                self._d = None
            else:
                data = self._d.unconsumed_tail
        return bytes(out)

    def finish(self) -> bytes:
        if self._pending:
            if self.kind == "deflate" and not self._ended:
                raise FetchRefusedError("encoding", "the compressed body ends early")
            raise FetchRefusedError("encoding", f"data after the end of the {self.kind} body")
        if self._d is None:
            return b""
        if not self._d.eof:
            out = self._d.flush()
            raise FetchRefusedError("encoding", f"the compressed body ends early ({len(out)} b)")
        return b""  # pragma: no cover - an ended stream is always cleared in feed


def _decoder(encoding: str) -> _BodyDecoder | None:
    """A bounded decoder for one ``Content-Encoding``; stacked or unknown ones are refused."""
    names = [e.strip().lower() for e in encoding.split(",") if e.strip()]
    names = [n for n in names if n != "identity"]
    if not names:
        return None
    if len(names) > 1:
        raise FetchRefusedError("encoding", f"stacked content encodings are refused: {encoding}")
    if names[0] in ("gzip", "x-gzip"):
        return _BodyDecoder("gzip")
    if names[0] == "deflate":
        return _BodyDecoder("deflate")
    raise FetchRefusedError("encoding", f"content encoding {names[0]!r} is not accepted")


@dataclass(frozen=True)
class FetchLimits:
    max_bytes: int = 10 * 1024 * 1024  # 10 MB, the M3 default (capture.max_body_bytes)
    connect_s: float = 10.0
    read_s: float = 30.0
    total_s: float = 60.0  # per hop
    max_redirects: int = 5


@dataclass(frozen=True)
class FetchResult:
    url: str  # after redirects
    status: int
    headers: dict[str, str]
    body: bytes
    redirects: list[str] = field(default_factory=list)

    @property
    def mime(self) -> str:
        return self.headers.get("content-type", "").split(";", 1)[0].strip().lower()


class SafeFetcher:
    def __init__(
        self,
        user_agent: str,
        limits: FetchLimits | None = None,
        *,
        resolver: Resolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.limits = limits or FetchLimits()
        self._resolver = resolver
        self._transport = transport

    def _request(self, client: httpx.AsyncClient, target: Target, ip: IPAddress,
                 method: str) -> httpx.Request:  # fmt: skip
        literal = f"[{ip}]" if ip.version == 6 else str(ip)
        url = f"{target.scheme}://{literal}:{target.port}{target.path}"
        host = target.origin.split("://", 1)[1]
        extensions = {"sni_hostname": target.host} if target.scheme == "https" else {}
        return client.build_request(
            method,
            url,
            headers={
                "Host": host,
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
            },  # fmt: skip
            extensions=extensions,
        )

    async def check_url(self, url: str) -> Target:
        """The URL's checks without fetching: parse it and check every resolved address.

        The lookup has the hop's deadline, like the one in ``_hop`` (review finding 23).
        """
        target = parse_target(url)
        try:
            async with asyncio.timeout(self.limits.total_s):
                await self._resolve(target)
        except TimeoutError:
            detail = f"DNS for {target.host} took longer than {self.limits.total_s:g} s"
            raise FetchRefusedError("timeout", detail) from None
        return target

    def with_limits(self, limits: FetchLimits) -> SafeFetcher:
        """The same fetcher (including any test subclass) with other limits."""
        clone = copy.copy(self)
        clone.limits = limits
        return clone

    async def _resolve(self, target: Target) -> list[IPAddress]:
        return await resolve(target, self._resolver)

    def _tls(self) -> ssl.SSLContext | bool:
        """Certificate and host-name checks with httpx's default authorities; tests may supply
        a context that trusts their own authority, never one that checks less."""
        return True

    def _checked_tls(self) -> ssl.SSLContext | bool:
        tls = self._tls()
        if tls is not True and not (
            isinstance(tls, ssl.SSLContext)
            and tls.verify_mode == ssl.CERT_REQUIRED
            and tls.check_hostname
        ):
            raise ValueError("SafeFetcher never fetches without certificate and host-name checks")
        return tls

    async def _read(self, response: httpx.Response) -> bytes:
        limit = self.limits.max_bytes
        too_large = FetchRefusedError("too-large", f"the body is larger than {limit} bytes")
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            raise too_large
        decoder = _decoder(response.headers.get("content-encoding", ""))
        out = bytearray()
        raw = 0
        async for chunk in response.aiter_raw():  # undecoded: decompression happens here
            raw += len(chunk)  # what arrives counts too, whatever the encoding (finding 8)
            if raw > limit:
                raise too_large
            out += chunk if decoder is None else decoder.feed(chunk, limit - len(out))
            if len(out) > limit:
                raise too_large
        if decoder is not None:
            out += decoder.finish()
        return bytes(out)

    async def _hop(self, client: httpx.AsyncClient, url: str,
                   method: str) -> tuple[FetchResult | None, str | None, int]:  # fmt: skip
        """One request: the result, or the redirect location and status."""
        target = parse_target(url)
        try:
            phase = "DNS for"
            async with asyncio.timeout(self.limits.total_s):  # DNS included (finding 3)
                ip = (await self._resolve(target))[0]
                phase = "the server at"
                request = self._request(client, target, ip, method)
                response = await client.send(request, stream=True)
                try:
                    location = response.headers.get("location")
                    if response.status_code in REDIRECTS and location:
                        return None, location, response.status_code
                    body = await self._read(response)
                    headers = dict(response.headers)
                    if headers.pop("content-encoding", None) is not None:
                        headers.pop("content-length", None)  # they described the encoded body
                    return FetchResult(url, response.status_code, headers, body), None, 0
                finally:
                    await response.aclose()
        except TimeoutError:
            detail = f"{phase} {target.host} took longer than {self.limits.total_s:g} s"
            raise FetchRefusedError("timeout", detail) from None
        except httpx.TimeoutException as exc:
            raise FetchRefusedError("timeout", f"{target.host}: {exc}") from None
        except zlib.error as exc:
            raise FetchRefusedError(
                "encoding", f"{target.host}: a damaged compressed body: {exc}"
            ) from None
        except httpx.HTTPError as exc:
            raise FetchRefusedError("connect", f"{target.host}: {exc}") from None

    async def fetch(
        self, url: str, method: str = "GET", before_hop: HopCheck | None = None
    ) -> FetchResult:
        """Fetch ``url`` with every hop checked; ``FetchRefusedError`` says why it was refused.

        ``before_hop`` is awaited with each hop's URL before it is requested, including
        redirect targets, so robots.txt and per-host rate limits apply to every host reached.
        """
        limits = self.limits
        timeout = httpx.Timeout(connect=limits.connect_s, read=limits.read_s,
                                write=limits.read_s, pool=limits.connect_s)  # fmt: skip
        redirects: list[str] = []
        # No kept-alive connections: the pool is keyed by address, so a redirect to another
        # name on the same address (a shared CDN) would reuse a TLS session whose certificate
        # was checked for the first name only.
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            verify=self._checked_tls(),
            limits=httpx.Limits(max_keepalive_connections=0),
        ) as client:
            current = url
            while True:
                if before_hop is not None:
                    await before_hop(current)
                result, location, status = await self._hop(client, current, method)
                if result is not None:
                    return FetchResult(result.url, result.status, result.headers, result.body,
                                       redirects)  # fmt: skip
                if len(redirects) >= limits.max_redirects:
                    raise FetchRefusedError(
                        "redirects", f"more than {limits.max_redirects} redirects"
                    )
                current = urljoin(current, location or "")
                redirects.append(current)
                if status == 303:
                    method = "GET"
