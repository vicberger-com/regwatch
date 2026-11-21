"""Prometheus metrics (M10.1b; REQ-01; BL-146), with prometheus-client (Apache-2.0).

- HTTP latency by method, route template (never the raw path, so ids and searches add no
  series) and status: ``regwatch_http_request_duration_seconds``.
- Business gauges, refreshed every ``REFRESH_S`` from the database and the queue by the API
  process: capture runs in the last 24 hours by outcome, items changed in the last hour, output
  jobs failed in the last 24 hours by kind, sources unhealthy for 24 hours, queue depth.
- Served by a separate listener on ``metrics_port``, bound to ``metrics_bind``
  (127.0.0.1 by default; Compose sets the container's address on the internal network only,
  publishes no port, and the proxy never routes to it). Counts and timings only, never content,
  users or addresses.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
import structlog
from prometheus_client import CollectorRegistry, Gauge, Histogram, start_http_server
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REFRESH_S = 30.0
REGISTRY = CollectorRegistry(auto_describe=True)
_log = structlog.get_logger("regwatch.metrics")

HTTP = Histogram("regwatch_http_request_duration_seconds", "HTTP request latency",
                 ["method", "route", "status"], registry=REGISTRY,
                 buckets=(0.025, 0.05, 0.1, 0.15, 0.3, 0.5, 1, 2, 5, 10))  # fmt: skip
CAPTURE_RUNS = Gauge("regwatch_capture_runs_24h", "Capture runs finished in the last 24 hours",
                     ["status"], registry=REGISTRY)  # fmt: skip
ITEMS_CHANGED = Gauge("regwatch_items_changed_1h", "Items changed in the last hour",
                      registry=REGISTRY)  # fmt: skip
OUTPUTS_FAILED = Gauge("regwatch_outputs_failed_24h", "Output jobs failed in the last 24 hours",
                       ["kind"], registry=REGISTRY)  # fmt: skip
SOURCES_UNHEALTHY = Gauge("regwatch_sources_unhealthy_24h",
                          "Enabled sources without a successful run for 24 hours",
                          registry=REGISTRY)  # fmt: skip
QUEUE_DEPTH = Gauge("regwatch_queue_depth", "Tasks waiting in a queue", ["queue"],
                    registry=REGISTRY)  # fmt: skip
REFRESHED = Gauge("regwatch_metrics_refreshed_timestamp_seconds",
                  "When the business gauges were last refreshed", registry=REGISTRY)  # fmt: skip


def route_of(scope: Scope) -> str:
    """The matched route's template (``/api/v1/items/{id}``), or ``unmatched``."""
    route = scope.get("route")
    return str(getattr(route, "path", "unmatched"))


class MetricsMiddleware:
    """Times every HTTP request (pure ASGI, so streamed responses are timed to their end)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = 500

        async def sending(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, sending)
        finally:
            HTTP.labels(scope.get("method", "GET"), route_of(scope), str(status)).observe(
                time.perf_counter() - start)  # fmt: skip


async def refresh(db: Any, queue_depths: Callable[[], Awaitable[dict[str, int]]]) -> None:  # noqa: ANN401
    """Recompute the business gauges once."""
    from sqlalchemy import text

    rows = (await db.execute(text(
        "SELECT status, count(*) FROM capture_run WHERE finished_at > now() - interval '24 hours'"
        " GROUP BY status"))).all()  # fmt: skip
    CAPTURE_RUNS.clear()
    for status, count in rows:
        CAPTURE_RUNS.labels(str(status)).set(int(count))
    changed = await db.scalar(
        text("SELECT count(*) FROM item WHERE last_changed_at > now() - interval '1 hour'")
    )
    ITEMS_CHANGED.set(int(changed or 0))
    failed = (await db.execute(text(
        "SELECT kind, count(*) FROM output_job WHERE status = 'failed'"
        " AND updated_at > now() - interval '24 hours' GROUP BY kind"))).all()  # fmt: skip
    OUTPUTS_FAILED.clear()
    for kind in ("pdf", "email", "csv", "print"):
        OUTPUTS_FAILED.labels(kind).set(0)
    for kind, count in failed:
        OUTPUTS_FAILED.labels(str(kind)).set(int(count))
    # Unhealthy (M3's health) with no good run for 24 hours: acceptance 4's alert counts these.
    SOURCES_UNHEALTHY.set(int(await db.scalar(text(
        "SELECT count(*) FROM source s WHERE s.enabled AND s.health = 'unhealthy'"
        " AND s.created_at < now() - interval '24 hours' AND NOT EXISTS ("
        " SELECT 1 FROM capture_run r JOIN capture_job j ON j.id = r.job_id"
        " WHERE j.source_id = s.id AND r.status IN ('success', 'partial')"
        " AND r.finished_at > now() - interval '24 hours')")) or 0))  # fmt: skip
    for name, depth in (await queue_depths()).items():
        QUEUE_DEPTH.labels(name).set(depth)
    REFRESHED.set(time.time())


async def refresh_forever(factory: Any, queue_depths: Callable[[], Awaitable[dict[str, int]]]
                          ) -> None:  # noqa: ANN401  # fmt: skip
    """Refresh every ``REFRESH_S``; a failure is logged and tried again, never fatal."""
    while True:
        try:
            async with factory() as db:
                await refresh(db, queue_depths)
        except Exception as exc:  # noqa: BLE001 - metrics never stop the API
            _log.warning("metrics_refresh_failed", error=type(exc).__name__)
        await anyio.sleep(REFRESH_S)


def serve(port: int, bind: str) -> None:
    """Start the metrics listener (a daemon thread)."""
    start_http_server(port, addr=bind, registry=REGISTRY)
    _log.info("metrics_listening", bind=bind, port=port)


async def queue_depths() -> dict[str, int]:
    """Tasks waiting in each Celery queue (a Valkey list per queue)."""
    import redis.asyncio as aioredis

    from regwatch.core.settings import get_settings
    from regwatch.core.worker import QUEUES, broker_url

    client = aioredis.Redis.from_url(broker_url(get_settings()), socket_timeout=2.0,
                                     socket_connect_timeout=2.0)  # fmt: skip
    try:
        return {name: int(await client.llen(name)) for name in QUEUES}
    finally:
        await client.aclose()
