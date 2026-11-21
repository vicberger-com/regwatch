"""The queue probe (CP-34): AUTH only over TLS when the URL asks for it (review of 4fc1014)."""

from __future__ import annotations

import asyncio
import ssl
from typing import Any

import pytest

from regwatch.api import services


class _Reader:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines

    async def readline(self) -> bytes:
        return self.lines.pop(0)


class _Writer:
    def __init__(self) -> None:
        self.sent = b""

    def write(self, data: bytes) -> None:
        self.sent += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.mark.parametrize(("url", "tls"), [("rediss://default:pw@q:6380/0", True),
                                          ("redis://default:pw@q:6379/0", False)])  # fmt: skip
async def test_tls_urls_get_tls_before_the_password(
    monkeypatch: pytest.MonkeyPatch, url: str, tls: bool
) -> None:
    seen: dict[str, Any] = {}
    writer = _Writer()

    async def connect(host: str, port: int, **kw: Any) -> tuple[_Reader, _Writer]:
        seen.update(kw, host=host, port=port)
        return _Reader([b"+OK\r\n", b"+PONG\r\n"]), writer

    monkeypatch.setattr(asyncio, "open_connection", connect)
    assert await services.probe_queue(url) == "ok"
    assert isinstance(seen.get("ssl"), ssl.SSLContext) is tls
    assert b"AUTH" in writer.sent
