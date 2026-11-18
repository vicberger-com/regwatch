"""The web page connector, single mode, with change detection (M3 acceptance 2; CP-16)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from regwatch.capture.connectors import web_page
from regwatch.capture.connectors.base import (
    Candidate,
    ConnectorContext,
    ConnectorError,
    JobSettings,
)
from regwatch.capture.connectors.config import ExtractionRules, WebPageConfig
from regwatch.capture.safe_fetch import CaptureFetcher, MemoryRateLimiter, SafeFetcher

NOW = datetime(2026, 11, 17, tzinfo=UTC)
URL = "https://regulator.example/guidance"
LINES = [f"Paragraph {n} of the guidance, with enough words to read." for n in range(40)]


def page(lines: list[str], visits: int = 1) -> bytes:
    body = "".join(f"<p>{line}</p>" for line in lines)
    return (f"<html><head><title>Guidance</title></head><body><div class=c>{body}</div>"
            f"<p class=counter>Visits: {visits}</p></body></html>").encode()  # fmt: skip


class Site:
    def __init__(self, body: bytes, status: int = 200, mime: str = "text/html; charset=utf-8"):
        self.body, self.status, self.mime = body, status, mime

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404, stream=httpx.ByteStream(b""))
        return httpx.Response(self.status, headers={"content-type": self.mime},
                              stream=httpx.ByteStream(self.body))  # fmt: skip


def context(site: Site, objects: dict[str, bytes]) -> ConnectorContext:
    async def public(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    async def no_wait(seconds: float) -> None:
        return None

    async def store(key: str, body: bytes) -> None:
        objects[key] = body

    async def load(key: str) -> bytes | None:
        return objects.get(key)

    fetcher = SafeFetcher("regwatch-test (+ops@example.org)", resolver=public,
                          transport=httpx.MockTransport(site))  # fmt: skip
    capture = CaptureFetcher(fetcher, MemoryRateLimiter(), rate_per_minute=6000, sleep=no_wait)
    return ConnectorContext(fetcher=capture, store=store, now=lambda: NOW, load=load)


def job(cursor: dict[str, Any] | None = None, **config: Any) -> JobSettings:
    rules = ExtractionRules(content_selectors=["div.c"], exclude_selectors=[".counter"])
    return JobSettings(source_id="s1", kind="web_page",
                       config=WebPageConfig(page_url=URL, **config),  # type: ignore[arg-type]
                       rules=rules, rate_per_minute=6000, cursor=cursor,
                       change_threshold_pct=5.0)  # fmt: skip


async def run(body: bytes, objects: dict[str, bytes], cursor: dict[str, Any] | None,
              **site: Any) -> tuple[Any, dict[str, Any] | None]:  # fmt: skip
    ctx = context(Site(body, **site), objects)
    settings = job(cursor)
    found = [c async for c in web_page.WebPageConnector().discover(settings, ctx)]
    assert [c.url for c in found] == [URL]
    doc = await web_page.WebPageConnector().fetch(found[0], settings, ctx)
    return doc, ctx.state


async def test_first_run_then_unchanged_then_changed_beyond_the_threshold() -> None:
    """M3 acceptance 2, with the counter excluded by selector."""
    objects: dict[str, bytes] = {}
    first, state = await run(page(LINES), objects, None)
    assert first.change == "new" and first.metadata["title"] == "Guidance"
    assert first.text.startswith("Paragraph 0") and "Visits" not in first.text
    assert state is not None and objects[state["text_ref"]] == first.text.encode()
    assert objects[first.body_ref] == page(LINES)
    same, kept = await run(page(LINES, visits=99), objects, state)  # only the counter differs
    assert (same.change, kept) == ("unchanged", None)
    one = [*LINES[:-1], "A new final paragraph."]  # 1 of 40 lines: 2.5 % changed, under 5 %
    small, kept = await run(page(one), objects, state)
    assert (small.change, small.metadata["changed_pct"], kept) == ("unchanged", 2.5, None)
    three = [*LINES[:-3], "New one.", "New two.", "New three."]  # 7.5 %: changed
    big, moved = await run(page(three), objects, state)
    assert big.change == "changed" and big.metadata["changed_pct"] == 7.5
    assert moved is not None and moved["content_hash"] != state["content_hash"]


async def test_a_lost_baseline_text_is_a_change() -> None:
    doc, state = await run(page(LINES), {}, {"content_hash": "old", "text_ref": "text/s1/gone.txt"})
    assert doc.change == "changed" and doc.metadata["changed_pct"] is None and state is not None


async def test_a_baseline_from_another_source_is_never_read() -> None:
    objects = {"text/other/x.txt": b"secret"}
    doc, _ = await run(
        page(LINES), objects, {"content_hash": "old", "text_ref": "text/other/x.txt"}
    )
    assert doc.change == "changed" and doc.metadata["changed_pct"] is None


@pytest.mark.parametrize(
    ("site", "reason"),
    [({"status": 404}, "http-status"), ({"mime": "application/pdf"}, "not-html")],
)
async def test_errors_and_other_media_are_refused(site: dict[str, Any], reason: str) -> None:
    objects: dict[str, bytes] = {}
    with pytest.raises(ConnectorError) as exc:
        await run(page(LINES), objects, None, **site)
    assert exc.value.reason == reason and objects == {}


async def test_a_page_that_cannot_be_read_is_a_typed_failure() -> None:
    with pytest.raises(ConnectorError) as exc:
        await run(b"<div>" * 1000, {}, None)
    assert exc.value.reason == "too-deep"


@pytest.mark.parametrize(("config", "render"), [({"mode": "listing"}, False), ({}, True)])
async def test_listing_mode_and_rendering_are_not_built_yet(config: dict[str, Any],
                                                            render: bool) -> None:  # fmt: skip
    settings = JobSettings(**{**job(**config).__dict__, "render_js": render})
    ctx = context(Site(b""), {})
    with pytest.raises(ConnectorError) as exc:
        [c async for c in web_page.WebPageConnector().discover(settings, ctx)]
    assert exc.value.reason == "not-implemented"


def test_changed_share_and_charset() -> None:
    assert web_page.changed_pct("", "") == 0.0
    assert web_page.changed_pct("a\nb", "a\nc") == 50.0
    assert web_page._charset('text/html; Charset="ISO-8859-1"') == "ISO-8859-1"
    assert web_page._charset("text/html") is None
    assert web_page._charset("text/html; q=1; charset=utf-8") == "utf-8"
    assert web_page.WebPageConnector().health(job()).status == "unknown"
    assert isinstance(Candidate(url=URL), Candidate)
