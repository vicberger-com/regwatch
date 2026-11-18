"""Running a connector for a capture run (capture/execution.py; M3 acceptance 4)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest

from regwatch.capture import execution
from regwatch.capture.connectors.base import (
    REGISTRY,
    Candidate,
    ConnectorContext,
    ConnectorError,
    HealthReport,
    JobSettings,
    RawDocument,
)
from regwatch.capture.connectors.config import RssConfig
from regwatch.capture.models import CaptureJob, Source
from regwatch.capture.runs import clean_error
from regwatch.capture.safe_fetch import FetchRefusedError, FetchResult

RUN = uuid.UUID("01930000-0000-7000-8000-000000000001")
SOURCE = uuid.UUID(int=7)
NOW = datetime(2026, 11, 17, tzinfo=UTC)


class Fetcher:
    """Stands in for CaptureFetcher: answers every URL, or raises what a test queued for it."""

    def __init__(self, fail: dict[str, list[Exception]] | None = None) -> None:
        self.fail = fail or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def fetch(self, url: str, **kwargs: Any) -> FetchResult:
        self.calls.append((url, kwargs))
        errors = self.fail.get(url, [])
        if errors:
            raise errors.pop(0)
        return FetchResult(url, 200, {"content-type": "text/html"}, b"<p>" + url.encode() + b"</p>")


class Fake:
    """A connector that discovers the given URLs and fetches each through ``ctx.fetcher``."""

    kind = "rss"
    config_schema = RssConfig

    def __init__(self, urls: list[str], discover_error: Exception | None = None) -> None:
        self.urls, self.discover_error = urls, discover_error

    async def discover(self, job: JobSettings, ctx: ConnectorContext) -> AsyncIterator[Candidate]:
        await ctx.fetcher.fetch("https://e.org/feed", rate_per_minute=job.rate_per_minute,
                                robots_override=job.robots_override)  # fmt: skip
        if self.discover_error is not None:
            raise self.discover_error
        for url in self.urls:
            yield Candidate(url=url, title=f"T {url}", external_id=url, language="en",
                            published_at=NOW)  # fmt: skip

    async def fetch(self, candidate: Candidate, job: JobSettings,
                    ctx: ConnectorContext) -> RawDocument:  # fmt: skip
        got = await ctx.fetcher.fetch(candidate.url, rate_per_minute=job.rate_per_minute,
                                      robots_override=job.robots_override)  # fmt: skip
        key = f"raw/{job.source_id}/{abs(hash(candidate.url))}"
        await ctx.store(key, got.body)
        return RawDocument(url=candidate.url, fetched_at=ctx.now(), status=200, body_ref=key,
                           mime="text/html")  # fmt: skip

    def health(self, job: JobSettings) -> HealthReport:
        return HealthReport("unknown")


def rows(config: dict[str, Any] | None = None, policy: str = "respect", reason: str | None = None,
         max_items: int = 200) -> tuple[CaptureJob, Source]:  # fmt: skip
    config = config if config is not None else {"feed_url": "https://e.org/f"}
    source = Source(id=SOURCE, kind="rss", robots_policy=policy, config=config,
                    override_reason=reason)  # fmt: skip
    job = CaptureJob(max_items_per_run=max_items, rate_limit_per_minute=30, render_js=False,
                     extraction_rules={})  # fmt: skip
    return job, source


class Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(execution, "RETRY_WAIT_S", 0.0)
        self.monkeypatch = monkeypatch
        self.stored: dict[str, bytes] = {}
        self.fetcher = Fetcher()

    def factory(self) -> execution.ContextFactory:
        async def store(key: str, body: bytes) -> None:
            self.stored[key] = body

        async def make(job: JobSettings) -> ConnectorContext:
            return ConnectorContext(fetcher=self.fetcher, store=store,  # type: ignore[arg-type]
                                    now=lambda: NOW)  # fmt: skip

        return make

    async def run(self, connector: Fake | None, **kw: Any) -> execution.Outcome:
        if connector is None:
            self.monkeypatch.delitem(REGISTRY, "rss")
        else:
            self.monkeypatch.setitem(REGISTRY, "rss", connector)
        job, source = rows(**kw)
        return await execution.run_connector(RUN, job, source, self.factory())

    def manifest(self) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(self.stored[execution.manifest_key(str(SOURCE), RUN)])
        return loaded


@pytest.fixture
def h(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(monkeypatch)


async def test_every_document_fetched_is_a_success(h: Harness) -> None:
    got = await h.run(Fake(["https://e.org/a", "https://e.org/b"]))
    assert (got.status, got.items_new, got.robots_decision) == ("success", 2, "allowed")
    rows = h.manifest()["documents"]
    assert [d["url"] for d in rows] == ["https://e.org/a", "https://e.org/b"]
    # Review finding 4: what the feed said about each entry travels with it to M4.
    assert rows[0]["title"] == "T https://e.org/a" and rows[0]["language"] == "en"
    assert rows[0]["external_id"] == "https://e.org/a" and rows[0]["published_at"]
    # Finding 5: the bytes fetched, feed included; not what was stored.
    fetched = sum(len(b"<p>" + u.encode() + b"</p>") for u, _ in h.fetcher.calls)
    assert got.bytes_fetched == fetched


async def test_transient_failures_are_retried_at_most_three_times(h: Harness) -> None:
    slow, gone = FetchRefusedError("timeout", "slow"), FetchRefusedError("connect", "no")
    h.fetcher.fail = {"https://e.org/a": [slow], "https://e.org/b": [gone, gone, gone, gone]}
    got = await h.run(Fake(["https://e.org/a", "https://e.org/b"]))
    urls = [u for u, _ in h.fetcher.calls]
    assert urls.count("https://e.org/a") == 2 and urls.count("https://e.org/b") == 3
    assert (got.status, got.items_new, got.error_class) == ("partial", 1, "some-failed")


@pytest.mark.parametrize("reason", ["private-address", "tls", "protocol", "too-large"])
async def test_refusals_are_not_retried(h: Harness, reason: str) -> None:
    h.fetcher.fail = {"https://e.org/a": [FetchRefusedError(reason, "server said <x>")]}
    got = await h.run(Fake(["https://e.org/a"]))
    assert [u for u, _ in h.fetcher.calls].count("https://e.org/a") == 1
    # One document and it failed: the run names its reason (manual upload review finding 5).
    assert (got.status, got.error_class) == ("failed", reason)
    assert "<x>" not in (got.error_message or "")  # fixed text, never the server's
    assert execution.manifest_key(str(SOURCE), RUN) not in h.stored


@pytest.mark.parametrize(
    ("error", "status", "error_class", "decision"),
    [(FetchRefusedError("robots", "robots.txt of e.org disallows it"), "skipped", "robots",
      "disallowed"),
     (FetchRefusedError("robots", "e.org robots.txt could not be read, so nothing is fetched"),
      "skipped", "robots", "unreadable"),
     (FetchRefusedError("rate-limited", "busy"), "skipped", "rate-limited", None),
     (FetchRefusedError("timeout", "slow"), "failed", "timeout", None)],
)  # fmt: skip
async def test_the_start_is_refused(
    h: Harness, error: Exception, status: str, error_class: str, decision: str | None
) -> None:
    """Acceptance 4; review finding 7: only robots.txt answers are robots decisions."""
    h.fetcher.fail = {"https://e.org/feed": [error]}
    got = await h.run(Fake(["https://e.org/a"]))
    assert (got.status, got.error_class, got.robots_decision) == (status, error_class, decision)


async def test_a_feed_that_cannot_be_used_was_still_allowed(h: Harness) -> None:
    got = await h.run(Fake([], discover_error=ConnectorError("unsafe-feed", "a DOCTYPE")))
    assert (got.status, got.error_class, got.robots_decision) == ("failed", "unsafe-feed",
                                                                   "allowed")  # fmt: skip
    assert got.bytes_fetched > 0


async def test_refused_pages_are_skips_not_failures(h: Harness) -> None:
    """Finding 3: robots.txt allowing the feed but not some pages is not a source failure."""
    no = FetchRefusedError("robots", "disallowed")
    h.fetcher.fail = {"https://e.org/b": [no]}
    some = await h.run(Fake(["https://e.org/a", "https://e.org/b"]))
    assert (some.status, some.robots_decision, some.items_new) == ("success", "partly-disallowed",
                                                                   1)  # fmt: skip
    h.fetcher.fail = {"https://e.org/a": [no], "https://e.org/b": [FetchRefusedError(
        "rate-limited", "busy")]}  # fmt: skip
    none = await h.run(Fake(["https://e.org/a", "https://e.org/b"]))
    assert (none.status, none.error_class) == ("skipped", "robots")
    h.fetcher.fail = {"https://e.org/a": [FetchRefusedError("rate-limited", "busy")]}
    busy = await h.run(Fake(["https://e.org/a"]))
    assert (busy.status, busy.error_class) == ("skipped", "rate-limited")


async def test_a_run_ends_at_its_deadline_with_what_it_has(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 1: a slow run ends inside the worker's limit, keeps its documents, and still
    writes its manifest."""
    import asyncio

    class Slow(Fake):
        async def fetch(self, candidate: Candidate, job: JobSettings,
                        ctx: ConnectorContext) -> RawDocument:  # fmt: skip
            if candidate.url.endswith("/b"):
                await asyncio.sleep(5)
            return await super().fetch(candidate, job, ctx)

    monkeypatch.setattr(execution, "RUN_DEADLINE_S", 0.3)
    got = await h.run(Slow(["https://e.org/a", "https://e.org/b"]))
    assert (got.status, got.error_class, got.items_new) == ("partial", "run-deadline", 1)
    assert len(h.manifest()["documents"]) == 1
    nothing = await h.run(Slow(["https://e.org/b"]))
    assert (nothing.status, nothing.error_class) == ("failed", "run-deadline")


async def test_the_override_reason_reaches_the_fetcher_only_when_overriding(h: Harness) -> None:
    """Finding 14: the reason is passed on for an override, and a stale one is ignored."""
    over = await h.run(Fake(["https://e.org/a"]), policy="override", reason="Owner agreed")
    assert over.robots_decision == "overridden"
    assert {kw["robots_override"] for _, kw in h.fetcher.calls} == {"Owner agreed"}
    h.fetcher.calls.clear()
    await h.run(Fake(["https://e.org/a"]), policy="respect", reason="stale")
    assert {kw["robots_override"] for _, kw in h.fetcher.calls} == {None}


async def test_limits_bad_config_and_missing_connectors(h: Harness) -> None:
    got = await h.run(Fake([f"https://e.org/{n}" for n in range(10)]), max_items=3)
    assert got.items_new == 3
    bad = await h.run(Fake([]), config={"feed_url": "not a url"})
    assert (bad.status, bad.error_class) == ("failed", "bad-config")
    none = await h.run(None)
    assert (none.status, none.error_class) == ("failed", "no-connector")


async def test_an_empty_feed_is_a_success_with_nothing_new(h: Harness) -> None:
    got = await h.run(Fake([]))
    assert (got.status, got.items_new, got.error_message) == ("success", 0, None)
    assert h.stored == {}


def test_refusal_messages_are_fixed_text() -> None:
    """Finding 6: a refusal's detail can quote a server; the run record never does."""
    exc = FetchRefusedError("protocol", "h11: illegal header line b'secret: token'")
    assert "secret" not in execution._refusal(exc)
    assert "other" in execution._refusal(FetchRefusedError("other", "x"))


@pytest.mark.parametrize(
    ("message", "expected"),
    [("https://user:pw@example.org/secret?token=abc failed", "https://example.org/… failed"),
     ("see http://[bad/ and ftp://h.example/x", "see <url> and ftp://h.example/…"),
     ("no url\nhere\x00", "no url here")],
)  # fmt: skip
def test_error_messages_keep_only_scheme_and_host(message: str, expected: str) -> None:
    """BL-90 (h)."""
    assert clean_error(message) == expected


def test_the_user_agent_names_the_contact() -> None:
    from regwatch.capture.tasks import user_agent

    assert user_agent("regwatch/{version} (+{contact_email})", "ops@example.org") == (
        "regwatch/0.1.0 (+ops@example.org)")  # fmt: skip
    assert user_agent("regwatch/{version} (+{contact_email})", "") == "regwatch/0.1.0"
    assert user_agent("x\r\nInjected: 1 {contact_email}", "a@b") == "xInjected: 1 a@b"
    assert user_agent("\x00", "") == "regwatch"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, 64 * 1024), (-5, 64 * 1024), (10**12, 50 * 1024 * 1024), ("x", 10 * 1024 * 1024),
     (None, 10 * 1024 * 1024), (2_000_000, 2_000_000)],
)  # fmt: skip
def test_the_body_cap_setting_is_bounded(value: Any, expected: int) -> None:
    """Finding 8."""
    from regwatch.capture.tasks import body_cap

    assert body_cap(value) == expected


async def test_only_the_run_deadline_counts_as_the_deadline(h: Harness) -> None:
    """Re-verification R1: a store's own timeout (ETIMEDOUT is a TimeoutError) is not the
    deadline; it propagates, and the run ends as internal-error in runs.execute."""

    class TimesOut(Fake):
        async def fetch(self, candidate: Candidate, job: JobSettings,
                        ctx: ConnectorContext) -> RawDocument:  # fmt: skip
            raise TimeoutError("ETIMEDOUT")

    with pytest.raises(TimeoutError):
        await h.run(TimesOut(["https://e.org/a"]))


async def test_every_page_disallowed_is_disallowed(h: Harness) -> None:
    """Re-verification R2."""
    no = FetchRefusedError("robots", "disallowed")
    h.fetcher.fail = {"https://e.org/a": [no], "https://e.org/b": [no]}
    got = await h.run(Fake(["https://e.org/a", "https://e.org/b"]))
    assert (got.status, got.robots_decision) == ("skipped", "disallowed")


async def test_a_run_that_took_less_than_was_offered_is_partial(h: Harness) -> None:
    """API feed review 2: the item limit, or a connector that stopped early, is partial."""
    got = await h.run(Fake([f"https://e.org/{n}" for n in range(5)]), max_items=3)
    assert (got.status, got.error_class, got.items_new) == ("partial", "truncated", 3)
    # CP-13/14 review finding 1: this connector does not resume from a cursor (as RSS), so it
    # gets none and the message asks the admin to act.
    assert got.cursor is None and "raise the items per run" in (got.error_message or "")

    class Resumes(Fake):
        async def discover(self, job: JobSettings,
                           ctx: ConnectorContext) -> AsyncIterator[Candidate]:  # fmt: skip
            ctx.notes.add("resumes")
            async for c in super().discover(job, ctx):
                yield c

    moving = await h.run(Resumes([f"https://e.org/{n}" for n in range(5)]), max_items=3)
    assert "continues where this one stopped" in (moving.error_message or "")
    assert moving.cursor == {"publication_date": NOW.date().isoformat()}
    h.fetcher.fail = {"https://e.org/1": [FetchRefusedError("too-large", "big")]}
    failed = await h.run(Resumes([f"https://e.org/{n}" for n in range(5)]), max_items=3)
    assert failed.cursor is None  # not past a document that failed (review, low finding)
    h.fetcher.fail = {}

    class Undated(Fake):
        async def discover(self, job: JobSettings,
                           ctx: ConnectorContext) -> AsyncIterator[Candidate]:  # fmt: skip
            for url in self.urls:
                yield Candidate(url=url)

    stuck = await h.run(Undated([f"https://e.org/{n}" for n in range(5)]), max_items=3)
    # Re-verification R1: no dates, no cursor: the admin must act.
    assert stuck.cursor is None and "raise the items per run" in (stuck.error_message or "")

    class Stops(Fake):
        async def discover(self, job: JobSettings,
                           ctx: ConnectorContext) -> AsyncIterator[Candidate]:  # fmt: skip
            async for c in super().discover(job, ctx):
                yield c
            ctx.notes.add("truncated")

    stopped = await h.run(Stops(["https://e.org/a"]))
    assert (stopped.status, stopped.error_class) == ("partial", "truncated")
    exact = await h.run(Fake([f"https://e.org/{n}" for n in range(3)]), max_items=3)
    assert exact.status == "success"  # exactly the limit, nothing more offered


async def test_a_later_page_failing_keeps_what_was_fetched(h: Harness) -> None:
    """API feed review 3: page 1's documents are kept, with a manifest, as a partial run."""

    class FailsLater(Fake):
        def __init__(self, error: Exception) -> None:
            super().__init__(["https://e.org/a", "https://e.org/b"])
            self.error = error

        async def discover(self, job: JobSettings,
                           ctx: ConnectorContext) -> AsyncIterator[Candidate]:  # fmt: skip
            async for c in super().discover(job, ctx):
                yield c
            raise self.error

    for error, reason in ((ConnectorError("malformed-answer", "page 2"), "malformed-answer"),
                          (FetchRefusedError("timeout", "slow"), "timeout")):  # fmt: skip
        h.stored.clear()
        got = await h.run(FailsLater(error))
        assert (got.status, got.error_class, got.items_new) == ("partial", reason, 2)
        assert len(h.manifest()["documents"]) == 2


async def test_the_connector_gets_the_last_successful_run(h: Harness) -> None:
    """API feed review 1: incremental windows start from the last success, not the last run."""
    seen: list[datetime | None] = []

    class Records(Fake):
        async def discover(self, job: JobSettings,
                           ctx: ConnectorContext) -> AsyncIterator[Candidate]:  # fmt: skip
            seen.append(job.last_success_at)
            async for c in super().discover(job, ctx):
                yield c

    h.monkeypatch.setitem(REGISTRY, "rss", Records([]))
    job, source = rows()
    job.last_run_at = datetime(2026, 11, 16, tzinfo=UTC)  # a failed run, more recent
    await execution.run_connector(RUN, job, source, h.factory(), NOW)
    assert seen == [NOW]


def test_the_cursor_only_moves_forward() -> None:
    """CP-14."""
    later = Candidate(url="https://e.org/a", published_at=datetime(2026, 11, 10, tzinfo=UTC))
    doc = RawDocument(url="u", fetched_at=NOW, status=200, body_ref="k", mime="text/html")
    assert execution._cursor(None, [(later, doc)], NOW) == {"publication_date": "2026-11-10"}
    assert execution._cursor({"publication_date": "2026-11-12"}, [(later, doc)], NOW) is None
    assert execution._cursor(None, [], NOW) is None
    future = Candidate(url="https://e.org/f", published_at=datetime(2099, 1, 1, tzinfo=UTC))
    held = execution._cursor(None, [(future, doc)], NOW)  # held at tomorrow (review, low)
    assert held == {"publication_date": "2026-11-18"}


class Raises(Fake):
    """Fetches as Fake does, but raises the given connector error for some URLs."""

    def __init__(self, urls: list[str], errors: dict[str, ConnectorError]) -> None:
        super().__init__(urls)
        self.errors = errors

    async def discover(self, job: JobSettings, ctx: ConnectorContext) -> AsyncIterator[Candidate]:
        ctx.notes.add("resumes")
        async for c in super().discover(job, ctx):
            yield c

    async def fetch(self, candidate: Candidate, job: JobSettings,
                    ctx: ConnectorContext) -> RawDocument:  # fmt: skip
        if candidate.url in self.errors:
            raise self.errors[candidate.url]
        return await super().fetch(candidate, job, ctx)


async def test_a_document_the_provider_does_not_have_is_a_skip(h: Harness) -> None:
    """EUR-Lex review finding 1: it does not fail the run, and the cursor still moves."""
    gone = ConnectorError("unavailable", "Cellar has no such document (HTTP 404)")
    got = await h.run(Raises(["https://e.org/a", "https://e.org/b"], {"https://e.org/b": gone}))
    assert (got.status, got.items_new, got.error_class) == ("success", 1, None)
    assert got.cursor == {"publication_date": NOW.date().isoformat()}
    assert got.error_message == "1 documents were skipped (unavailable 1)"
    none = await h.run(Raises(["https://e.org/a"], {"https://e.org/a": gone}))
    assert (none.status, none.error_class) == ("skipped", "unavailable")
    # Re-verification R1: with robots refusals too, each reason is counted and some pages were
    # not disallowed, so robots.txt partly disallowed the run.
    no = FetchRefusedError("robots", "disallowed")
    h.fetcher.fail = {"https://e.org/b": [no], "https://e.org/c": [no]}
    mixed = await h.run(Raises([f"https://e.org/{x}" for x in "abc"], {"https://e.org/a": gone}))
    outcome = (mixed.status, mixed.error_class, mixed.robots_decision)
    assert outcome == ("skipped", "robots", "partly-disallowed")
    assert mixed.error_message == "all 3 documents were refused (robots 2, unavailable 1)"


async def test_a_block_on_one_document_stops_the_run(h: Harness) -> None:
    """EUR-Lex review finding 3: no request follows the first challenge."""
    block = ConnectorError("blocked-by-provider", "the provider's firewall refused the request")
    urls = [f"https://e.org/{n}" for n in range(5)]
    got = await h.run(Raises(urls, {"https://e.org/1": block, "https://e.org/2": block}))
    assert (got.status, got.error_class, got.items_new) == ("partial", "blocked-by-provider", 1)
    assert [u for u, _ in h.fetcher.calls] == ["https://e.org/feed", "https://e.org/0"]
    first = await h.run(Raises(urls, {"https://e.org/0": block}))
    assert (first.status, first.error_class) == ("failed", "blocked-by-provider")


class Compares(Fake):
    """Marks documents as the test says, and keeps its own state in the cursor (CP-16)."""

    def __init__(self, urls: list[str], changes: dict[str, str]) -> None:
        super().__init__(urls)
        self.changes = changes

    async def fetch(self, candidate: Candidate, job: JobSettings,
                    ctx: ConnectorContext) -> RawDocument:  # fmt: skip
        doc = await super().fetch(candidate, job, ctx)
        ctx.state = {"content_hash": "h2"}
        return RawDocument(**{**doc.__dict__, "change": self.changes.get(candidate.url)})


async def test_unchanged_documents_are_counted_not_handed_on(h: Harness) -> None:
    urls = ["https://e.org/a", "https://e.org/b", "https://e.org/c"]
    got = await h.run(Compares(urls, {"https://e.org/a": "unchanged", "https://e.org/b": "changed",
                                      "https://e.org/c": "new"}))  # fmt: skip
    assert (got.status, got.items_new, got.items_changed, got.items_unchanged) == (
        "success",
        1,
        1,
        1,
    )
    assert [d["url"] for d in h.manifest()["documents"]] == urls[1:]
    assert got.cursor == {"content_hash": "h2"}
    h.stored.clear()
    same = await h.run(Compares(urls[:1], {"https://e.org/a": "unchanged"}))
    assert (same.status, same.items_unchanged, same.documents) == ("success", 1, [])
    assert execution.manifest_key(str(SOURCE), RUN) not in h.stored  # nothing for M4


async def test_connector_state_is_kept_only_when_every_document_was_fetched(h: Harness) -> None:
    h.fetcher.fail = {"https://e.org/b": [FetchRefusedError("too-large", "big")]}
    got = await h.run(Compares(["https://e.org/a", "https://e.org/b"], {}))
    assert got.status == "partial" and got.cursor is None
