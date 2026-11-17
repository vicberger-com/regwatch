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
from regwatch.capture.safe_fetch import FetchRefusedError

RUN = uuid.UUID("01930000-0000-7000-8000-000000000001")
NOW = datetime(2026, 11, 17, tzinfo=UTC)


class Fake:
    """A connector whose discovery and fetches do what each test says."""

    kind = "rss"
    config_schema = RssConfig

    def __init__(self, urls: list[str], fail: dict[str, list[Exception]] | None = None,
                 discover_error: Exception | None = None) -> None:  # fmt: skip
        self.urls, self.fail, self.discover_error = urls, fail or {}, discover_error
        self.calls: list[str] = []

    async def discover(self, job: JobSettings, ctx: ConnectorContext) -> AsyncIterator[Candidate]:
        if self.discover_error is not None:
            raise self.discover_error
        for url in self.urls:
            yield Candidate(url=url)

    async def fetch(self, candidate: Candidate, job: JobSettings,
                    ctx: ConnectorContext) -> RawDocument:  # fmt: skip
        self.calls.append(candidate.url)
        errors = self.fail.get(candidate.url, [])
        if errors:
            raise errors.pop(0)
        body = candidate.url.encode()
        key = f"raw/{job.source_id}/{len(self.calls)}"
        await ctx.store(key, body)
        return RawDocument(url=candidate.url, fetched_at=ctx.now(), status=200, body_ref=key,
                           mime="text/html")  # fmt: skip

    def health(self, job: JobSettings) -> HealthReport:
        return HealthReport("unknown")


def rows(config: dict[str, Any] | None = None, policy: str = "respect",
         max_items: int = 200) -> tuple[CaptureJob, Source]:  # fmt: skip
    config = config if config is not None else {"feed_url": "https://e.org/f"}
    source = Source(id=uuid.UUID(int=7), kind="rss", robots_policy=policy, config=config,
                    override_reason="Owner agreed" if policy == "override" else None)  # fmt: skip
    job = CaptureJob(max_items_per_run=max_items, rate_limit_per_minute=30, render_js=False,
                     extraction_rules={})  # fmt: skip
    return job, source


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    monkeypatch.setattr(execution, "RETRY_WAIT_S", 0.0)
    return {}


def factory(stored: dict[str, bytes]) -> execution.ContextFactory:
    async def store(key: str, body: bytes) -> None:
        stored[key] = body

    async def make(job: JobSettings) -> ConnectorContext:
        return ConnectorContext(fetcher=None, store=store, now=lambda: NOW)  # type: ignore[arg-type]

    return make


async def run(connector: Fake, stored: dict[str, bytes], monkeypatch: pytest.MonkeyPatch,
              **kw: Any) -> execution.Outcome:  # fmt: skip
    monkeypatch.setitem(REGISTRY, "rss", connector)
    job, source = rows(**kw)
    return await execution.run_connector(RUN, job, source, factory(stored))


async def test_every_document_fetched_is_a_success(
    stored: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    got = await run(Fake(["https://e.org/a", "https://e.org/b"]), stored, monkeypatch)
    assert (got.status, got.items_new, got.robots_decision) == ("success", 2, "allowed")
    manifest = json.loads(stored[execution.manifest_key(str(uuid.UUID(int=7)), RUN)])
    assert [d["url"] for d in manifest["documents"]] == ["https://e.org/a", "https://e.org/b"]
    assert got.bytes_fetched == sum(len(v) for v in stored.values())


async def test_transient_failures_are_retried_at_most_three_times(
    stored: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    timeout = FetchRefusedError("timeout", "slow")
    fake = Fake(["https://e.org/a", "https://e.org/b"],
                fail={"https://e.org/a": [timeout],  # recovers on the second attempt
                      "https://e.org/b": [timeout, timeout, timeout, timeout]})  # fmt: skip
    got = await run(fake, stored, monkeypatch)
    assert fake.calls.count("https://e.org/a") == 2
    assert fake.calls.count("https://e.org/b") == 3  # never a fourth
    assert (got.status, got.items_new, got.error_class) == ("partial", 1, "some-failed")


async def test_refusals_are_not_retried(
    stored: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = Fake(["https://e.org/a"],
                fail={"https://e.org/a": [FetchRefusedError("private-address", "no")]})  # fmt: skip
    got = await run(fake, stored, monkeypatch)
    assert fake.calls == ["https://e.org/a"]
    assert (got.status, got.error_class) == ("failed", "fetch-failed")
    assert execution.manifest_key(str(uuid.UUID(int=7)), RUN) not in stored


@pytest.mark.parametrize(
    ("error", "status", "error_class", "decision"),
    [(FetchRefusedError("robots", "disallowed"), "skipped", "robots", "disallowed"),
     (FetchRefusedError("rate-limited", "busy"), "skipped", "rate-limited", "rate-limited"),
     (FetchRefusedError("timeout", "slow"), "failed", "timeout", None),
     (ConnectorError("unsafe-feed", "a DOCTYPE"), "failed", "unsafe-feed", None)],
)  # fmt: skip
async def test_discovery_stops(
    stored: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: str,
    error_class: str,
    decision: str | None,
) -> None:
    """Acceptance 4: robots.txt disallowing the feed skips the run and records the decision."""
    got = await run(Fake([], discover_error=error), stored, monkeypatch)
    assert (got.status, got.error_class, got.robots_decision) == (status, error_class, decision)


async def test_limits_bad_config_and_missing_connectors(
    stored: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    many = Fake([f"https://e.org/{n}" for n in range(10)])
    got = await run(many, stored, monkeypatch, max_items=3)
    assert got.items_new == 3 and len(many.calls) == 3
    bad = await run(Fake([]), stored, monkeypatch, config={"feed_url": "not a url"})
    assert (bad.status, bad.error_class) == ("failed", "bad-config")
    over = await run(Fake(["https://e.org/a"]), stored, monkeypatch, policy="override")
    assert over.robots_decision == "overridden"
    monkeypatch.delitem(REGISTRY, "rss")
    job, source = rows()
    none = await execution.run_connector(RUN, job, source, factory(stored))
    assert (none.status, none.error_class) == ("failed", "no-connector")


async def test_an_empty_feed_is_a_success_with_nothing_new(
    stored: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    got = await run(Fake([]), stored, monkeypatch)
    assert (got.status, got.items_new) == ("success", 0) and stored == {}


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
