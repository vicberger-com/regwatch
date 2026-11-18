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
        return httpx.Response(200, stream=httpx.ByteStream(b'{"results": []}'))

    got = await client(handler).get_json("/search", {"q": "AI act", "format": "json"})
    assert got == {"results": []}
    assert str(seen[0].url) == "http://search:8080/search?q=AI+act&format=json"
    assert seen[0].headers["accept"] == "application/json"


@pytest.mark.parametrize(
    ("response", "reason"),
    [(httpx.Response(302, headers={"location": "http://169.254.169.254/"}), "sidecar-status"),
     (httpx.Response(500), "sidecar-status"),
     (httpx.Response(200, stream=httpx.ByteStream(b"not json")), "sidecar-malformed"),
     (httpx.Response(200, stream=httpx.ByteStream(b"[" * 1000)), "sidecar-malformed"),
     (httpx.Response(200, stream=httpx.ByteStream(b"x" * 2048)), "sidecar-too-large"),
     # Search review finding 1: a compressed answer is refused before anything is inflated.
     (httpx.Response(200, headers={"content-encoding": "gzip, gzip"},
                     stream=httpx.ByteStream(b"\x1f\x8b...")), "sidecar-encoding")],
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


async def test_the_client_asks_for_an_uncompressed_answer() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(b"{}"))

    await client(handler).get_json("/search", {})
    assert seen[0].headers["accept-encoding"] == "identity"


async def test_a_dripping_sidecar_meets_the_whole_call_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search review finding 7: the read timeout is per read; the deadline is per call."""
    import asyncio

    from regwatch.core import internal

    monkeypatch.setattr(internal, "DEADLINE_S", 0.2)

    class Drip(httpx.AsyncByteStream):
        async def __aiter__(self):  # type: ignore[no-untyped-def]
            while True:
                await asyncio.sleep(0.05)
                yield b" "

    with pytest.raises(InternalError) as exc:
        await client(lambda r: httpx.Response(200, stream=Drip())).get_json("/search", {})
    assert exc.value.reason == "sidecar-timeout"
