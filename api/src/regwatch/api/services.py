"""Dependency probes for the health endpoint.

Until migration 0001 (#28) adds a database driver, the db probe opens a TCP connection to
the host and port in ``REGWATCH_DATABASE_URL``; the queue probe sends a RESP ``PING`` to
Valkey. Both use a short timeout and never raise.
"""

from __future__ import annotations

import asyncio
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Any
from urllib.parse import urlsplit

import anyio

from regwatch.api.schemas import DependencyState

PROBE_TIMEOUT_S = 1.0
# Stamped at image build by release.yml once it exists; "unknown" in development.
BUILD_COMMIT = "unknown"


def app_version() -> str:
    try:
        return package_version("regwatch")
    except PackageNotFoundError:  # pragma: no cover - only when run from an uninstalled tree
        return "0.0.0"


def _host_port(url: str, default_port: int) -> tuple[str, int]:
    parts = urlsplit(url)
    if not parts.hostname:
        raise ValueError("URL has no host")
    return parts.hostname, parts.port or default_port


async def _exchange(host: str, port: int, payload: bytes | None, expect: bytes | None) -> bool:
    writer = None
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_S):
            reader, writer = await asyncio.open_connection(host, port)
            if payload is not None:
                writer.write(payload)
                await writer.drain()
            if expect is not None:
                return (await reader.readline()).startswith(expect)
            return True
    except (OSError, TimeoutError, ValueError):
        return False
    finally:
        if writer is not None:
            writer.close()


async def probe_db(database_url: str) -> DependencyState:
    try:
        host, port = _host_port(database_url, 5432)
    except ValueError:
        return "unavailable"
    return "ok" if await _exchange(host, port, None, None) else "unavailable"


def _resp(*parts: str) -> bytes:
    """One RESP command (an array of bulk strings)."""
    out = [f"*{len(parts)}\r\n".encode()]
    for part in parts:
        data = part.encode()
        out.append(b"$%d\r\n%s\r\n" % (len(data), data))
    return b"".join(out)


async def probe_queue(queue_url: str) -> DependencyState:
    """A PING, after AUTH when the URL has credentials (the stack's Valkey has a password:
    without AUTH it answers NOAUTH, found by the M10.2 restore drill). The password goes only
    to the queue, never into a log or an answer."""
    from urllib.parse import unquote

    try:
        host, port = _host_port(queue_url, 6379)
    except ValueError:
        return "unavailable"
    parts = urlsplit(queue_url)
    if parts.password is None:
        ok = await _exchange(host, port, _resp("PING"), b"+PONG")
        return "ok" if ok else "unavailable"
    auth = (_resp("AUTH", unquote(parts.username or "default"), unquote(parts.password))
            if parts.username else _resp("AUTH", unquote(parts.password)))  # fmt: skip
    writer = None
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_S):
            reader, writer = await asyncio.open_connection(host, port)
            writer.write(auth + _resp("PING"))
            await writer.drain()
            authed = (await reader.readline()).startswith(b"+OK")
            pong = (await reader.readline()).startswith(b"+PONG")
            return "ok" if authed and pong else "unavailable"
    except (OSError, TimeoutError, ValueError):
        return "unavailable"
    finally:
        if writer is not None:
            writer.close()


READY_TIMEOUT_S = 2.0


async def probe_db_query(factory: Any) -> DependencyState:
    """A query, not just a connection: the database answers and this process may use it."""
    from sqlalchemy import text

    try:
        with anyio.fail_after(READY_TIMEOUT_S):
            async with factory() as db:
                await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any failure means not ready
        return "unavailable"
    return "ok"


async def probe_object_store(path: str) -> DependencyState:
    """The object store's directory exists and this process can write to it."""
    import os

    def check() -> bool:
        return os.path.isdir(path) and os.access(path, os.W_OK | os.X_OK)  # noqa: PTH112

    return "ok" if await anyio.to_thread.run_sync(check) else "unavailable"
