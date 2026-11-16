"""Fixture HTTP server for capture, SSRF and parser tests (issue #12, REQ-25; fixtures.md).

Two listeners run on one event loop in a background thread:

- ``base_url``: a FastAPI app (served by uvicorn) for the fixture files and HTTP-level
  behaviour: status codes, delays, redirect chains and loops, redirects to private addresses,
  slow bodies, oversized bodies, gzip bombs, robots.txt variants and change sequences.
- ``raw_url``: a plain asyncio socket listener for byte-level misbehaviour that an HTTP
  library refuses to produce: a Content-Length that lies, headers trickled byte by byte, a
  connection that never answers, and non-HTTP garbage.

Any request to ``base_url`` also takes ``?delay_ms=N`` (wait before answering) and
``?status=N`` (override the status). Every request is recorded in ``server.state.requests``.

    with FixtureServer() as server:
        httpx.get(server.url("/redirect/private/metadata"))

Run standalone (from ``api/``): ``uv run python -m tests.support.fixture_server --port 8099``.
Route reference: ``tests/fixtures/README.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import struct
import threading
import time
import zlib
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse, RedirectResponse, StreamingResponse

from tests.fixtures.feeds.generate import GENERATORS

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
DIRS = {"feeds": FIXTURES / "feeds", "pages": FIXTURES / "pages", "corpus": FIXTURES / "corpus"}
MIB = 1024 * 1024
MAX_DELAY_MS = 120_000
MAX_SIZE = 4096 * MIB
SERVED_SUFFIXES = {".xml", ".html", ".txt", ".json", ".md"}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json",
    ".md": "text/markdown; charset=utf-8",
    ".xml": "application/rss+xml; charset=utf-8",
}
SPECIAL_TYPES = {
    "valid_atom.xml": "application/atom+xml; charset=utf-8",
    "encoding_latin1.xml": "application/rss+xml; charset=ISO-8859-1",
    "malformed.xml": "application/rss+xml",
    "hostile.xml": "application/rss+xml",
}
ROBOTS_VARIANTS = ("allow", "disallow", "crawl_delay")


def _load_json(name: str) -> dict[str, object]:
    data: dict[str, object] = json.loads((DIRS["pages"] / name).read_text(encoding="utf-8"))
    return data


@dataclass
class RecordedRequest:
    method: str
    path: str
    query: str
    headers: dict[str, str]
    listener: str = "app"
    client_port: int | None = None  # tells apart requests on separate connections
    at: float = field(default_factory=time.monotonic)  # arrival, for rate-window checks


@dataclass
class ServerState:
    robots: str = "allow"
    sequence_pos: dict[str, int] = field(default_factory=dict)
    requests: list[RecordedRequest] = field(default_factory=list)
    port: int = 0

    def reset(self) -> None:
        self.robots = "allow"
        self.sequence_pos.clear()
        self.requests.clear()


# --- generated bodies -------------------------------------------------------------------


@cache
def _zero_segment() -> tuple[bytes, bytes]:
    """Gzip header plus the first 1 MiB block, and the identical deflate block for later MiBs."""
    co = zlib.compressobj(9, zlib.DEFLATED, 31)
    block = b"\0" * MIB
    first = co.compress(block) + co.flush(zlib.Z_FULL_FLUSH)
    repeat = co.compress(block) + co.flush(zlib.Z_FULL_FLUSH)
    return first, repeat


@cache
def _zero_crc(mib: int) -> int:
    crc, block = 0, b"\0" * MIB
    for _ in range(mib):
        crc = zlib.crc32(block, crc)
    return crc


def gzip_bomb(mib: int) -> Iterator[bytes]:
    """A valid single-member gzip stream that inflates to ``mib`` MiB of zero bytes.

    About 1 KiB on the wire per MiB inflated; built at run time and never stored on disk.
    """
    first, repeat = _zero_segment()
    yield first
    for _ in range(mib - 1):
        yield repeat
    yield b"\x03\x00"  # empty final block (fixed Huffman), byte-aligned after a full flush
    yield struct.pack("<II", _zero_crc(mib), (mib * MIB) & 0xFFFFFFFF)


def nested_gzip_bomb(mib: int) -> bytes:
    """Gzip of a gzip bomb: needs two decoding passes (``Content-Encoding: gzip, gzip``)."""
    return zlib.compress(b"".join(gzip_bomb(mib)), 9, wbits=31)


@cache
def generated_feed(name: str) -> bytes:
    return GENERATORS[name]()


def _item_page(n: int) -> str:
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f"<title>Notice {n:02d}</title></head><body><main><h1>Notice {n:02d}</h1>"
        f"<p>Generated item page {n:02d} for the listing fixture (issue #12).</p>"
        "</main></body></html>"
    )


# --- FastAPI app ------------------------------------------------------------------------


def _int(request: Request, name: str, default: int, lo: int, hi: int) -> int:
    raw = request.query_params.get(name)
    value = default if raw is None else int(raw)
    return max(lo, min(hi, value))


def create_app(state: ServerState) -> FastAPI:  # noqa: C901 - one route table
    app = FastAPI(title="regwatch fixture server", docs_url=None, redoc_url=None, openapi_url=None)
    chain = _load_json("redirect_chain.json")
    private = _load_json("private_redirect.json")["targets"]
    sequences = _load_json("sequences.json")["sequences"]
    assert isinstance(private, dict) and isinstance(sequences, dict)

    @app.middleware("http")
    async def common(request: Request, call_next):  # type: ignore[no-untyped-def]
        state.requests.append(
            RecordedRequest(
                request.method,
                request.url.path,
                request.url.query,
                dict(request.headers),
                client_port=request.client.port if request.client else None,
            )
        )
        delay = request.query_params.get("delay_ms")
        if delay is not None:
            await asyncio.sleep(min(int(delay), MAX_DELAY_MS) / 1000)
        response = await call_next(request)
        override = request.query_params.get("status")
        if override is not None:
            response.status_code = int(override)
        return response

    @app.get("/health")
    async def health() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.get("/robots.txt")
    async def robots() -> Response:
        return _file("pages", f"robots_{state.robots}.txt")

    @app.put("/_control/robots/{variant}")
    async def set_robots(variant: str) -> PlainTextResponse:
        if variant not in ROBOTS_VARIANTS:
            return PlainTextResponse("unknown variant", status_code=404)
        state.robots = variant
        return PlainTextResponse(variant)

    @app.post("/_control/reset")
    async def reset() -> PlainTextResponse:
        state.reset()
        return PlainTextResponse("reset")

    @app.get("/status/{code}")
    async def status(code: int, request: Request) -> Response:
        headers = {}
        if "retry_after" in request.query_params:
            headers["Retry-After"] = request.query_params["retry_after"]
        return PlainTextResponse(f"status {code}\n", status_code=code, headers=headers)

    @app.get("/delay/{ms}")
    async def delay(ms: int) -> PlainTextResponse:
        await asyncio.sleep(min(ms, MAX_DELAY_MS) / 1000)
        return PlainTextResponse(f"delayed {ms} ms\n")

    @app.get("/redirect/chain/{n}")
    async def redirect_chain(n: int) -> Response:
        statuses = chain["statuses"]
        assert isinstance(statuses, list)
        target = str(chain["final"]) if n <= 0 else f"/redirect/chain/{n - 1}"
        return RedirectResponse(target, status_code=int(statuses[n % len(statuses)]))

    @app.get("/redirect/loop/{side}")
    async def redirect_loop(side: str) -> Response:
        return RedirectResponse(f"/redirect/loop/{'b' if side == 'a' else 'a'}", status_code=302)

    @app.get("/redirect/to")
    async def redirect_to(request: Request) -> Response:
        code = _int(request, "code", 302, 300, 399)
        return Response(
            status_code=code, headers={"Location": request.query_params.get("url", "/")}
        )

    @app.get("/redirect/private/{name}")
    async def redirect_private(name: str) -> Response:
        if name not in private:
            return PlainTextResponse("unknown target", status_code=404)
        location = str(private[name]).replace("{port}", str(state.port))
        return Response(status_code=302, headers={"Location": location})

    @app.get("/slow/body")
    async def slow_body(request: Request) -> StreamingResponse:
        chunks = _int(request, "chunks", 10, 1, 10_000)
        interval = _int(request, "interval_ms", 500, 0, MAX_DELAY_MS)
        size = _int(request, "chunk_bytes", 64, 1, MIB)

        async def gen() -> AsyncIterator[bytes]:
            for _ in range(chunks):
                yield b"s" * size
                await asyncio.sleep(interval / 1000)

        return StreamingResponse(gen(), media_type="text/plain")

    @app.get("/size/{n}")
    async def size(n: int, request: Request) -> StreamingResponse:
        n = max(0, min(n, MAX_SIZE))

        async def gen() -> AsyncIterator[bytes]:
            left = n
            while left > 0:
                step = min(left, 64 * 1024)
                yield b"x" * step
                left -= step

        headers = {} if request.query_params.get("chunked") == "1" else {"Content-Length": str(n)}
        return StreamingResponse(gen(), media_type="application/octet-stream", headers=headers)

    @app.get("/bomb/gzip")
    async def bomb(request: Request) -> Response:
        mib = _int(request, "mib", 1024, 1, 4096)
        if request.query_params.get("nested") == "1":
            return Response(
                nested_gzip_bomb(mib),
                media_type="text/html",
                headers={"Content-Encoding": "gzip, gzip"},
            )
        return StreamingResponse(
            gzip_bomb(mib), media_type="text/html", headers={"Content-Encoding": "gzip"}
        )

    @app.get("/pages/zip_bomb.html.gz")
    async def zip_bomb(request: Request) -> StreamingResponse:
        mib = _int(request, "mib", 1024, 1, 4096)
        return StreamingResponse(
            gzip_bomb(mib), media_type="text/html", headers={"Content-Encoding": "gzip"}
        )

    @app.get("/pages/listing/item-{n}.html")
    async def listing_item(n: int) -> Response:
        if not 1 <= n <= 30:
            return PlainTextResponse("not found", status_code=404)
        return Response(_item_page(n), media_type="text/html; charset=utf-8")

    @app.get("/sequence/{name}")
    async def sequence(name: str) -> Response:
        files = sequences.get(name)
        if not isinstance(files, list):
            return PlainTextResponse("unknown sequence", status_code=404)
        pos = state.sequence_pos.get(name, 0)
        state.sequence_pos[name] = pos + 1
        return _file("pages", str(files[min(pos, len(files) - 1)]))

    @app.get("/feeds/{name}")
    async def feeds(name: str) -> Response:
        if name in GENERATORS:
            return Response(generated_feed(name), media_type="application/rss+xml; charset=utf-8")
        return _file("feeds", name)

    @app.get("/pages/{name}")
    async def pages(name: str) -> Response:
        return _file("pages", name)

    @app.get("/corpus/{name}")
    async def corpus(name: str) -> Response:
        return _file("corpus", name)

    return app


def _file(group: str, name: str) -> Response:
    folder = DIRS[group]
    allowed = {p.name for p in folder.iterdir() if p.is_file() and p.suffix in SERVED_SUFFIXES}
    if name not in allowed:  # also rejects traversal: only listed file names match
        return PlainTextResponse("not found", status_code=404)
    path = folder / name
    media = SPECIAL_TYPES.get(name) or CONTENT_TYPES[path.suffix]
    return Response(path.read_bytes(), media_type=media)


# --- raw listener -----------------------------------------------------------------------


async def _raw_handler(
    state: ServerState, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
        line = head.split(b"\r\n", 1)[0].decode("latin-1")
        method, target, _ = (line.split(" ", 2) + ["", ""])[:3]
        parts = urlsplit(target)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        state.requests.append(RecordedRequest(method, parts.path, parts.query, {}, listener="raw"))
        await _raw_route(parts.path, q, writer)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError, ConnectionError):
        pass
    finally:
        writer.close()


def _num(q: dict[str, str], name: str, default: int, hi: int) -> int:
    return max(0, min(hi, int(q.get(name, default))))


async def _raw_route(path: str, q: dict[str, str], writer: asyncio.StreamWriter) -> None:
    if path in ("/lie/content-length", "/lie/short", "/lie/long"):
        declared, actual = {"/lie/short": (1000, 10), "/lie/long": (10, MIB)}.get(path, (100, 1000))
        declared = _num(q, "declared", declared, MAX_SIZE)
        actual = _num(q, "actual", actual, 64 * MIB)
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n"
            + f"Content-Length: {declared}\r\n\r\n".encode()
        )
        sent = 0
        while sent < actual:
            step = min(actual - sent, 64 * 1024)
            writer.write(b"y" * step)
            await writer.drain()
            sent += step
    elif path == "/raw/slow-headers":
        interval = _num(q, "interval_ms", 500, MAX_DELAY_MS) / 1000
        for byte in b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nX-Slow: " + b"z" * 64:
            writer.write(bytes([byte]))
            await writer.drain()
            await asyncio.sleep(interval)
    elif path == "/raw/hang":
        await asyncio.sleep(_num(q, "seconds", 120, 3600))
    elif path == "/raw/garbage":
        writer.write(b"\x00\xffNOT HTTP AT ALL\r\n\r\n\x16\x03\x01")
    else:
        writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
    await writer.drain()


# --- server wrapper ---------------------------------------------------------------------


class FixtureServer:
    """Start both listeners in a background thread; use as a context manager."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0, raw_port: int = 0) -> None:
        self.host = host
        self.state = ServerState()
        self._sock = self._bind(host, port)
        self._raw_sock = self._bind(host, raw_port)
        self.port = self._sock.getsockname()[1]
        self.raw_port = self._raw_sock.getsockname()[1]
        self.state.port = self.port
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None

    @staticmethod
    def _bind(host: str, port: int) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(128)
        sock.setblocking(False)
        return sock

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def raw_url(self) -> str:
        return f"http://{self.host}:{self.raw_port}"

    def url(self, path: str) -> str:
        return self.base_url + path

    def raw(self, path: str) -> str:
        return self.raw_url + path

    def reset(self) -> None:
        self.state.reset()

    def start(self, timeout: float = 5.0) -> FixtureServer:
        config = uvicorn.Config(
            create_app(self.state), log_level="warning", access_log=False, lifespan="off", ws="none"
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._run, name="fixture-server", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self._server.started:
            if self._error is not None or not self._thread.is_alive():
                raise RuntimeError("fixture server failed to start") from self._error
            if time.monotonic() > deadline:
                raise TimeoutError("fixture server did not start in time")
            time.sleep(0.01)
        return self

    def _run(self) -> None:
        try:
            asyncio.run(self._main())
        except BaseException as exc:  # surfaced by start()
            self._error = exc

    async def _main(self) -> None:
        assert self._server is not None
        raw = await asyncio.start_server(
            lambda r, w: _raw_handler(self.state, r, w), sock=self._raw_sock
        )
        try:
            await self._server.serve(sockets=[self._sock])
        finally:
            raw.close()
            await raw.wait_closed()

    def stop(self, timeout: float = 5.0) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout)
        for sock in (self._sock, self._raw_sock):
            sock.close()

    def __enter__(self) -> FixtureServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the regwatch fixture server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--raw-port", type=int, default=8098)
    args = parser.parse_args(argv)
    with FixtureServer(args.host, args.port, args.raw_port) as server:
        print(f"fixture server: {server.base_url} (raw listener {server.raw_url}); Ctrl-C to stop")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
