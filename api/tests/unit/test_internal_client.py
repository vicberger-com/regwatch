"""The fixed-URL internal client for sidecars (ADR-0001; ADR-0010 decision 6)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from regwatch.core.internal import InternalClient, InternalError

BASE = "http://search:8080"


def client(handler: Any, **kw: Any) -> InternalClient:
    return InternalClient(BASE, transport=httpx.MockTransport(handler), **kw)


async def test_a_json_answer_from_the_fixed_base() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"results": []})

    got = await client(handler).get_json("/search", {"q": "AI act", "format": "json"})
    assert got == {"results": []}
    assert str(seen[0].url) == "http://search:8080/search?q=AI+act&format=json"
    assert seen[0].headers["accept"] == "application/json"


@pytest.mark.parametrize(
    ("response", "reason"),
    [(httpx.Response(302, headers={"location": "http://169.254.169.254/"}), "sidecar-status"),
     (httpx.Response(500), "sidecar-status"), (httpx.Response(200, content=b"not json"),
                                               "sidecar-malformed"),
     (httpx.Response(200, content=b"[" * 1000), "sidecar-malformed"),
     (httpx.Response(200, content=b"x" * 2048), "sidecar-too-large")],
)  # fmt: skip
async def test_answers_that_are_not_usable_are_typed_errors(response: httpx.Response,
                                                            reason: str) -> None:  # fmt: skip
    with pytest.raises(InternalError) as exc:
        await client(lambda r: response, max_answer=1024).get_json("/search", {})
    assert exc.value.reason == reason and "169.254" not in exc.value.detail


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (httpx.ConnectError("no"), "sidecar-unavailable"),
        (httpx.ReadTimeout("slow"), "sidecar-timeout"),
    ],
)
async def test_transport_failures_are_typed_errors(error: Exception, reason: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(InternalError) as exc:
        await client(handler).get_json("/search", {})
    assert exc.value.reason == reason


@pytest.mark.parametrize("path", ["http://evil.example/", "//evil.example/x", "/../admin", "search",
                                  "/a?b=c", "/" + "a" * 101])  # fmt: skip
async def test_only_fixed_paths_on_the_base(path: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nothing may be sent")

    with pytest.raises(ValueError):
        await client(handler).get_json(path, {})
