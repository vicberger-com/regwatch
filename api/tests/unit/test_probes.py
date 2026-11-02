from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest

from regwatch.api import services

Handler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]


@pytest.fixture
async def server() -> AsyncIterator[Callable[[Handler], Awaitable[int]]]:
    servers: list[asyncio.Server] = []

    async def start(handler: Handler) -> int:
        srv = await asyncio.start_server(handler, "127.0.0.1", 0)
        servers.append(srv)
        return int(srv.sockets[0].getsockname()[1])

    yield start
    for srv in servers:
        srv.close()
        await asyncio.wait_for(srv.wait_closed(), timeout=2)


async def _pong(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    await reader.readline()
    writer.write(b"+PONG\r\n")
    await writer.drain()
    writer.close()


async def _wrong(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    writer.write(b"-ERR nope\r\n")
    await writer.drain()
    writer.close()


async def _silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    await reader.read()  # never answers; returns when the probe gives up and disconnects
    writer.close()


async def test_queue_ok(server: Callable[[Handler], Awaitable[int]]) -> None:
    port = await server(_pong)
    assert await services.probe_queue(f"valkey://127.0.0.1:{port}/0") == "ok"


async def test_queue_wrong_reply(server: Callable[[Handler], Awaitable[int]]) -> None:
    port = await server(_wrong)
    assert await services.probe_queue(f"valkey://127.0.0.1:{port}/0") == "unavailable"


async def test_queue_timeout(
    server: Callable[[Handler], Awaitable[int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(services, "PROBE_TIMEOUT_S", 0.05)
    port = await server(_silent)
    assert await services.probe_queue(f"valkey://127.0.0.1:{port}/0") == "unavailable"


async def test_db_ok_and_refused(server: Callable[[Handler], Awaitable[int]]) -> None:
    port = await server(_wrong)
    assert await services.probe_db(f"postgresql://u:p@127.0.0.1:{port}/x") == "ok"
    assert await services.probe_db("postgresql://u:p@127.0.0.1:1/x") == "unavailable"


@pytest.mark.parametrize("url", ["postgresql:///nohost", "not-a-url"])
async def test_url_without_host(url: str) -> None:
    assert await services.probe_db(url) == "unavailable"
    assert await services.probe_queue(url) == "unavailable"
