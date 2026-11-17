"""The dry run behind ``POST /sources/{id}/test`` (CP-13; screens.md: Test).

Workers do all outbound fetching (architecture 3.1), so the API never runs a connector. The route
audits the request, publishes ``capture.dry_run(source_id, request_id)`` and waits for the
worker's answer in Valkey under ``regwatch:dry-run:{request_id}``, for at most ``WAIT_S``. The
worker runs only the connector's discovery: it stores nothing, records no run and changes no
health, and answers with at most ``MAX_CANDIDATES`` candidates, the robots.txt decision and
warnings. Each user may start ``RATE_PER_MINUTE`` dry runs a minute.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture.connectors.base import REGISTRY, ConnectorContext, ConnectorError
from regwatch.capture.execution import ContextFactory, job_settings
from regwatch.capture.models import CaptureJob, Source
from regwatch.capture.safe_fetch.policy import FetchRefusedError
from regwatch.capture.schemas import SourceTestResult
from regwatch.core.errors import ProblemError
from regwatch.core.services import audit
from regwatch.identity.services import Principal

MAX_CANDIDATES = 5
WAIT_S = 30.0
POLL_S = 0.5
RESULT_TTL_S = 120
DISCOVERY_DEADLINE_S = 25.0  # inside WAIT_S, so the worker answers before the API gives up
RATE_PER_MINUTE = 6
KEY = "regwatch:dry-run:{request_id}"
# Set by the API while it waits; a worker that finds it gone skips the request, so a test the API
# has given up on never fetches the source for nobody (CP-13/14 review finding 3).
PENDING_KEY = "regwatch:dry-run-pending:{request_id}"
RATE_KEY = "regwatch:dry-run-rate:{user_id}"

Publish = Callable[[uuid.UUID, uuid.UUID], Awaitable[None]]
_log = structlog.get_logger("regwatch.capture.dryrun")


class Valkey(Protocol):
    async def get(self, name: str) -> bytes | None: ...
    async def set(self, name: str, value: str, ex: int, nx: bool = False) -> Any: ...
    async def delete(self, name: str) -> Any: ...
    async def incr(self, name: str) -> int: ...
    async def expire(self, name: str, time: int) -> Any: ...
    async def exists(self, *names: str) -> int: ...


async def _no_store(key: str, body: bytes) -> None:
    raise RuntimeError("a dry run stores nothing")


async def preview(job: CaptureJob, source: Source, make_context: ContextFactory) -> dict[str, Any]:
    """The worker's side: the first candidates of the source, nothing stored."""
    connector = REGISTRY.get(source.kind)
    if connector is None:
        return {"candidates": [], "robots_decision": "unknown",
                "warnings": [f"no connector runs {source.kind} sources yet"]}  # fmt: skip
    try:
        settings = job_settings(job, source)
    except ConnectorError as exc:
        return {"candidates": [], "robots_decision": "unknown", "warnings": [exc.detail]}
    base = await make_context(settings)
    ctx = ConnectorContext(fetcher=base.fetcher, store=_no_store, now=base.now)
    found: list[dict[str, Any]] = []
    warnings: list[str] = []
    decision = "overridden" if settings.robots_override else "allowed"
    try:
        async with asyncio.timeout(DISCOVERY_DEADLINE_S):
            async for c in connector.discover(settings, ctx):
                found.append({"url": c.url, "title": c.title, "external_id": c.external_id,
                              "published_at": c.published_at.isoformat() if c.published_at
                              else None})  # fmt: skip
                if len(found) >= MAX_CANDIDATES:
                    break
    except TimeoutError:
        warnings.append(f"discovery took longer than {DISCOVERY_DEADLINE_S:g} s")
    except FetchRefusedError as exc:
        if exc.reason == "robots":
            decision = "unreadable" if "could not be read" in exc.detail else "disallowed"
        warnings.append(f"the fetch was refused ({exc.reason})")  # the reason, never the detail
    except ConnectorError as exc:
        warnings.append(f"{exc.reason}: {exc.detail}")
    if not found and not warnings:
        warnings.append("the source offered no candidates")
    return {"candidates": found, "robots_decision": decision, "warnings": warnings}


async def run_on_worker(db: AsyncSession, source_id: uuid.UUID, request_id: uuid.UUID,
                        make_context: ContextFactory, valkey: Valkey) -> None:  # fmt: skip
    """``capture.dry_run``: answer the request in Valkey, unless the API stopped waiting."""
    if not await valkey.exists(PENDING_KEY.format(request_id=request_id)):
        return
    try:
        result = await _answer(db, source_id, make_context)
    except Exception as exc:  # noqa: BLE001 - always answer, so the admin is not left at a 504
        _log.exception("capture_dry_run_failed", source_id=str(source_id))
        failed = f"the test failed on the worker ({type(exc).__name__})"
        result = {"candidates": [], "robots_decision": "unknown", "warnings": [failed]}
    await valkey.set(KEY.format(request_id=request_id), json.dumps(result), ex=RESULT_TTL_S)


async def _answer(db: AsyncSession, source_id: uuid.UUID,
                  make_context: ContextFactory) -> dict[str, Any]:  # fmt: skip
    source = await db.scalar(select(Source).where(Source.id == source_id))
    job = await db.scalar(select(CaptureJob).where(CaptureJob.source_id == source_id))
    # Nothing to write: end the transaction so none is held while fetching. Detach the rows
    # first, or the rollback expires them and reading them later would need the database.
    for row in (source, job):
        if row is not None:
            db.expunge(row)
    await db.rollback()
    if source is None or job is None:
        return {"candidates": [], "robots_decision": "unknown",
                "warnings": ["the source no longer exists"]}  # fmt: skip
    return await preview(job, source, make_context)


Sleep = Callable[[float], Awaitable[None]]


async def request(db: AsyncSession, source_id: uuid.UUID, principal: Principal, ip: str | None,
                  publish: Publish, valkey: Valkey,
                  sleep: Sleep = asyncio.sleep) -> SourceTestResult:  # fmt: skip
    """The API's side of ``POST /sources/{id}/test``."""
    source = await db.scalar(select(Source.id).where(Source.id == source_id))
    if source is None:
        raise ProblemError(404, "not-found", "No such source.")
    try:
        return await _ask(db, source_id, principal, ip, publish, valkey, sleep)
    except (ConnectionError, TimeoutError, OSError) as exc:  # Valkey unreachable or slow
        raise ProblemError(503, "queue-unavailable",
                           "The test could not be run now; try again.") from exc  # fmt: skip


async def _ask(db: AsyncSession, source_id: uuid.UUID, principal: Principal, ip: str | None,
               publish: Publish, valkey: Valkey, sleep: Sleep) -> SourceTestResult:  # fmt: skip
    rate_key = RATE_KEY.format(user_id=principal.user.id)
    # The expiry is set before the count, so the counter can never be left without one and
    # lock a user out (CP-13/14 review, low finding).
    await valkey.set(rate_key, "0", ex=60, nx=True)
    count = await valkey.incr(rate_key)
    if count > RATE_PER_MINUTE:
        busy = f"At most {RATE_PER_MINUTE} tests a minute; try again shortly."
        raise ProblemError(429, "rate-limited", busy, headers={"Retry-After": "60"})
    request_id = uuid.uuid4()
    audit(db, "source.test", "source", source_id, actor=principal.user.id, ip=ip,
          after={"request_id": str(request_id)})  # fmt: skip
    await db.commit()
    pending = PENDING_KEY.format(request_id=request_id)
    await valkey.set(pending, "1", ex=int(WAIT_S))
    try:
        await publish(source_id, request_id)
    except Exception:  # noqa: BLE001 - any broker failure means the same here
        raise ProblemError(503, "queue-unavailable",
                           "The test could not be queued; try again.") from None  # fmt: skip
    key = KEY.format(request_id=request_id)
    deadline = asyncio.get_running_loop().time() + WAIT_S  # by time, not by loop count
    try:
        while asyncio.get_running_loop().time() < deadline:
            raw = await valkey.get(key)
            if raw is not None:
                await valkey.delete(key)
                return SourceTestResult.model_validate(json.loads(raw))
            await sleep(POLL_S)
    finally:
        await valkey.delete(pending)  # given up or answered: a late worker skips it
    raise ProblemError(504, "worker-timeout",
                       f"No worker answered within {WAIT_S:g} s; try again.")  # fmt: skip
