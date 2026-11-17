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
    assert (got.status, got.error_class) == ("failed", "fetch-failed")
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
