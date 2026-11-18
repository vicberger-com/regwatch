"""Text, title, date and hash from a page (ADR-0009 decision 3; M3 acceptance 2)."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from regwatch.capture.connectors.config import ExtractionRules, validate_rules
from regwatch.capture.extract import text, tree
from regwatch.core.errors import ProblemError

PAGE = b"""<html><head><title> The   Act 2026 </title><script>track()</script></head><body>
<nav>Home | About</nav><header>Site</header>
<div class=content><h1>Heading</h1>
<p>First paragraph of the regulation, with enough words to count.</p>
<p>Second, <a href=/x>a link</a> and <b>more</b> text.</p>
<p class=updated>Updated 17 November 2026</p><time datetime=2026-11-17T10:00:00Z>today</time>
<table><tr><td>cell one<td>cell two</table></div>
<aside>Related</aside><footer>Contact</footer></body></html>"""


def run(body: bytes = PAGE, **rules: Any) -> text.Extracted:
    return text.extract(tree.parse(body), ExtractionRules(**{"min_text_length": 10, **rules}))


def test_the_main_text_skips_boilerplate() -> None:
    got = run()
    assert got.method == "blocks" and got.title == "The Act 2026"
    assert got.text.splitlines() == [
        "Heading", "First paragraph of the regulation, with enough words to count.",
        "Second, a link and more text.", "Updated 17 November 2026", "today",
        "cell one cell two"]  # fmt: skip
    assert "Home" not in got.text and "Contact" not in got.text and "track" not in got.text
    assert got.warnings == [] and got.published_at is None


def test_selectors_exclusions_and_the_date() -> None:
    got = run(content_selectors=["div.content p", "div.content"], exclude_selectors=[".updated"],
              date_selector="time", title_selector="h1")  # fmt: skip
    assert got.method == "selectors" and got.title == "Heading"
    assert "Updated" not in got.text and got.text.startswith("Heading")
    assert got.text.count("First paragraph") == 1  # p inside the chosen div: once
    assert got.published_at == datetime(2026, 11, 17, 10, tzinfo=UTC)
    by_text = run(date_selector=".updated", date_format="Updated %d %B %Y")
    assert by_text.published_at == datetime(2026, 11, 17, tzinfo=UTC)
    bad = run(date_selector="h1")
    assert bad.published_at is None and bad.warnings == ["the date could not be read"]


def test_the_hash_ignores_skipped_parts_and_whitespace() -> None:
    """M3 acceptance 2: identical text hashes the same; a counter excluded by selector too."""
    a = run(PAGE.replace(b"Updated 17", b"Updated 19"), exclude_selectors=["p.updated"])
    spaced = PAGE.replace(b"enough words", b"enough \n\n  words")
    b = run(spaced.replace(b"17 November", b"18 November"), exclude_selectors=["p.updated"])
    assert a.content_hash == b.content_hash and len(a.content_hash) == 64
    c = run(PAGE.replace(b"enough words", b"other words"), exclude_selectors=["p.updated"])
    assert c.content_hash != a.content_hash


@pytest.mark.parametrize(
    ("body", "method"),
    [(b"<main><p>" + b"x" * 300 + b"</p></main><div><p>" + b"y" * 900 + b"</p></div>", "main"),
     (b"<article><p>" + b"x" * 300 + b"</p></article>", "article"),
     (b"<main><p>short</p></main><div><p>" + b"y" * 300 + b"</p></div>", "blocks"),
     (b"<div><p><a href=/a>" + b"l" * 900 + b"</a></p></div><div><p>" + b"t" * 300 + b"</p></div>",
      "blocks"),
     (b"<body>no paragraphs here</body>", "blocks"), (b"", "blocks"),
     (b"<div><p><a href=/a>only links</a></p></div>", "blocks")],
)  # fmt: skip
def test_the_main_text_heuristic(body: bytes, method: str) -> None:
    got = text.extract(tree.parse(body), ExtractionRules())
    assert got.method == method
    if b"t" * 300 in body:
        assert got.text == "t" * 300  # link text does not count
    if body.startswith(b"<main><p>x"):
        assert got.text == "x" * 300


def test_warnings_for_short_text_no_match_and_a_cut_page(monkeypatch: pytest.MonkeyPatch) -> None:
    got = run(content_selectors=["#missing"], min_text_length=200)
    assert got.warnings == ["no element matched the content selectors",
                            "the text is shorter than 200 characters"]  # fmt: skip
    monkeypatch.setattr(tree, "MAX_PARSE_BYTES", 100)
    assert run().warnings[0].startswith("the page was longer")


def test_no_title_and_an_h1_title() -> None:
    assert run(b"<p>body text here</p>").title is None
    assert run(b"<h1>  Big\n title </h1><p>body</p>").title == "Big title"


@pytest.mark.parametrize(
    ("value", "fmt", "expected"),
    [("2026-11-17", None, datetime(2026, 11, 17, tzinfo=UTC)),
     ("2026-11-17T10:00:00+02:00", None,
      datetime(2026, 11, 17, 10, tzinfo=timezone(timedelta(hours=2)))),
     ("17 November 2026", None, datetime(2026, 11, 17, tzinfo=UTC)),
     ("Nov  17, 2026", None, datetime(2026, 11, 17, tzinfo=UTC)),
     ("17.11.2026", None, datetime(2026, 11, 17, tzinfo=UTC)),
     ("2026/11/17", None, datetime(2026, 11, 17, tzinfo=UTC)),
     ("17/11/26", "%d/%m/%y", datetime(2026, 11, 17, tzinfo=UTC)),
     ("2026-02-30", None, None), ("nonsense", None, None), ("", None, None), (None, None, None),
     ("2026-11-17", "%d.%m.%Y", None), ("17.11.2026 17", "%d.%m.%Y %d", None)],
)  # fmt: skip
def test_dates(value: str | None, fmt: str | None, expected: datetime | None) -> None:
    assert text.parse_date(value, fmt) == expected


def test_text_is_normalized() -> None:
    assert text.normalize("á\x00b \t c\n\n \n d ") == "á b c\nd"
    assert len(text.normalize("x" * (text.MAX_TEXT + 5))) == text.MAX_TEXT


def test_deep_and_wide_pages_stay_fast() -> None:
    """Scoring is bottom-up in one pass, so nested paragraphs are not quadratic."""
    deep = b"<blockquote>" * 250 + b"x" * 200_000
    wide = b"<div>" + b"<p>" + b"<p>word ".join([b""] * 50_000) + b"</div>"
    for body in (deep, wide):
        started = time.monotonic()
        text.extract(tree.parse(body), ExtractionRules())
        assert time.monotonic() - started < 10


@pytest.mark.parametrize(
    ("rules", "field"),
    [({"content_selectors": ["a:hover"]}, "content_selectors"),
     ({"exclude_selectors": ["x"] * 21}, "exclude_selectors"),
     ({"title_selector": "a ~ b"}, "title_selector"), ({"date_selector": "::x"}, "date_selector"),
     ({"date_format": "%s"}, "date_format"), ({"date_format": "no directive"}, "date_format"),
     ({"date_format": "%Y" * 21}, "date_format"), ({"date_format": "%d.%m.%Y %d"}, "date_format")],
)  # fmt: skip
def test_rules_are_checked_when_saved(rules: dict[str, Any], field: str) -> None:
    with pytest.raises(ProblemError) as exc:
        validate_rules(rules)
    assert [e.field for e in exc.value.errors] == [f"extraction_rules.{field}"]
    ok = validate_rules({"content_selectors": ["main p"], "title_selector": "h1",
                         "date_selector": "time", "date_format": "%d.%m.%Y"})  # fmt: skip
    assert ok.date_format == "%d.%m.%Y"


@pytest.mark.parametrize(
    "body",
    [b"<svg><text>SVG-SECRET</text></svg><main><p>" + b"v" * 300 + b"</p></main>",
     b"<template><main><p>HIDDEN" + b"h" * 300 + b"</p></main></template><article><p>"
     + b"v" * 300 + b"</p></article>",
     b"<nav><main><p>HIDDEN" + b"h" * 300 + b"</p></main></nav><div><p>" + b"v" * 300
     + b"</p></div>",
     b"<aside><p>HIDDEN" + b"h" * 900 + b"</p></aside><div><p>" + b"v" * 300 + b"</p></div>",
     b"<math><mi>SVG-SECRET</mi></math><div><p>" + b"v" * 300 + b"</p></div>"],
)  # fmt: skip
def test_hidden_and_graphic_text_is_never_the_main_text(body: bytes) -> None:
    """Re-verification R3: what monitoring hashes is what a reader sees."""
    got = text.extract(tree.parse(body), ExtractionRules())
    assert got.text == "v" * 300


def test_links_from_a_listing_selector(monkeypatch: pytest.MonkeyPatch) -> None:
    body = (
        b'<ul class=d><li><a href=" /a ">A</a><li><a href="/a">A again</a><li><a>none</a>'
        b'<li><a href="' + b"x" * 2049 + b'">long</a></ul><p><a class=one href="/b">B</a></p>'
    )
    page = tree.parse(body)
    walk = tree.elements(page.root)
    assert text.links(page, "ul.d", walk) == ["/a"]
    assert text.links(page, "a.one", walk) == ["/b"]
    monkeypatch.setattr(text, "MAX_LINKS", 1)
    assert text.links(page, "a", walk) == ["/a"]
    assert text.extract(page, ExtractionRules(), "a.one").links == ["/b"]


def test_links_a_reader_cannot_see_are_not_taken() -> None:
    """Web listing review finding 5: template contents, hidden and excluded elements."""
    body = (
        b'<ul class=d><li><a href="/ok">ok</a></li><template><a href="/t">t</a></template>'
        b'<li hidden><a href="/h">h</a></li><li class=x><a href="/x">x</a></li></ul>'
    )
    got = text.extract(tree.parse(body), ExtractionRules(exclude_selectors=[".x"]), "ul.d")
    assert got.links == ["/ok"]
