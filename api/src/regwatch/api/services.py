"""Dependency probes for the health endpoint.

Until migration 0001 (#28) adds a database driver, the db probe opens a TCP connection to
the host and port in ``REGWATCH_DATABASE_URL``; the queue probe sends a RESP ``PING`` to
Valkey. Both use a short timeout and never raise.
"""

from __future__ import annotations

import asyncio
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from urllib.parse import urlsplit

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


async def probe_queue(queue_url: str) -> DependencyState:
    try:
        host, port = _host_port(queue_url, 6379)
    except ValueError:
        return "unavailable"
    ok = await _exchange(host, port, b"*1\r\n$4\r\nPING\r\n", b"+PONG")
    return "ok" if ok else "unavailable"
