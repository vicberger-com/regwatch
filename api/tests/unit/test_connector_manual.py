"""The manual connector and the upload checks (CP-17)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from regwatch.api import middleware
from regwatch.capture import manual
from regwatch.capture.connectors import manual as connector
from regwatch.capture.connectors.base import ConnectorContext, ConnectorError, JobSettings
from regwatch.capture.connectors.config import ExtractionRules, ManualConfig
from regwatch.capture.safe_fetch import CaptureFetcher, MemoryRateLimiter, SafeFetcher
from regwatch.core.errors import ProblemError

NOW = datetime(2026, 11, 18, tzinfo=UTC)
SID = "00000000-0000-0000-0000-000000000009"
RUN = "01930000-0000-7000-8000-000000000001"


@pytest.mark.parametrize(
    ("data", "mime"),
    [(b"%PDF-1.7 ...", "application/pdf"), (b"\xef\xbb\xbf <!DOCTYPE html><p>x", "text/html"),
     (b"<html><body>x", "text/html"), (b"Plain words, caf\xc3\xa9.", "text/plain"),
     (b"<p>a fragment, taken as text</p>", "text/plain"),
     (b'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml">', "text/html"),
     (b"<meta charset=utf-8><p>x", "text/html"), (b" " * 2000 + b"<html><p>x", "text/html"),
     (b"<div>some text</div><html>late</html>", "text/html")],
)  # fmt: skip
def test_sniffing_by_content(data: bytes, mime: str) -> None:
    assert manual.sniff(data) == mime


@pytest.mark.parametrize("data", [b"\x00binary", b"\xff\xfe\xfd not utf-8"])
def test_other_content_is_refused(data: bytes) -> None:
    with pytest.raises(ProblemError) as exc:
        manual.sniff(data)
    assert exc.value.status == 415


def site(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(404, stream=httpx.ByteStream(b""))
    if request.url.path == "/act":
        page = b"<title>Act</title><main><p>" + b"word " * 50 + b"</p></main>"
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"},
                              stream=httpx.ByteStream(page))  # fmt: skip
    if request.url.path == "/act.pdf":
        return httpx.Response(200, headers={"content-type": "application/pdf"},
                              stream=httpx.ByteStream(b"%PDF-1.7"))  # fmt: skip
    if request.url.path == "/img":
        return httpx.Response(200, headers={"content-type": "image/png"},
                              stream=httpx.ByteStream(b"png"))  # fmt: skip
    return httpx.Response(404, stream=httpx.ByteStream(b""))


def context(objects: dict[str, bytes], run_id: str | None = RUN) -> ConnectorContext:
    async def public(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    async def store(key: str, body: bytes) -> None:
        objects[key] = body

    async def load(key: str) -> bytes | None:
        return objects.get(key)

    fetcher = SafeFetcher("regwatch-test (+ops@example.org)", resolver=public,
                          transport=httpx.MockTransport(site))  # fmt: skip
    capture = CaptureFetcher(fetcher, MemoryRateLimiter(), rate_per_minute=6000)
    ctx = ConnectorContext(fetcher=capture, store=store, now=lambda: NOW, load=load)
    if run_id is not None:
        ctx.scratch["run_id"] = run_id
    return ctx


JOB = JobSettings(source_id=SID, kind="manual", config=ManualConfig(), rules=ExtractionRules(),
                  rate_per_minute=6000)  # fmt: skip


async def run(objects: dict[str, bytes], request: Any, run_id: str | None = RUN) -> Any:
    if request is not None:
        objects[manual.request_key(SID, RUN)] = (request if isinstance(request, bytes)
                                                 else json.dumps(request).encode())  # fmt: skip
    ctx = context(objects, run_id)
    found = [c async for c in connector.ManualConnector().discover(JOB, ctx)]
    return [await connector.ManualConnector().fetch(c, JOB, ctx) for c in found]


async def test_a_url_page_is_fetched_and_read_in_the_child() -> None:
    objects: dict[str, bytes] = {}
    [doc] = await run(objects, {"kind": "url", "url": "https://reg.example/act", "title": None})
    assert (doc.change, doc.mime, doc.metadata["title"]) == ("new", "text/html", "Act")
    assert doc.text.startswith("word word") and objects[doc.body_ref].startswith(b"<title>")
    [pdf] = await run(objects, {"kind": "url", "url": "https://reg.example/act.pdf",
                                "title": "Act PDF"})  # fmt: skip
    assert (pdf.mime, pdf.text, pdf.metadata["title"]) == ("application/pdf", None, "Act PDF")


@pytest.mark.parametrize(
    ("path", "reason"), [("/img", "unsupported-type"), ("/gone", "http-status")]
)
async def test_urls_that_are_not_documents_fail(path: str, reason: str) -> None:
    with pytest.raises(ConnectorError) as exc:
        await run({}, {"kind": "url", "url": f"https://reg.example{path}", "title": None})
    assert exc.value.reason == reason


async def test_an_uploaded_file_is_read_back_by_its_exact_key() -> None:
    body_ref = f"upload/{SID}/" + "a" * 64
    objects = {body_ref: "Plain text, café.".encode()}
    [doc] = await run(objects, {"kind": "file", "body_ref": body_ref, "mime": "text/plain",
                                "title": "Note"})  # fmt: skip
    assert (doc.text, doc.url, doc.body_ref) == ("Plain text, café.", "urn:sha256:" + "a" * 64,
                                                 body_ref)  # fmt: skip
    html_ref = f"upload/{SID}/" + "b" * 64
    objects[html_ref] = b"<html><main><p>" + b"word " * 50 + b"</p></main>"
    [page] = await run(objects, {"kind": "file", "body_ref": html_ref, "mime": "text/html",
                                 "title": None})  # fmt: skip
    assert page.text.startswith("word") and page.metadata["content_hash"]


@pytest.mark.parametrize(
    "request_",
    [{"kind": "file", "body_ref": "upload/other/" + "a" * 64, "mime": "text/plain"},
     {"kind": "file", "body_ref": "../../etc/passwd", "mime": "text/plain"},
     {"kind": "file", "body_ref": f"upload/{SID}/" + "a" * 64, "mime": "image/png"},
     {"kind": "shell", "url": "x"}, b"not json"],
)  # fmt: skip
async def test_requests_that_are_not_this_sources_are_refused(request_: Any) -> None:
    with pytest.raises(ConnectorError) as exc:
        await run({}, request_)
    assert exc.value.reason == "bad-request"


async def test_runs_without_a_request_offer_nothing() -> None:
    assert await run({}, None) == []
    assert await run({}, None, run_id="../../x") == []
    body_ref = f"upload/{SID}/" + "c" * 64
    with pytest.raises(ConnectorError) as exc:  # the file was removed meanwhile
        await run({}, {"kind": "file", "body_ref": body_ref, "mime": "text/plain"})
    assert exc.value.reason == "bad-request"
    assert connector.ManualConnector().health(JOB).status == "unknown"


def test_only_the_upload_route_has_the_larger_cap() -> None:
    route = {"method": "POST", "path": f"/api/v1/sources/{SID}/documents"}
    assert middleware._limit(route, 100) == 10 * 1024 * 1024 + 64 * 1024
    assert middleware._limit({**route, "method": "PUT"}, 100) == 100
    assert middleware._limit({"method": "POST", "path": "/api/v1/sources"}, 100) == 100
    assert middleware._limit({**route, "path": route["path"] + "/x"}, 100) == 100


async def test_a_page_that_cannot_be_read_is_a_typed_failure() -> None:
    body_ref = f"upload/{SID}/" + "d" * 64
    with pytest.raises(ConnectorError) as exc:
        await run({body_ref: b"<div>" * 1000}, {"kind": "file", "body_ref": body_ref,
                                                "mime": "text/html"})  # fmt: skip
    assert exc.value.reason == "too-deep"


async def test_the_override_never_applies_to_a_submitted_url() -> None:
    """Manual review finding 1: robots.txt is obeyed whatever the job says."""
    calls: list[Any] = []

    class Recording:
        async def fetch(self, url: str, **kwargs: Any) -> Any:
            calls.append(kwargs)
            from regwatch.capture.safe_fetch import FetchResult

            return FetchResult(url, 200, {"content-type": "application/pdf"}, b"%PDF-1.7")

    objects = {manual.request_key(SID, RUN): json.dumps({"kind": "url",
                                                         "url": "https://elsewhere.example/m",
                                                         "title": None}).encode()}  # fmt: skip

    async def store(key: str, body: bytes) -> None:
        objects[key] = body

    async def load(key: str) -> bytes | None:
        return objects.get(key)

    ctx = ConnectorContext(fetcher=Recording(), store=store, now=lambda: NOW, load=load)  # type: ignore[arg-type]
    ctx.scratch["run_id"] = RUN
    job = JobSettings(**{**JOB.__dict__, "robots_override": "The regulator agreed in writing"})
    [c] = [c async for c in connector.ManualConnector().discover(job, ctx)]
    await connector.ManualConnector().fetch(c, job, ctx)
    assert calls[0]["robots_override"] is None


async def test_a_run_of_a_manual_source_reads_its_request_by_the_run_id() -> None:
    """Manual review finding 7: through run_connector, which passes the run's id."""
    import uuid

    from regwatch.capture import execution
    from regwatch.capture.models import CaptureJob, Source

    objects: dict[str, bytes] = {}
    run_id = uuid.UUID(RUN)
    objects[manual.request_key(SID, run_id)] = json.dumps(
        {"kind": "url", "url": "https://reg.example/act", "title": "Act"}
    ).encode()

    async def make(settings: JobSettings) -> ConnectorContext:
        return context(objects, None)

    source = Source(id=uuid.UUID(SID), kind="manual", robots_policy="respect", config={},
                    override_reason=None)  # fmt: skip
    job = CaptureJob(max_items_per_run=10, rate_limit_per_minute=6000, render_js=False,
                     extraction_rules={})  # fmt: skip
    got = await execution.run_connector(run_id, job, source, make)
    assert (got.status, got.items_new) == ("success", 1)
    objects[manual.request_key(SID, run_id)] = json.dumps(
        {"kind": "url", "url": "https://reg.example/img", "title": None}
    ).encode()
    failed = await execution.run_connector(run_id, job, source, make)
    # Finding 5: one document, so its own reason, not "none of 1 documents".
    assert (failed.status, failed.error_class) == ("failed", "unsupported-type")
