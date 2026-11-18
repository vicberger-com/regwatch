"""The web page connector, single mode, with change detection (M3 acceptance 2; CP-16)."""

from __future__ import annotations

import json
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


@pytest.mark.parametrize(("config", "render"), [({}, True)])
async def test_rendering_is_not_built_yet(config: dict[str, Any],
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


def test_no_code_outside_extract_parses_captured_html_in_process() -> None:
    """BL-98 (a), re-verification R2: by the syntax tree, over the whole package, not by
    substrings. Only capture/extract may import html5lib or extract.tree, text and select;
    config.py may import compile_selector, which compiles an admin's selector, never a page."""
    import ast
    import pathlib

    import regwatch

    banned = {"html5lib", "regwatch.capture.extract.tree", "regwatch.capture.extract.text",
              "regwatch.capture.extract.select"}  # fmt: skip
    root = pathlib.Path(regwatch.__file__).parent
    allowed = {("capture/connectors/config.py", "regwatch.capture.extract.select")}
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith("capture/extract/"):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for name in names:
                hit = next((b for b in banned if name == b or name.startswith(b + ".")), None)
                assert hit is None or (rel, hit) in allowed, f"{rel} imports {name}"


@pytest.mark.parametrize(
    "ref",
    [
        "text/other/" + "a" * 64 + ".txt",
        "raw/s1/runs/x.json",
        "../../etc/passwd",
        "text/s1/" + "A" * 64 + ".txt",
        "text/s1/" + "a" * 63 + ".txt",
        5,
        "x" * 100_000,
    ],
)
def test_only_this_sources_text_keys_reach_m4(ref: Any) -> None:
    """Re-verification R1."""
    assert web_page._own_text_ref(ref, "s1") is None
    good = "text/s1/" + "a" * 64 + ".txt"
    assert web_page._own_text_ref(good, "s1") == good


class Listing:
    """A listing page linking to documents; each document's body can be changed per test."""

    def __init__(self, links: list[str], docs: dict[str, str]) -> None:
        self.links, self.docs = links, docs
        self.paths: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404, stream=httpx.ByteStream(b""))
        if request.url.path == "/list":
            items = "".join(f'<li><a href="{h}">doc</a></li>' for h in self.links)
            body = f"<nav><a href='/nav'>menu</a></nav><ul class=docs>{items}</ul>".encode()
        elif request.url.path.endswith(".pdf"):
            return httpx.Response(200, headers={"content-type": "application/pdf"},
                                  stream=httpx.ByteStream(b"%PDF"))  # fmt: skip
        elif request.url.path.startswith("/deep"):
            body = b"<div>" * 1000
        elif request.url.path == "/hop":
            return httpx.Response(302, headers={"Location": "https://third.example/x"})
        else:
            body = f"<div class=c><p>{self.docs.get(request.url.path, 'none')}</p></div>".encode()
        return httpx.Response(200, headers={"content-type": "text/html"},
                              stream=httpx.ByteStream(body))  # fmt: skip


async def listing_run(site: Listing, objects: dict[str, bytes], cursor: dict[str, Any] | None,
                      max_links: int = 50, max_items: int = 100, **rules: Any) -> Any:  # fmt: skip
    import uuid

    from regwatch.capture import execution
    from regwatch.capture.models import CaptureJob, Source

    async def make(settings: JobSettings) -> ConnectorContext:
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

    source = Source(id=uuid.UUID(int=7), kind="web_page", robots_policy="respect",
                    config={"page_url": "https://regulator.example/list", "mode": "listing",
                            "listing_link_selector": "ul.docs", "max_links": max_links},
                    override_reason=None)  # fmt: skip
    job_row = CaptureJob(max_items_per_run=max_items, rate_limit_per_minute=6000,
                         render_js=False,
                         extraction_rules={"content_selectors": ["div.c"], **rules},
                         cursor=cursor)  # fmt: skip
    return await execution.run_connector(uuid.uuid4(), job_row, source, make)


async def test_listing_mode_compares_each_linked_page() -> None:
    site = Listing(["/a", "b", "https://regulator.example/a", "javascript:x()", "http://10.0.0.1/x"],
                   {"/a": "Act A", "/b": "Act B"})  # fmt: skip
    objects: dict[str, bytes] = {}
    first = await listing_run(site, objects, None)
    assert (first.status, first.items_new, first.items_unchanged) == ("success", 2, 0)
    assert [d.url for d in first.documents] == ["https://regulator.example/a",
                                                "https://regulator.example/b"]  # fmt: skip
    assert "/nav" not in site.paths  # only the selector's links
    ref = first.cursor["listing_ref"]
    assert ref.startswith("state/00000000-0000-0000-0000-000000000007/")
    same = await listing_run(site, objects, first.cursor)
    assert (same.items_unchanged, same.items_new, same.cursor) == (2, 0, None)
    site.docs["/b"] = "Act B, amended"
    site.links = ["/b"]  # /a is no longer listed
    moved = await listing_run(site, objects, first.cursor)
    assert (moved.items_changed, moved.items_unchanged) == (1, 0)
    assert moved.documents[0].metadata["previous_text_ref"].startswith("text/")
    state = json.loads(objects[moved.cursor["listing_ref"]])
    assert list(state) == ["https://regulator.example/b"]


async def test_listing_limits_patterns_and_a_foreign_state_key() -> None:
    site = Listing([f"/d{n}" for n in range(5)] + ["/skip-me"], {})
    objects: dict[str, bytes] = {}
    cut = await listing_run(site, objects, None, max_links=3)
    assert (cut.status, cut.error_class, cut.items_new) == ("partial", "truncated", 3)
    some = await listing_run(site, objects, None, exclude_url_patterns=["skip"],
                             include_url_patterns=["/d[0-1]$", "skip"])  # fmt: skip
    assert [d.url.rsplit("/", 1)[1] for d in some.documents] == ["d0", "d1"]
    foreign = {"listing_ref": "state/other/" + "a" * 64 + ".json"}
    objects["state/other/" + "a" * 64 + ".json"] = b'{"https://regulator.example/d0": ["x", "y"]}'
    fresh = await listing_run(site, objects, foreign, max_links=1)
    assert fresh.documents[0].change == "new"  # another source's state is never read
    broken = {"listing_ref": "state/00000000-0000-0000-0000-000000000007/" + "b" * 64 + ".json"}
    objects[broken["listing_ref"]] = b"not json"
    assert (await listing_run(site, objects, broken, max_links=1)).documents[0].change == "new"


@pytest.mark.parametrize(
    ("config", "rules"),
    [({"mode": "listing"}, {}), ({"mode": "listing", "listing_link_selector": "a:hover"}, {}),
     ({}, {"include_url_patterns": ["(a)\\1"]}), ({}, {"exclude_url_patterns": ["x" * 201]})],
)  # fmt: skip
def test_listing_settings_are_checked_when_saved(config: dict[str, Any],
                                                 rules: dict[str, Any]) -> None:  # fmt: skip
    from regwatch.capture.connectors.config import validate_config, validate_rules
    from regwatch.core.errors import ProblemError

    with pytest.raises(ProblemError):
        validate_config("web_page", {"page_url": URL, **config})
        validate_rules(rules)


async def test_stale_rows_fail_as_bad_config() -> None:
    """Rows saved before these checks: a bad pattern, a listing without its selector."""

    class Rules:
        include_url_patterns = ["(a)\\1"]
        exclude_url_patterns: list[str] = []

    with pytest.raises(ConnectorError) as exc:
        web_page._url_filter(Rules())
    assert exc.value.reason == "bad-config"
    stale = WebPageConfig.model_construct(page_url=URL, mode="listing", listing_link_selector=None,
                                          max_links=5, wait_for_selector=None)  # fmt: skip
    settings = JobSettings(**{**job().__dict__, "config": stale})
    with pytest.raises(ConnectorError) as exc:
        [c async for c in web_page.WebPageConnector().discover(settings, context(Site(b""), {}))]
    assert exc.value.reason == "bad-config"


async def test_a_state_object_that_is_not_a_map_is_ignored() -> None:
    sid = "00000000-0000-0000-0000-000000000007"
    ref = f"state/{sid}/" + "c" * 64 + ".json"
    site = Listing(["/a"], {"/a": "A"})
    got = await listing_run(site, {ref: b"[1, 2]"}, {"listing_ref": ref})
    assert got.documents[0].change == "new"


async def test_links_stay_on_the_listing_host_and_hops_too() -> None:
    """Web listing review finding 1: no other host, not even by a redirect."""
    links = ["https://third.example/private", "https://sub.regulator.example/x", "/hop", "/a"]
    site = Listing(links,
                   {"/a": "A"})  # fmt: skip
    got = await listing_run(site, {}, None)
    assert [d.url for d in got.documents] == ["https://regulator.example/a"]
    assert got.status == "partial"  # /hop was refused at its redirect, never fetched elsewhere
    assert "/x" not in site.paths and "/private" not in site.paths


async def test_the_override_applies_to_page_urls_host_only() -> None:
    calls: list[Any] = []

    class Recording:
        async def fetch(self, url: str, **kwargs: Any) -> Any:
            calls.append(kwargs)
            from regwatch.capture.safe_fetch import FetchResult

            return FetchResult(url, 200, {"content-type": "text/html"}, b"<p>x</p>")

    settings = JobSettings(**{**job().__dict__, "robots_override": "Owner agreed with the site"})
    ctx = ConnectorContext(fetcher=Recording(), store=None, now=lambda: NOW)  # type: ignore[arg-type]
    await web_page._get_html(URL, settings, ctx, "regulator.example")
    await web_page._get_html("https://other.example/x", settings, ctx, "other.example")
    await web_page._get_html(URL, settings, ctx)
    assert [c["robots_override"] for c in calls] == ["Owner agreed with the site", None,
                                                     "Owner agreed with the site"]  # fmt: skip
    assert calls[0]["allow_hop"]("https://regulator.example/y")
    assert not calls[0]["allow_hop"]("https://third.example/y") and calls[2]["allow_hop"] is None


async def test_a_failing_page_keeps_the_others_state() -> None:
    """Finding 2: a PDF in the listing fails, yet /a and /b are unchanged next time."""
    site = Listing(["/a", "/b", "/report.pdf"], {"/a": "A", "/b": "B"})
    objects: dict[str, bytes] = {}
    first = await listing_run(site, objects, None)
    assert (first.status, first.items_new) == ("partial", 2) and first.cursor is not None
    again = await listing_run(site, objects, first.cursor)
    assert (again.items_new, again.items_unchanged) == (0, 2)


async def test_a_run_stops_after_three_unreadable_pages() -> None:
    """Finding 3: hostile pages cost up to 20 s each; the run stops at the third."""
    site = Listing(["/a"] + [f"/deep{n}" for n in range(10)], {"/a": "A"})
    got = await listing_run(site, {}, None)
    assert (got.status, got.error_class) == ("partial", "unreadable-pages")
    assert sum(1 for p in site.paths if p.startswith("/deep")) == 3


async def test_the_item_limit_rotates_through_the_links() -> None:
    """Finding 4: pages never checked first, then the longest unchecked."""
    site = Listing([f"/d{n}" for n in range(5)], {})
    objects: dict[str, bytes] = {}

    first = await listing_run(site, objects, None, max_items=2)
    second = await listing_run(site, objects, first.cursor, max_items=2)
    third = await listing_run(site, objects, second.cursor, max_items=2)
    names = [[d.url.rsplit("/", 1)[1] for d in r.documents] for r in (first, second, third)]
    assert names == [["d0", "d1"], ["d2", "d3"], ["d4"]]


async def test_query_variants_are_one_page() -> None:
    site = Listing([f"/a?v={n}" for n in range(5)], {"/a": "A"})
    got = await listing_run(site, {}, None)
    assert [d.url for d in got.documents] == ["https://regulator.example/a"]


def test_a_url_that_does_not_parse_has_no_host() -> None:
    assert web_page._host("https://[bad") is None
