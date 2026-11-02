"""Request id and access logging as a pure ASGI middleware.

The ``X-Request-Id`` header is client input: it is reused only when it matches a short safe
pattern, otherwise a new id is generated. The id is bound to structlog's context for the
duration of the request and echoed in the response. Bodies are never read or logged.
"""

from __future__ import annotations

import re
import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

_log = structlog.get_logger("regwatch.access")


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
