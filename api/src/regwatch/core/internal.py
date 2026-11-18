"""The fixed-URL internal client for sidecars (ADR-0001; ADR-0010 decision 6).

SafeFetcher refuses private addresses, rightly: it fetches captured, hostile URLs. Sidecars
(``search``, later ``pdf`` and ``translate``) live on the internal network, so they are called
through this client instead, which can reach only what the settings name:

- one base URL per sidecar, from the settings, never from a request, a source or a page;
- only paths the caller names in code, joined to that base (no absolute URLs, no ``..``);
- no redirects followed, no proxies from the environment, no cookies kept;
- a timeout on every step and a cap on the answer's size, read as a stream;
- an answer that is not 2xx, too large or not JSON is an ``InternalError`` with a fixed text.

It is never used for captured content.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

MAX_ANSWER = 4 * 1024 * 1024
TIMEOUT = httpx.Timeout(connect=3.0, read=20.0, write=5.0, pool=3.0)
_PATH = re.compile(r"/[A-Za-z0-9_\-/]{0,100}")


class InternalError(Exception):
    """A sidecar failed; ``reason`` is a fixed code, ``detail`` never quotes the answer."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason, self.detail = reason, detail


class InternalClient:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None,
                 max_answer: int = MAX_ANSWER) -> None:  # fmt: skip
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.max_answer = max_answer

    async def get_json(self, path: str, params: dict[str, str]) -> Any:  # noqa: ANN401 - JSON
        """GET ``base_url + path`` with ``params``; the JSON it answers."""
        if not _PATH.fullmatch(path) or ".." in path or "//" in path:
            raise ValueError("an internal path is a fixed path such as /search")
        async with httpx.AsyncClient(base_url=self.base_url, transport=self.transport,
                                     timeout=TIMEOUT, follow_redirects=False,
                                     trust_env=False) as client:  # fmt: skip
            try:
                headers = {"accept": "application/json"}
                async with client.stream("GET", path, params=params, headers=headers) as got:
                    if not 200 <= got.status_code < 300:
                        status = f"the sidecar answered HTTP {got.status_code}"
                        raise InternalError("sidecar-status", status)
                    body = bytearray()
                    async for chunk in got.aiter_bytes():
                        body += chunk
                        if len(body) > self.max_answer:
                            raise InternalError("sidecar-too-large", "the sidecar's answer is "
                                                "larger than the limit")  # fmt: skip
            except httpx.TimeoutException:
                raise InternalError(
                    "sidecar-timeout", "the sidecar did not answer in time"
                ) from None
            except httpx.HTTPError:
                raise InternalError(
                    "sidecar-unavailable", "the sidecar could not be reached"
                ) from None
        try:
            return json.loads(bytes(body))
        except (ValueError, RecursionError):
            raise InternalError("sidecar-malformed", "the sidecar's answer is not JSON") from None
