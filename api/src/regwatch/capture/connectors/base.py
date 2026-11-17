"""The connector protocol (M3 interfaces; docs/contracts/connectors.yaml ``candidate`` and
``raw_document``).

A connector turns one capture job into candidates (``discover``) and a candidate into a raw
document (``fetch``). It reaches the network only through ``ctx.fetcher``, a ``CaptureFetcher``
(SafeFetcher with robots.txt and per-host rate limits), and stores raw bodies through
``ctx.store``; it never opens a socket itself.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from regwatch.capture.safe_fetch import CaptureFetcher


class ConnectorError(Exception):
    """A source answered with something its connector cannot use; ``reason`` is a stable code
    for ``capture_run.error_class`` and ``detail`` a short message that never quotes content."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Candidate:
    url: str
    title: str | None = None
    published_at: datetime | None = None
    external_id: str | None = None
    summary: str | None = None
    language: str | None = None
    hints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RawDocument:
    url: str
    fetched_at: datetime
    status: int
    body_ref: str  # object store key of the raw body
    mime: str
    final_url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    text: str | None = None  # pre-extracted text, when the connector already has it
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HealthReport:
    status: Literal["unknown", "healthy", "degraded", "unhealthy"]
    detail: str = ""


@dataclass(frozen=True)
class JobSettings:
    """What a connector needs to know about its job (from ``capture_job`` and ``source``)."""

    source_id: str
    kind: str
    config: BaseModel
    rules: BaseModel
    max_items: int = 200
    rate_per_minute: int = 30
    render_js: bool = False
    robots_override: str | None = None  # the admin's recorded reason, or None to obey
    last_success_at: datetime | None = None  # when the last successful run started


@dataclass
class ConnectorContext:
    fetcher: CaptureFetcher
    store: Callable[[str, bytes], Awaitable[None]]  # object store put(key, body)
    now: Callable[[], datetime]
    # What a connector reports beside its candidates, such as "truncated" when it stopped
    # before the source ran out (API feed review finding 2).
    notes: set[str] = field(default_factory=set)


class Connector(Protocol):
    kind: str
    config_schema: type[BaseModel]

    def discover(self, job: JobSettings, ctx: ConnectorContext) -> AsyncIterator[Candidate]: ...

    async def fetch(
        self, candidate: Candidate, job: JobSettings, ctx: ConnectorContext
    ) -> RawDocument: ...

    def health(self, job: JobSettings) -> HealthReport: ...


REGISTRY: dict[str, Connector] = {}


def register(connector: Connector) -> Connector:
    """Add a connector for its ``kind``; one per kind."""
    if connector.kind in REGISTRY:
        raise ValueError(f"a connector for {connector.kind!r} is already registered")
    REGISTRY[connector.kind] = connector
    return connector
