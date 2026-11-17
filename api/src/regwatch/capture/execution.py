"""Running a connector for one capture run (M3 design notes; acceptance 1 and 4).

``run_connector`` turns a job and its source into ``JobSettings``, asks the kind's connector
for candidates, fetches each one, and reports what happened as an ``Outcome``:

- every candidate fetched: ``success``; some: ``partial``; none of several: ``failed``;
- robots.txt disallows the feed or page the job starts from: ``skipped`` with the decision
  recorded (acceptance 4); a host too busy to answer in time: ``skipped`` as ``rate-limited``;
- anything else that stops discovery: ``failed`` with a stable ``error_class``.

A fetch that times out or cannot connect is tried again, at most ``MAX_ATTEMPTS`` times in all
(M3 design notes: failures never retry more than 3 times per run). Refusals (a private address,
robots.txt, a body too large) are never retried.

Every body is stored in the object store; the run's documents are listed in a manifest at
``raw/{source_id}/runs/{run_id}.json``, which M4 reads to make items (ASSUMPTIONS M3).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from regwatch.capture.connectors import rss as _rss  # noqa: F401 - registers the connector
from regwatch.capture.connectors.base import (
    REGISTRY,
    ConnectorContext,
    ConnectorError,
    JobSettings,
    RawDocument,
)
from regwatch.capture.connectors.config import validate_config, validate_rules
from regwatch.capture.models import CaptureJob, Source
from regwatch.capture.safe_fetch.policy import FetchRefusedError
from regwatch.core.errors import ProblemError

MAX_ATTEMPTS = 3
RETRY_WAIT_S = 1.0  # first backoff; doubles per attempt, at most 10 s
TRANSIENT = frozenset({"timeout", "connect"})
SKIPPING = {"robots": "disallowed", "rate-limited": "rate-limited"}

ContextFactory = Callable[[JobSettings], Awaitable[ConnectorContext]]


@dataclass
class Outcome:
    status: str
    error_class: str | None = None
    error_message: str | None = None
    robots_decision: str | None = None
    items_new: int = 0
    bytes_fetched: int = 0
    documents: list[RawDocument] = field(default_factory=list)


def job_settings(job: CaptureJob, source: Source) -> JobSettings:
    """What the connector needs; a stored config that no longer validates is a ``bad-config``
    failure rather than a crash."""
    try:
        config = validate_config(source.kind, source.config)
        rules = validate_rules(job.extraction_rules)
    except ProblemError as exc:
        raise ConnectorError("bad-config", "the stored source settings are not valid") from exc
    override = source.override_reason if source.robots_policy == "override" else None
    return JobSettings(source_id=str(source.id), kind=source.kind, config=config, rules=rules,
                       max_items=job.max_items_per_run, rate_per_minute=job.rate_limit_per_minute,
                       render_js=job.render_js, robots_override=override)  # fmt: skip


def _transient(exc: BaseException) -> bool:
    return isinstance(exc, FetchRefusedError) and exc.reason in TRANSIENT


def _retrying() -> AsyncRetrying:
    return AsyncRetrying(stop=stop_after_attempt(MAX_ATTEMPTS), reraise=True,
                         wait=wait_exponential(multiplier=RETRY_WAIT_S, max=10),
                         retry=retry_if_exception(_transient))  # fmt: skip


def manifest_key(source_id: str, run_id: uuid.UUID) -> str:
    return f"raw/{source_id}/runs/{run_id}.json"


def _manifest(run_id: uuid.UUID, documents: list[RawDocument]) -> bytes:
    rows: list[dict[str, Any]] = [
        {"url": d.url, "final_url": d.final_url, "status": d.status, "body_ref": d.body_ref,
         "mime": d.mime, "fetched_at": d.fetched_at.isoformat(), "text": d.text}
        for d in documents
    ]  # fmt: skip
    return json.dumps({"run_id": str(run_id), "documents": rows}).encode("utf-8")


async def run_connector(run_id: uuid.UUID, job: CaptureJob, source: Source,
                        make_context: ContextFactory) -> Outcome:  # fmt: skip
    connector = REGISTRY.get(source.kind)
    if connector is None:
        return Outcome("failed", "no-connector", f"no connector runs {source.kind} sources yet")
    try:
        settings = job_settings(job, source)
    except ConnectorError as exc:
        return Outcome("failed", exc.reason, exc.detail)
    ctx = await make_context(settings)
    stored = 0
    store = ctx.store

    async def counting_store(key: str, body: bytes) -> None:
        nonlocal stored
        stored += len(body)
        await store(key, body)

    ctx = ConnectorContext(fetcher=ctx.fetcher, store=counting_store, now=ctx.now)
    documents: list[RawDocument] = []
    failures = 0
    try:
        async for candidate in connector.discover(settings, ctx):
            if len(documents) + failures >= settings.max_items:
                break
            try:
                async for attempt in _retrying():
                    with attempt:
                        documents.append(await connector.fetch(candidate, settings, ctx))
            except (FetchRefusedError, ConnectorError):
                failures += 1
    except FetchRefusedError as exc:
        if exc.reason in SKIPPING:
            return Outcome("skipped", exc.reason, exc.detail, robots_decision=SKIPPING[exc.reason])
        return Outcome("failed", exc.reason, exc.detail)
    except ConnectorError as exc:
        return Outcome("failed", exc.reason, exc.detail)
    if documents:
        await counting_store(manifest_key(settings.source_id, run_id),
                             _manifest(run_id, documents))  # fmt: skip
    if failures and not documents:
        return Outcome("failed", "fetch-failed", f"none of {failures} documents could be fetched",
                       bytes_fetched=stored)  # fmt: skip
    status = "partial" if failures else "success"
    message = f"{failures} of {failures + len(documents)} documents failed" if failures else None
    decision = "overridden" if settings.robots_override else "allowed"
    return Outcome(status, "some-failed" if failures else None, message, robots_decision=decision,
                   items_new=len(documents), bytes_fetched=stored, documents=documents)  # fmt: skip
