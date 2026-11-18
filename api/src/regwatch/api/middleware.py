"""Request id and access logging as a pure ASGI middleware.

The ``X-Request-Id`` header is client input: it is reused only when it matches a short safe
pattern, otherwise a new id is generated. The id is bound to structlog's context for the
duration of the request and echoed in the response. Bodies are never read or logged.
"""

from __future__ import annotations

import json
import re
import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

_log = structlog.get_logger("regwatch.access")

MAX_BODY_BYTES = 2 * 1024 * 1024  # 8.2 request limit; uploads get their own caps when they land
# Upload routes with a larger cap (8.2 allows uploads up to 25 MB): the method, the path under
# the API prefix, and the cap. CP-17: a manual source's document, 10 MB and the multipart frame.
UPLOADS = ((b"POST", re.compile(r"/api/v1/sources/[0-9a-fA-F-]{36}/documents"),
            10 * 1024 * 1024 + 64 * 1024),)  # fmt: skip


def _limit(scope: Scope, default: int) -> int:
    method = scope.get("method", "").encode()
    path = scope.get("path", "")
    for allowed, pattern, cap in UPLOADS:
        if method == allowed and pattern.fullmatch(path):
            return cap
    return default


class BodySizeLimitMiddleware:
    """Refuse request bodies over ``MAX_BODY_BYTES`` with 413 before anything parses them.

    FastAPI reads and decodes a JSON body before route dependencies run, so this limit sits
    in front of the session gate (review finding 3). ``Content-Length`` is checked first;
    chunked bodies are counted as they arrive.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = _limit(scope, self.max_bytes)
        declared = next((v for k, v in scope["headers"] if k == b"content-length"), None)
        if declared is not None and (not declared.isdigit() or int(declared) > limit):
            await self._refuse(scope, send, limit)
            return
        seen = 0
        started = refused = False

        async def counting_receive() -> Message:
            nonlocal seen, refused
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit and not refused:
                    refused = True
                    if not started:
                        await self._refuse(scope, send, limit)
                    # The app sees a disconnect and stops reading; its answer is dropped.
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if refused:
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, counting_receive, tracking_send)

    async def _refuse(self, scope: Scope, send: Send, limit: int) -> None:
        body = {"type": "https://regwatch/errors/payload-too-large", "title": "Content Too Large",
                "status": 413, "detail": f"Request bodies are limited to {limit} bytes.",
                "instance": scope.get("path", "")}  # fmt: skip
        rid = structlog.contextvars.get_contextvars().get("request_id")
        if rid:
            body["request_id"] = rid
        payload = json.dumps(body).encode()
        headers = [
            (b"content-type", b"application/problem+json"),
            (b"content-length", str(len(payload)).encode()),
            (b"connection", b"close"),
        ]
        await send({"type": "http.response.start", "status": 413, "headers": headers})
        await send({"type": "http.response.body", "body": payload})


def resolve_request_id(raw: str | None) -> str:
    if raw and _SAFE_ID.match(raw):
        return raw
    return uuid.uuid4().hex


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw = next(
            (v.decode("latin-1") for k, v in scope["headers"] if k == REQUEST_ID_HEADER.encode()),
            None,
        )
        request_id = resolve_request_id(raw)
        started = time.perf_counter()
        status_code = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_id)
            finally:
                _log.info(
                    "request",
                    method=scope["method"],
                    path=scope["path"],
                    status=status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )
