"""SafeFetcher's fetch: one pinned connection per hop, re-checked redirects, size and time caps.

For every hop (the first request and each redirect, at most ``max_redirects``):

1. ``parse_target`` and ``resolve`` check the URL and every address of its host (``policy``).
2. The request goes to one checked address, not to the host name, so DNS cannot answer
   differently at connection time (rebinding). ``Host`` carries the name, and for https the
   TLS server name and certificate check use it too (httpcore's ``sni_hostname``).
3. The body is read as a stream and stops at ``max_bytes`` after decompression, so a gzip
   bomb or a lying ``Content-Length`` cannot exhaust memory. Each hop has a total deadline as
   well as connect and read timeouts, so a slow server cannot hold a worker.

Connections are not kept alive between hops, so every hop's TLS certificate is checked for its
own name. Environment proxies are ignored (``trust_env=False``): a proxy would see the request
instead of the checked address. ``pinned_hosts`` exists for tests that use the local fixture
server (see ``policy.resolve``) and must never be set from configuration.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
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
        pinned_hosts: Mapping[str, str] | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.limits = limits or FetchLimits()
        self._resolver = resolver
        self._transport = transport
        self._pinned = dict(pinned_hosts or {})

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

    async def _read(self, response: httpx.Response) -> bytes:
        limit = self.limits.max_bytes
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            raise FetchRefusedError("too-large", f"the body is larger than {limit} bytes")
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():  # decoded: the cap applies after gzip
            size += len(chunk)
            if size > limit:
                raise FetchRefusedError("too-large", f"the body is larger than {limit} bytes")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _hop(self, client: httpx.AsyncClient, url: str,
                   method: str) -> tuple[FetchResult | None, str | None, int]:  # fmt: skip
        """One request: the result, or the redirect location and status."""
        target = parse_target(url)
        ip = (await resolve(target, self._resolver, self._pinned))[0]
        try:
            async with asyncio.timeout(self.limits.total_s):
                request = self._request(client, target, ip, method)
                response = await client.send(request, stream=True)
                try:
                    location = response.headers.get("location")
                    if response.status_code in REDIRECTS and location:
                        return None, location, response.status_code
                    body = await self._read(response)
                    headers = dict(response.headers)
                    return FetchResult(url, response.status_code, headers, body), None, 0
                finally:
                    await response.aclose()
        except TimeoutError:
            detail = f"{target.host} took longer than {self.limits.total_s:g} s"
            raise FetchRefusedError("timeout", detail) from None
        except httpx.TimeoutException as exc:
            raise FetchRefusedError("timeout", f"{target.host}: {exc}") from None
        except httpx.HTTPError as exc:
            raise FetchRefusedError("connect", f"{target.host}: {exc}") from None

    async def fetch(self, url: str, method: str = "GET") -> FetchResult:
        """Fetch ``url`` with every hop checked; ``FetchRefusedError`` says why it was refused."""
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
            limits=httpx.Limits(max_keepalive_connections=0),
        ) as client:
            current = url
            while True:
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
