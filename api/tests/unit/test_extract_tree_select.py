"""HTML parsing within bounds and the CSS selector subset (ADR-0009, CP-15)."""

from __future__ import annotations

import time

import pytest

from regwatch.capture.extract import select, tree
from regwatch.capture.extract.select import SelectorError, compile_selector

PAGE = (b'<!doctype html><title>T</title><!-- note --><div id=main class="a b">'
        b'<p class=x>1</p><p>2</p><section><p data-k="v w" lang="en-GB">3</p></section></div>'
        b"<ul><li>a<li>b<li>c</ul><table><tr><td>t</table>")  # fmt: skip


def texts(selector: str, body: bytes = PAGE) -> list[str]:
    root = tree.parse(body).root
    return [el.text or el.tag for el in compile_selector(selector).select(root)]


def test_the_tree_is_a_browsers_tree() -> None:
    page = tree.parse(PAGE)
    walk = [(e.tag, p.tag if p is not None else None, n, c) for e, p, n, c in
            tree.elements(page.root)]  # fmt: skip
    assert walk[:3] == [("html", None, 1, 1), ("head", "html", 1, 2), ("title", "head", 1, 1)]
    assert ("tbody", "table", 1, 1) in walk  # implied, as in a browser
    assert not page.cut and all(isinstance(t, str) for t, *_ in walk)  # comments are not elements


@pytest.mark.parametrize(
    ("selector", "expected"),
    [("p", ["1", "2", "3"]), ("DIV > P", ["1", "2"]), ("div p", ["1", "2", "3"]),
     ("#main .x", ["1"]), ("p:not(.x)", ["2", "3"]), (".a.b > p.x", ["1"]),
     ("[data-k]", ["3"]), ("[data-k=v]", []), ('[data-k="v w"]', ["3"]), ("[data-k~=w]", ["3"]),
     ("[lang^=en]", ["3"]), ("[lang$='GB']", ["3"]), ("[lang*=n-G]", ["3"]), ("[lang^='']", []),
     ("li:nth-child(odd)", ["a", "c"]), ("li:nth-child(even)", ["b"]), ("li:nth-child(2)", ["b"]),
     ("li:nth-child(-n+2)", ["a", "b"]), ("li:nth-child(n+3)", ["c"]),
     ("li:nth-child(2n-1)", ["a", "c"]),
     ("li:nth-child(+3)", ["c"]), ("li:first-child", ["a"]), ("li:last-child", ["c"]),
     ("table > tbody > tr > td", ["t"]), ("ul li:last-child, #main>p:first-child", ["1", "c"]),
     ("p , li:not(:last-child)", ["1", "2", "3", "a", "b"]), ("* > section *", ["3"]),
     ("#nope", []), ("div:not(#main) p", []), ("li:nth-child(2n + 1)", ["a", "c"])],
)  # fmt: skip
def test_the_subset_matches_as_css_does(selector: str, expected: list[str]) -> None:
    assert texts(selector) == expected


@pytest.mark.parametrize(
    ("selector", "message"),
    [("a:hover", "not supported"), ("a::before", "not supported"), ("a ~ b", "not supported"),
     ("a + b", "not supported"), ("div >", "step is missing"), ("", "1 to 300"),
     ("x" * 301, "1 to 300"), ("a[x|=y]", "not supported"), (":not(:not(a))", "not supported"),
     (":not(a:not(b))", "not supported"), (":not(a b)", "no combinator"),
     ("a:nth-child(foo)", "an\\+b"), ("p.x div", None), (".x p", None), ("p.x span", None),
     (".a div", None), ("a.b c", None), ("x.y", None), ("div.x#y", None), ("p#x", None),
     (".x div", None), ("p.a.b", None), ("a, " * 10 + "a", "at most 10"),
     (" ".join(["p"] * 9), "at most 8"), ("p.x*", "must come first"),
     ("li:nth-child(\u0663)", "an\\+b"), ("li:nth-child(\uff13)", "an\\+b"),
     ("li:nth-child(2 n+1)", "an\\+b"), ("#1x", "not supported"), ("a\u3000b", "not supported")],
)  # fmt: skip
def test_selectors_outside_the_subset_are_refused(selector: str, message: str | None) -> None:
    if message is None:
        compile_selector(selector)  # accepted
        return
    with pytest.raises(SelectorError, match=message):
        compile_selector(selector)


def test_a_non_string_is_refused() -> None:
    with pytest.raises(SelectorError):
        compile_selector(None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("body", "reason"),
    [(b"<div>" * 100_000, "too-deep"), (b"<b>" * 100_000, "too-deep"),
     (b"<br>" * 200_001, "too-large")],
)  # fmt: skip
def test_hostile_pages_are_refused_quickly(body: bytes, reason: str) -> None:
    started = time.monotonic()
    with pytest.raises(tree.ParseError) as exc:
        tree.parse(body)
    # Generous: the bound matters, not the machine (review finding 7: 5.8 s under coverage).
    assert exc.value.reason == reason and time.monotonic() - started < 20


def test_a_slow_parse_is_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tree, "MAX_SECONDS", -1.0)  # the deadline is already past
    with pytest.raises(tree.ParseError) as exc:
        tree.parse(b"<p>x</p>")
    assert exc.value.reason == "too-slow"


def test_only_the_start_of_a_long_body_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tree, "MAX_PARSE_BYTES", 20)
    page = tree.parse(b"<p>first</p><p>second and more</p>")
    assert page.cut and [e.text for e in page.root.iter("p")] == ["first", "secon"]


def test_charsets_from_the_server_and_unknown_labels() -> None:
    body = "<p>café</p>".encode("latin-1")
    assert tree.parse(body, "iso-8859-1").root.find(".//p").text == "café"  # type: ignore[union-attr]
    assert tree.parse(b"<p>x</p>", "no-such-charset").root.find(".//p").text == "x"  # type: ignore[union-attr]


def test_matching_costs_elements_times_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    """A selector that fails only at its first step, over deep nesting, would backtrack
    through every choice of ancestors in a naive matcher; here it is one pass."""
    body = b"<div>" * 250 + b"<span>x</span>"
    sel = compile_selector("p div div div div div div span")
    started = time.monotonic()
    assert sel.select(tree.parse(body).root) == []
    assert time.monotonic() - started < 1
    assert select.MAX_STEPS == 8


def test_matching_follows_the_browser() -> None:
    """Review finding 4: ASCII whitespace splits classes; SVG names and attributes match
    ignoring case and namespace; template contents are inert."""
    body = (
        '<p class="a\u00a0b">nbsp</p><p class="c\td">tab</p>'
        '<svg viewBox="0 0 1 1"><rect class=r></rect></svg>'
        "<template><p class=t>inert</p></template>"
    ).encode()
    assert texts(".a", body) == [] and texts(".d", body) == ["tab"]
    assert texts("[class~=b]", body) == []
    assert texts("svg rect.r", body) == ["{http://www.w3.org/2000/svg}rect"]
    assert len(texts("[viewbox]", body)) == 1 and texts(".t", body) == []


def test_a_charset_label_that_is_no_text_is_ignored() -> None:
    assert tree.parse(b"<p>x</p>", "\ud800").root.find(".//p").text == "x"  # type: ignore[union-attr]
