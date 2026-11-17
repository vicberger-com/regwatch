"""Parse captured HTML into a tree, as a browser would, within fixed bounds (ADR-0009).

html5lib follows the WHATWG parsing algorithm, so selectors copied from a browser's developer
tools see the same tree: implicit ``tbody``, and the browser's repair of misnested tags. It is
pure Python, and parts of the algorithm scan the stack of open elements, so deep nesting costs
time quadratic in the depth: 4,000 nested ``div`` elements take about 0.4 s, and 100,000 take
minutes. Captured pages are hostile, so the tree builder refuses:

- a stack of open elements deeper than ``MAX_DEPTH``;
- more than ``MAX_ELEMENTS`` elements;
- a parse that runs past ``MAX_SECONDS`` (checked at each element, so text alone cannot stall
  it: text is linear).

Only the first ``MAX_PARSE_BYTES`` of a body are parsed; the caller is told when the rest was
cut. Scripts are never run: html5lib only builds the tree.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import html5lib  # type: ignore[import-untyped]  # no stubs; used only in this module
from html5lib.treebuilders import getTreeBuilder  # type: ignore[import-untyped]

MAX_PARSE_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 256
MAX_ELEMENTS = 200_000
MAX_SECONDS = 10.0
_Base: Any = getTreeBuilder("etree")


class ParseError(Exception):
    """The page could not be parsed within the bounds; ``reason`` is a fixed code."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason, self.detail = reason, detail


class _Stack(list[Any]):
    """html5lib's stack of open elements, refusing a page past the bounds. Every element the
    parser inserts is pushed here, void elements included, so this also counts elements."""

    def __init__(self, deadline: float) -> None:
        super().__init__()
        self.deadline, self.elements = deadline, 0

    def append(self, item: Any) -> None:  # noqa: ANN401 - html5lib's element wrapper
        if len(self) >= MAX_DEPTH:
            raise ParseError("too-deep", f"elements are nested more than {MAX_DEPTH} deep")
        self.elements += 1
        if self.elements > MAX_ELEMENTS:
            raise ParseError("too-large", f"the page has more than {MAX_ELEMENTS} elements")
        if time.monotonic() > self.deadline:
            raise ParseError("too-slow", f"the page took longer than {MAX_SECONDS:g} s to parse")
        super().append(item)


def _builder(deadline: float) -> type:
    class Capped(_Base):  # type: ignore[misc]
        def reset(self) -> None:
            super().reset()
            self.openElements = _Stack(deadline)

    return Capped


@dataclass(frozen=True)
class Page:
    root: ET.Element  # the html element; tag names are lower case, without a namespace
    cut: bool  # the body was longer than MAX_PARSE_BYTES and only its start was parsed


def parse(body: bytes, encoding: str | None = None) -> Page:
    """The tree of ``body``. ``encoding`` is the charset the server named, if any; html5lib
    otherwise sniffs it as browsers do (BOM, then ``<meta charset>``, then windows-1252)."""
    cut = len(body) > MAX_PARSE_BYTES
    deadline = time.monotonic() + MAX_SECONDS
    parser = html5lib.HTMLParser(tree=_builder(deadline), namespaceHTMLElements=False)
    # An unknown charset label is ignored by html5lib, which then sniffs as browsers do.
    try:
        root = parser.parse(body[:MAX_PARSE_BYTES], transport_encoding=encoding)
    except UnicodeError:  # a label that is no text at all, such as a lone surrogate (finding 6)
        root = parser.parse(body[:MAX_PARSE_BYTES])
    return Page(root, cut)


def elements(root: ET.Element) -> list[tuple[ET.Element, ET.Element | None, int, int]]:
    """Every element in document order, without recursion: (element, parent, position among
    its parent's element children counting from 1, the number of those children)."""
    out: list[tuple[ET.Element, ET.Element | None, int, int]] = []
    stack: list[tuple[ET.Element, ET.Element | None, int, int]] = [(root, None, 1, 1)]
    while stack:
        item = stack.pop()
        out.append(item)
        # Comments have a function as their tag. A template's contents are inert in a browser
        # and match no selector there (review finding 4), so they are not walked.
        kids = [k for k in item[0] if isinstance(k.tag, str)] if item[0].tag != "template" else []
        stack.extend((k, item[0], n, len(kids)) for n, k in reversed(list(enumerate(kids, 1))))
    return out
