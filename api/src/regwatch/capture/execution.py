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

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, cast

from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from regwatch.capture.connectors import api_feed as _api_feed  # noqa: F401 - registers it
from regwatch.capture.connectors import rss as _rss  # noqa: F401 - registers the connector
from regwatch.capture.connectors import web_crawl as _web_crawl  # noqa: F401 - registers it
from regwatch.capture.connectors import web_page as _web_page  # noqa: F401 - registers it
from regwatch.capture.connectors.base import (
    REGISTRY,
    Candidate,
    ConnectorContext,
    ConnectorError,
    JobSettings,
    RawDocument,
)
from regwatch.capture.connectors.config import validate_config, validate_rules
from regwatch.capture.models import CaptureJob, Source
from regwatch.capture.safe_fetch import CaptureFetcher, FetchResult
from regwatch.capture.safe_fetch.policy import FetchRefusedError
from regwatch.core.errors import ProblemError

# Under the worker's soft limit (55 minutes), so a slow run still ends with its outcome and
# manifest instead of being killed and rolled back (finding 1).
RUN_DEADLINE_S = 45 * 60
MAX_ATTEMPTS = 3
RETRY_WAIT_S = 1.0  # first backoff; doubles per attempt, at most 10 s
TRANSIENT = frozenset({"timeout", "connect"})
SKIPPING = frozenset({"robots", "rate-limited"})
# A document the provider does not have in the asked form (EUR-Lex review finding 1): skipped,
# not failed, so the cursor still moves past it.
UNAVAILABLE = frozenset({"unavailable"})
STOPPING = frozenset({"blocked-by-provider", "unreadable-pages", "override-redirect"})
REFUSALS = {
    "robots": "robots.txt does not allow it",
    "rate-limited": "the host is busy; tried again next run",
    "private-address": "the host does not resolve to public addresses only",
    "dns": "the host name could not be resolved",
    "timeout": "the host did not answer in time",
    "connect": "the host could not be reached",
    "tls": "the host's certificate could not be verified",
    "protocol": "the host's answer was not valid HTTP",
    "too-large": "the answer was larger than the size limit",
    "redirects": "the answer redirected too many times",
    "encoding": "the answer's compression was not valid",
    "url": "the address is not valid",
    "scheme": "only http and https addresses are fetched",
    "userinfo": "addresses with a user name or password are not fetched",
}

ContextFactory = Callable[[JobSettings], Awaitable[ConnectorContext]]


@dataclass
class Outcome:
    status: str
    error_class: str | None = None
    error_message: str | None = None
    robots_decision: str | None = None
    items_new: int = 0
    items_changed: int = 0
    items_unchanged: int = 0
    bytes_fetched: int = 0
    cursor: dict[str, Any] | None = None  # the job's new cursor (CP-14), or None to keep it
    cursor_from: dict[str, Any] | None = None  # the cursor the run started from
    # Write the cursor even if the run failed: per-document state that kept every entry it
    # did not update (web listing re-verification R7).
    cursor_on_failure: bool = False
    documents: list[RawDocument] = field(default_factory=list)


def job_settings(job: CaptureJob, source: Source,
                 last_success_at: datetime | None = None) -> JobSettings:  # fmt: skip
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
                       render_js=job.render_js, robots_override=override,
                       last_success_at=last_success_at, cursor=job.cursor)  # fmt: skip


def _transient(exc: BaseException) -> bool:
    return isinstance(exc, FetchRefusedError) and exc.reason in TRANSIENT


def _retrying() -> AsyncRetrying:
    return AsyncRetrying(stop=stop_after_attempt(MAX_ATTEMPTS), reraise=True,
                         wait=wait_exponential(multiplier=RETRY_WAIT_S, max=10),
                         retry=retry_if_exception(_transient))  # fmt: skip


def manifest_key(source_id: str, run_id: uuid.UUID) -> str:
    return f"raw/{source_id}/runs/{run_id}.json"


def _manifest(run_id: uuid.UUID, entries: list[tuple[Candidate, RawDocument]]) -> bytes:
    """What M4 needs to make items: the document and what the feed said about it (finding 4)."""
    rows: list[dict[str, Any]] = [
        {"url": d.url, "final_url": d.final_url, "status": d.status, "body_ref": d.body_ref,
         "mime": d.mime, "fetched_at": d.fetched_at.isoformat(), "text": d.text,
         "title": c.title, "summary": c.summary, "external_id": c.external_id,
         "language": c.language,
         "published_at": c.published_at.isoformat() if c.published_at else None,
         # What the connector learned from the document itself (a page's title and date, and
         # the key of its previous text), and whether it is new or changed (CP-16).
         "change": d.change, "metadata": d.metadata}
        for c, d in entries
    ]  # fmt: skip
    return json.dumps({"run_id": str(run_id), "documents": rows}).encode("utf-8")


class _CountingFetcher:
    """The run's fetcher, counting the bytes of every body fetched (feeds included; finding 5)."""

    def __init__(self, inner: CaptureFetcher) -> None:
        self.inner, self.fetched = inner, 0

    async def fetch(self, url: str, **kwargs: Any) -> FetchResult:
        got = await self.inner.fetch(url, **kwargs)
        self.fetched += len(got.body)
        return got


def _refusal(exc: FetchRefusedError) -> str:
    """Fixed text for a refusal: its detail can quote what a server sent (finding 6)."""
    return REFUSALS.get(exc.reason, f"the fetch was refused ({exc.reason})")


def _robots_answer(exc: FetchRefusedError) -> str:
    return "unreadable" if "could not be read" in exc.detail else "disallowed"


async def run_connector(run_id: uuid.UUID, job: CaptureJob, source: Source,
                        make_context: ContextFactory,
                        last_success_at: datetime | None = None) -> Outcome:  # fmt: skip
    connector = REGISTRY.get(source.kind)
    if connector is None:
        return Outcome("failed", "no-connector", f"no connector runs {source.kind} sources yet")
    try:
        settings = job_settings(job, source, last_success_at)
    except ConnectorError as exc:
        return Outcome("failed", exc.reason, exc.detail)
    base = await make_context(settings)
    counter = _CountingFetcher(base.fetcher)
    ctx = ConnectorContext(fetcher=cast(CaptureFetcher, counter), store=base.store, now=base.now,
                           notes=base.notes, load=base.load)  # fmt: skip
    allowed = "overridden" if settings.robots_override else "allowed"
    entries: list[tuple[Candidate, RawDocument]] = []
    unchanged = 0  # fetched and compared: the same as last time, so not for M4 (CP-16)
    failures = 0
    refused: dict[str, int] = {}  # robots.txt or a busy host refused these pages: not failures
    cut_short = False
    truncated = False  # more was offered than the run took (API feed review 2)
    stopped: tuple[str, str] | None = None  # discovery stopped after documents were fetched (3)
    try:
        async with asyncio.timeout(RUN_DEADLINE_S) as deadline:  # end inside the worker's limit
            async for candidate in connector.discover(settings, ctx):
                taken = len(entries) + unchanged + failures + sum(refused.values())
                if taken >= settings.max_items:
                    truncated = True  # a candidate arrived past the limit: there is more
                    break
                try:
                    async for attempt in _retrying():
                        with attempt:
                            document = await connector.fetch(candidate, settings, ctx)
                    if document.change == "unchanged":
                        unchanged += 1
                    else:
                        entries.append((candidate, document))
                except FetchRefusedError as exc:
                    if exc.reason in SKIPPING:
                        refused[exc.reason] = refused.get(exc.reason, 0) + 1
                    else:
                        failures += 1
                except ConnectorError as exc:
                    if exc.reason in STOPPING:  # a block on one document stops the run (3)
                        raise
                    if exc.reason in UNAVAILABLE:  # the provider has no such document: a skip
                        refused[exc.reason] = refused.get(exc.reason, 0) + 1
                    else:
                        failures += 1
    except TimeoutError:
        if not deadline.expired():  # some other timeout (a store's ETIMEDOUT): not ours (R1)
            raise
        cut_short = True
    except FetchRefusedError as exc:
        if entries:  # a later page failed: keep what was fetched (finding 3)
            stopped = (exc.reason, _refusal(exc))
        elif exc.reason == "robots":  # the feed or page the job starts from
            return Outcome("skipped", "robots", _refusal(exc), robots_decision=_robots_answer(exc),
                           bytes_fetched=counter.fetched)  # fmt: skip
        elif exc.reason == "rate-limited":
            return Outcome("skipped", "rate-limited", _refusal(exc), bytes_fetched=counter.fetched)
        else:
            return Outcome("failed", exc.reason, _refusal(exc), bytes_fetched=counter.fetched)
    except ConnectorError as exc:  # raised after the start was fetched: robots.txt allowed it
        # A stop after documents were handled (fetched, unchanged or failed) keeps what the run
        # learned, the connector's state included (web listing re-verification R1).
        if entries or unchanged or (exc.reason in STOPPING and failures):
            stopped = (exc.reason, exc.detail)
        else:
            return Outcome("failed", exc.reason, exc.detail, robots_decision=allowed,
                           bytes_fetched=counter.fetched)  # fmt: skip
    finish = getattr(connector, "finish", None)
    if finish is not None:  # discovery ended, at its end, a limit or a later error
        await finish(settings, ctx)
    if entries:
        await base.store(manifest_key(settings.source_id, run_id), _manifest(run_id, entries))
    status, error_class, message = _verdict(len(entries) + unchanged, failures, refused, cut_short)
    # Only a connector that resumes from the cursor gets one, and not past failed documents
    # (CP-13/14 review finding 1, low findings): otherwise "continues" would not be true.
    resumes = "resumes" in ctx.notes and failures == 0
    cursor = _cursor(settings.cursor, entries, base.now()) if resumes else None
    # The connector's own state (CP-16): written when every document was fetched, or always for
    # a connector whose state is per document and keeps the old entry of any it did not reach
    # (listing mode; web listing review finding 2).
    per_document = "state-per-document" in ctx.notes
    if ctx.state is not None and (per_document or (failures == 0 and not cut_short)):
        cursor = ctx.state if ctx.state != settings.cursor else None
    if stopped is not None:  # some documents, then discovery failed: partial, with its reason
        status, (error_class, message) = ("partial" if entries or unchanged else "failed"), stopped
    elif status == "success" and (truncated or "truncated" in ctx.notes):
        status, error_class = "partial", "truncated"
        # The next run continues only where a cursor moved forward (CP-14); otherwise it would
        # ask for the same window again (API feed re-verification R1), so the admin must act.
        moved = cursor is not None
        if "state-full" in ctx.notes:  # web crawl re-verification R6
            message = ("the site has more pages than a crawl remembers (5,000); narrow "
                       "allowed_domains or the URL patterns")  # fmt: skip
        elif "crawl-limit" in ctx.notes:  # R7: deeper pages may never be reached; say so
            message = ("the crawl found more pages than one run takes; raise max_pages_per_run "
                       "or narrow allowed_domains or the URL patterns")  # fmt: skip
        elif moved:
            message = ("more documents were offered than one run takes; the next run continues "
                       "where this one stopped")  # fmt: skip
        else:
            message = ("more documents were offered than one run takes; raise the items per run "
                       "or narrow the query")  # fmt: skip
    return Outcome(status, error_class, message,
                   robots_decision=_decision(allowed, refused, len(entries) + failures),
                   items_new=sum(1 for _, d in entries if d.change != "changed"),
                   items_changed=sum(1 for _, d in entries if d.change == "changed"),
                   items_unchanged=unchanged, bytes_fetched=counter.fetched,
                   documents=[doc for _, doc in entries], cursor=cursor,
                   cursor_from=settings.cursor, cursor_on_failure=per_document)  # fmt: skip


def _cursor(current: dict[str, Any] | None, entries: list[tuple[Candidate, RawDocument]],
            now: datetime) -> dict[str, Any] | None:  # fmt: skip
    """The newest publication date among the documents stored, or None when it would not
    move the job's cursor forward (CP-14). A date past tomorrow is held at tomorrow, so one
    record dated 2099 cannot park the cursor beyond every real document."""
    ceiling = (now + timedelta(days=1)).date().isoformat()
    dates = [min(c.published_at.date().isoformat(), ceiling) for c, _ in entries
             if c.published_at]  # fmt: skip
    if not dates:
        return None
    newest = max(dates)
    before = (current or {}).get("publication_date")
    if isinstance(before, str) and before >= newest:
        return None
    return {"publication_date": newest}


def _decision(allowed: str, refused: dict[str, int], others: int) -> str:
    """Every page disallowed is ``disallowed``; some is ``partly-disallowed`` (R2)."""
    if not refused.get("robots"):
        return allowed
    # Any document not refused by robots.txt (fetched, failed, busy or unavailable) makes it
    # partly disallowed (EUR-Lex re-verification R1).
    if others or sum(refused.values()) > refused["robots"]:
        return "partly-disallowed"
    return "disallowed"


def _counts(refused: dict[str, int]) -> str:
    """Each skip reason with its count, such as ``robots 2, unavailable 1`` (R1)."""
    return ", ".join(f"{reason} {n}" for reason, n in sorted(refused.items()) if n)


def _verdict(fetched: int, failures: int, refused: dict[str, int],
             cut_short: bool) -> tuple[str, str | None, str | None]:  # fmt: skip
    """The run's status, error class and message from what happened to its documents."""
    skipped = sum(refused.values())
    total = fetched + failures + skipped
    if cut_short:
        limit = f"the run stopped at its {RUN_DEADLINE_S // 60}-minute limit"
        return ("partial" if fetched else "failed"), "run-deadline", limit
    if failures and not fetched:
        return "failed", "fetch-failed", f"none of {total} documents could be fetched"
    if skipped and not fetched:
        reason = "robots" if refused.get("robots") else sorted(refused)[0]
        return "skipped", reason, f"all {skipped} documents were refused ({_counts(refused)})"
    if failures:
        return "partial", "some-failed", f"{failures} of {total} documents failed"
    if skipped:
        return "success", None, f"{skipped} documents were skipped ({_counts(refused)})"
    return "success", None, None
