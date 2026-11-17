"""Text, title and date from a parsed page, by the extraction rules or the main-text heuristic
(ADR-0009 decision 3; M3 design notes: single-page change detection).

- ``exclude_selectors`` and boilerplate (scripts, styles, navigation, headers, footers, asides,
  forms) are skipped wherever they are; they never reach the text or the hash.
- With ``content_selectors``, the content is the text of the matching elements in document
  order. Without them, the main text is the single ``main`` or ``article`` element if there is
  one with enough text; otherwise the block whose paragraphs hold the most text that is not link
  text, counting a paragraph fully for its parent and half for its grandparent.
- Text keeps block boundaries as line breaks; runs of whitespace become one space, blank lines
  go, and the result is NFC. Its SHA-256 is the change-detection hash, so a page that differs
  only in skipped parts or whitespace hashes the same.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime

from regwatch.capture.connectors.config import ExtractionRules
from regwatch.capture.extract.select import compile_selector
from regwatch.capture.extract.tree import Page, elements

BOILERPLATE = frozenset({"script", "style", "noscript", "template", "nav", "header", "footer",
                         "aside", "form", "iframe", "svg", "math", "button", "select", "head",
                         "object", "embed", "canvas", "dialog"})  # fmt: skip
BLOCKS = frozenset({"address", "article", "blockquote", "br", "dd", "details", "div", "dl", "dt",
                    "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li",
                    "main", "ol", "p", "pre", "section", "summary", "table", "tr", "ul",
                    "caption", "body"})  # fmt: skip
CELLS = frozenset({"td", "th"})
PARAGRAPHS = frozenset({"p", "pre", "li", "td", "blockquote", "dd"})
MAX_TEXT = 1_000_000  # characters kept; a page is at most 2 MiB parsed
MAX_TITLE = 500
# ISO 8601 first, then common written forms (CP-15); English month names only.
DATE_FORMATS = ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%d.%m.%Y", "%Y/%m/%d")
_SPACE = re.compile(r"[^\S\n]+")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


@dataclass(frozen=True)
class Extracted:
    text: str
    content_hash: str  # SHA-256 of ``text``, hex
    title: str | None = None
    published_at: datetime | None = None
    method: str = "selectors"  # selectors, main, article or blocks
    warnings: list[str] = field(default_factory=list)


def normalize(text: str) -> str:
    text = _CONTROL.sub(" ", unicodedata.normalize("NFC", text))
    lines = (_SPACE.sub(" ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)[:MAX_TEXT]


def _sep(el: ET.Element) -> str:
    return "\n" if el.tag in BLOCKS else (" " if el.tag in CELLS else "")


def _flat(value: str | None) -> str:
    """Source line breaks are whitespace in HTML; only block boundaries make lines."""
    return value.replace("\r", " ").replace("\n", " ") if value else ""


def text_of(el: ET.Element, skip: set[int]) -> str:
    """The element's text with block boundaries as line breaks, skipping the given elements and
    boilerplate (their tails, the text after them, are kept). Iterative: a page may be 256
    levels deep."""
    out: list[str] = []
    # An element to open, or the text to emit when an element closes: its separator and tail.
    stack: list[ET.Element | str] = [el]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            out.append(item)
            continue
        if not isinstance(item.tag, str) or id(item) in skip or item.tag in BOILERPLATE:
            continue
        out.append(_sep(item) + _flat(item.text))
        for child in reversed(list(item)):
            stack.append((_sep(child) if isinstance(child.tag, str) else "") + _flat(child.tail))
            stack.append(child)
    return normalize("".join(out))


Walk = list[tuple[ET.Element, ET.Element | None, int, int]]


def _skipped(page: Page, rules: ExtractionRules, walk: Walk) -> set[int]:
    return {id(el) for s in rules.exclude_selectors
            for el in compile_selector(s).select(page.root, walk)}  # fmt: skip


def _length(value: str | None) -> int:
    return len(" ".join(value.split())) if value else 0


def _main(page: Page, skip: set[int], minimum: int, walk: Walk) -> tuple[str, str]:
    """(text, method) by the heuristic in the module docstring. Text and link-text lengths are
    summed bottom-up in one pass, so nesting does not make scoring quadratic."""
    for tag in ("main", "article"):
        found = [el for el in page.root.iter(tag) if id(el) not in skip]
        if len(found) == 1:
            text = text_of(found[0], skip)
            if len(text) >= minimum:
                return text, "main" if tag == "main" else "article"
    total: dict[int, int] = {}
    links: dict[int, int] = {}
    for el, _parent, *_rest in reversed(walk):  # children before their parents
        if id(el) in skip or el.tag in BOILERPLATE:
            total[id(el)] = links[id(el)] = 0
            continue
        kids = [k for k in el if isinstance(k.tag, str)]
        total[id(el)] = (_length(el.text) + sum(_length(k.tail) for k in el)
                         + sum(total[id(k)] for k in kids))  # fmt: skip
        links[id(el)] = total[id(el)] if el.tag == "a" else sum(links[id(k)] for k in kids)
    parents = {id(el): parent for el, parent, *_rest in walk}
    scores: dict[int, float] = {}
    nodes: dict[int, ET.Element] = {}
    for el, parent, *_rest in walk:
        if el.tag not in PARAGRAPHS or not total[id(el)]:
            continue
        score = total[id(el)] - links[id(el)]
        grand = parents.get(id(parent))  # a paragraph is always inside body, so both exist
        for weight, node in ((1.0, parent), (0.5, grand)):
            if node is not None:  # pragma: no branch - html5lib puts every p inside body
                scores[id(node)] = scores.get(id(node), 0) + weight * score
                nodes[id(node)] = node
    if scores:
        best = max(scores, key=lambda k: scores[k])
        if scores[best] > 0:
            return text_of(nodes[best], skip), "blocks"
    body = page.root.find("body")
    return (text_of(body, skip) if body is not None else ""), "blocks"


def parse_date(value: str | None, fmt: str | None = None) -> datetime | None:
    """A date from page text: by ``date_format``, else ISO 8601, else one of DATE_FORMATS.
    Times without a zone are taken as UTC; anything unreadable is None, never an error."""
    if not value:
        return None
    value = " ".join(value.split())[:100]
    candidates = (fmt,) if fmt else (None, *DATE_FORMATS)
    for form in candidates:
        try:  # fromisoformat reads a date alone too, as midnight
            got = datetime.strptime(value, form) if form else datetime.fromisoformat(value)
        except ValueError:
            continue
        return got if got.tzinfo else got.replace(tzinfo=UTC)
    return None


def _first(page: Page, selector: str | None, skip: set[int], walk: Walk) -> ET.Element | None:
    if not selector:
        return None
    found = [el for el in compile_selector(selector).select(page.root, walk) if id(el) not in skip]
    return found[0] if found else None


def extract(page: Page, rules: ExtractionRules) -> Extracted:
    """The page's text, hash, title and date by the job's rules (checked when saved)."""
    walk = elements(page.root)  # once per page, for every selector (review finding 3)
    skip = _skipped(page, rules, walk)
    warnings = []
    if page.cut:
        warnings.append("the page was longer than the parse limit; only its start was read")
    if rules.content_selectors:
        chosen: dict[int, ET.Element] = {}
        for s in rules.content_selectors:
            chosen.update((id(el), el) for el in compile_selector(s).select(page.root, walk))
        # In document order, and not inside another chosen element, whose text holds it: one
        # pass marks each element that has a chosen ancestor.
        under: dict[int, bool] = {}
        picked: list[ET.Element] = []
        for el, parent, *_r in walk:
            up = parent is not None and (under[id(parent)] or id(parent) in chosen)
            under[id(el)] = up
            if id(el) in chosen and not up:
                picked.append(el)
        text = normalize("\n".join(text_of(el, skip) for el in picked))
        method = "selectors"
        if not picked:
            warnings.append("no element matched the content selectors")
    else:
        text, method = _main(page, skip, rules.min_text_length, walk)
    if len(text) < rules.min_text_length:
        warnings.append(f"the text is shorter than {rules.min_text_length} characters")
    title_el = _first(page, rules.title_selector, skip, walk)
    if title_el is None:
        title_el = page.root.find("head/title")
    if title_el is None:
        title_el = next(iter(page.root.iter("h1")), None)
    title = None
    if title_el is not None:
        title = text_of(title_el, set()).replace("\n", " ")[:MAX_TITLE] or None
    date_el = _first(page, rules.date_selector, skip, walk)
    published = None
    if date_el is not None:
        raw = date_el.get("datetime") or date_el.get("content") or text_of(date_el, set())
        published = parse_date(raw, rules.date_format)
        if published is None:
            warnings.append("the date could not be read")
    digest = hashlib.sha256(text.encode()).hexdigest()
    return Extracted(text, digest, title, published, method, warnings)
