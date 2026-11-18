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

    fetcher = SafeFetcher("regwatch-test (+ops@example.org)", resolver=public,
                          transport=httpx.MockTransport(site))  # fmt: skip
    capture = CaptureFetcher(fetcher, MemoryRateLimiter(), rate_per_minute=6000, sleep=no_wait)
    return ConnectorContext(fetcher=capture, store=store, now=lambda: NOW)


def job(cursor: dict[str, Any] | None = None, **config: Any) -> JobSettings:
    rules = ExtractionRules(content_selectors=["div.c"], exclude_selectors=[".counter"])
    return JobSettings(source_id="s1", kind="web_page",
                       config=WebPageConfig(page_url=URL, **config),  # type: ignore[arg-type]
                       rules=rules, rate_per_minute=6000, cursor=cursor)  # fmt: skip


async def run(body: bytes, objects: dict[str, bytes], cursor: dict[str, Any] | None,
              **site: Any) -> tuple[Any, dict[str, Any] | None]:  # fmt: skip
    ctx = context(Site(body, **site), objects)
    settings = job(cursor)
    found = [c async for c in web_page.WebPageConnector().discover(settings, ctx)]
    assert [c.url for c in found] == [URL]
    doc = await web_page.WebPageConnector().fetch(found[0], settings, ctx)
    return doc, ctx.state


async def test_first_run_then_unchanged_then_every_change() -> None:
    """M3 acceptance 2 and CP-16: identical text is unchanged (the counter is excluded by
    selector); any other text is changed and goes to M4, which applies the threshold."""
    objects: dict[str, bytes] = {}
    first, state = await run(page(LINES), objects, None)
    assert first.change == "new" and first.metadata["title"] == "Guidance"
    assert first.text.startswith("Paragraph 0") and "Visits" not in first.text
    assert state is not None and objects[state["text_ref"]] == first.text.encode()
    assert objects[first.body_ref] == page(LINES) and first.metadata["previous_text_ref"] is None
    stored = set(objects)
    same, kept = await run(page(LINES, visits=99), objects, state)  # only the counter differs
    assert (same.change, kept) == ("unchanged", None)
    assert set(objects) == stored  # an unchanged run stores nothing (review finding 5)
    # Review findings 1 and 2: one line of 41 (a status), or the same lines in another order.
    for lines in ([*LINES[:-1], "Status: Repealed"], [LINES[1], LINES[0], *LINES[2:]]):
        doc, moved = await run(page(lines), objects, state)
        assert doc.change == "changed" and doc.metadata["previous_text_ref"] == state["text_ref"]
        assert moved is not None and moved["content_hash"] != state["content_hash"]


async def test_the_charset_reaches_the_child_and_xhtml_is_html() -> None:
    body = "<div class=c><p>Règlement café</p></div>".encode("latin-1")
    doc, _ = await run(body, {}, None, mime="text/html; charset=ISO-8859-1")
    assert "Règlement café" in doc.text
    xhtml, _ = await run(page(LINES), {}, None, mime="application/xhtml+xml")
    assert xhtml.change == "new"


@pytest.mark.parametrize(
    ("site", "reason"),
    [
        ({"status": 404}, "http-status"),
        ({"mime": "application/pdf"}, "not-html"),
        ({"mime": ""}, "not-html"),
    ],
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


def test_charset_and_health() -> None:
    assert web_page._charset('text/html; Charset="ISO-8859-1"') == "ISO-8859-1"
    assert web_page._charset("text/html") is None
    assert web_page._charset("text/html; q=1; charset=utf-8") == "utf-8"
    assert web_page.WebPageConnector().health(job()).status == "unknown"
    assert isinstance(Candidate(url=URL), Candidate)


async def test_a_run_with_the_real_connector() -> None:
    """Review finding 7: run_connector with this connector, its counts, manifest and cursor."""
    import json
    import uuid

    from regwatch.capture import execution
    from regwatch.capture.models import CaptureJob, Source

    objects: dict[str, bytes] = {}
    site = Site(page(LINES))

    async def make(settings: JobSettings) -> ConnectorContext:
        return context(site, objects)

    source = Source(id=uuid.UUID(int=7), kind="web_page", robots_policy="respect",
                    config={"page_url": URL}, override_reason=None)  # fmt: skip
    job_row = CaptureJob(max_items_per_run=10, rate_limit_per_minute=6000, render_js=False,
                         extraction_rules={"content_selectors": ["div.c"]})  # fmt: skip
    run_id = uuid.UUID(int=1)
    first = await execution.run_connector(run_id, job_row, source, make)
    assert (first.status, first.items_new, first.items_unchanged) == ("success", 1, 0)
    rows = json.loads(objects[execution.manifest_key(str(source.id), run_id)])["documents"]
    assert rows[0]["change"] == "new" and rows[0]["metadata"]["title"] == "Guidance"
    job_row.cursor = first.cursor
    again = await execution.run_connector(uuid.UUID(int=2), job_row, source, make)
    assert (again.status, again.items_unchanged, again.cursor) == ("success", 1, None)
    assert execution.manifest_key(str(source.id), uuid.UUID(int=2)) not in objects


def test_connectors_never_parse_captured_html_in_process() -> None:
    """BL-98 (a): only extract.isolate may be used by connectors; tree, text and select run in
    the child alone."""
    import pathlib

    import regwatch.capture.connectors as package

    for path in pathlib.Path(package.__file__).parent.glob("*.py"):
        if path.name == "config.py":  # compiles the admin's selectors when saved; never a page
            continue
        code = path.read_text()
        for banned in ("extract.text", "extract.select", "tree.parse(", "extract import text",
                       "extract import select", "extract import tree"):  # fmt: skip
            assert banned not in code, f"{path.name} uses {banned}"
