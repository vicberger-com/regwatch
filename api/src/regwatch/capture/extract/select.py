"""The CSS selector subset of the extraction rules (CP-15; ADR-0009).

Supported:
- type selectors and ``*``; ``#id`` and ``.class``;
- ``[attr]``, and ``[attr=v]`` with ``~=``, ``^=``, ``$=`` and ``*=``, where ``v`` is a name or
  a quoted string;
- the descendant (space) and child (``>``) combinators, and comma lists;
- ``:first-child``, ``:last-child`` and ``:nth-child(an+b | odd | even)``;
- ``:not(...)`` holding one compound selector without ``:not``.

Anything else is refused by ``compile_selector`` with a message, so a rule is checked when it is
saved, not when a page arrives. Matching is a single pass in document order: for each step of
the selector, each element records whether that step matches it and whether it or an ancestor
does, so the cost is the number of elements times the number of steps, whatever the selector.
There is no backtracking, and no recursion over the tree.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # nosec B405 - html5lib builds the trees; no XML is parsed
from dataclasses import dataclass, field

from regwatch.capture.extract.tree import elements

MAX_SELECTOR = 300
MAX_ALTERNATIVES = 10
MAX_STEPS = 8
_NAME = r"-?[_a-zA-Z][-_a-zA-Z0-9]*"
_WS = r"[ \t\n\r\f]"  # CSS whitespace: ASCII only (review finding 6)
_SPLIT = re.compile(r"[ \t\n\r\f]+")  # how a browser splits class and ~= lists (finding 4)
_TOKEN = re.compile(
    # Combinators before plain whitespace, so " > " and " , " are one token each.
    rf"""(?P<child>{_WS}*>{_WS}*)|(?P<comma>{_WS}*,{_WS}*)|(?P<space>{_WS}+)|(?P<type>{_NAME}|\*)
    |\#(?P<id>{_NAME})|\.(?P<cls>{_NAME})
    |\[{_WS}*(?P<attr>{_NAME}){_WS}*(?:(?P<op>[~^$*]?=){_WS}*(?:(?P<bare>{_NAME})|"(?P<dq>[^"\\]*)"|'(?P<sq>[^'\\]*)'){_WS}*)?\]
    |:(?P<pseudo>first-child|last-child)\b|:nth-child\({_WS}*(?P<nth>[^)]*?){_WS}*\)|:not\((?P<neg>[^()]*)\)
    """,
    re.VERBOSE,
)
_NTH = re.compile(
    r"(?:(?P<a>[+-]?[0-9]{0,6})n(?:(?P<sign>[+-])(?P<b1>[0-9]{1,6}))?"
    r"|(?P<b>[+-]?[0-9]{1,6}))"
)


class SelectorError(ValueError):
    """A selector outside the subset; the message says what is wrong."""


@dataclass(frozen=True)
class _Compound:
    tag: str | None = None  # None is any element
    ids: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    attrs: tuple[tuple[str, str | None, str], ...] = ()  # (name, operator, value)
    nth: tuple[tuple[int, int, bool], ...] = ()  # (a, b, from the end)
    negated: tuple[_Compound, ...] = ()

    def matches(self, el: ET.Element, position: int, count: int) -> bool:
        # SVG and MathML elements carry their namespace in html5lib's tree (finding 4).
        name = el.tag.rsplit("}", 1)[-1] if el.tag.startswith("{") else el.tag  # R6: a}p
        if self.tag is not None and name.lower() != self.tag:
            return False
        if self.ids and any(el.get("id") != i for i in self.ids):
            return False
        if self.classes:
            have = set(_SPLIT.split(el.get("class") or ""))
            if not have.issuperset(self.classes):
                return False
        for name, op, want in self.attrs:
            value = _get(el, name)
            if value is None or not _attr(op, value, want):
                return False
        for a, b, from_end in self.nth:
            if not _nth(a, b, count - position + 1 if from_end else position):
                return False
        return not any(n.matches(el, position, count) for n in self.negated)


def _get(el: ET.Element, name: str) -> str | None:
    """An attribute by name, ignoring case, as for HTML; SVG keeps ``viewBox`` (finding 4)."""
    value = el.get(name)
    if value is None:
        value = next((v for k, v in el.attrib.items() if k.lower() == name), None)
    return value


def _attr(op: str | None, value: str, want: str) -> bool:
    if op is None:
        return True
    if op == "=":
        return value == want
    if op == "~=":
        return want in _SPLIT.split(value)
    if not want:  # [a^=""], [a$=""] and [a*=""] match nothing (Selectors 4)
        return False
    return {"^=": value.startswith, "$=": value.endswith, "*=": value.__contains__}[op](want)


def _nth(a: int, b: int, index: int) -> bool:
    """Whether index = a*n + b for some n >= 0."""
    if a == 0:
        return index == b
    return (index - b) % a == 0 and (index - b) // a >= 0


@dataclass(frozen=True)
class Selector:
    text: str
    # Each alternative: its steps left to right, each a compound and the combinator before it.
    alternatives: tuple[tuple[tuple[str, _Compound], ...], ...] = field(repr=False)

    def select(self, root: ET.Element, walk: list[tuple[ET.Element, ET.Element | None, int, int]]
               | None = None) -> list[ET.Element]:  # fmt: skip
        """The matching elements, in document order, each once. ``walk`` is ``elements(root)``,
        when the caller has it already: several selectors on one page walk it once (finding 3)."""
        found: dict[int, ET.Element] = {}
        walk = elements(root) if walk is None else walk
        for steps in self.alternatives:
            # here[id] = which steps match the element; below[id] = which match it or an ancestor
            here: dict[int, int] = {}
            below: dict[int, int] = {}
            last = 1 << (len(steps) - 1)
            for el, parent, position, count in walk:
                p_here = here.get(id(parent), 0) if parent is not None else 0
                p_below = below.get(id(parent), 0) if parent is not None else 0
                bits = 0
                for i, (combinator, compound) in enumerate(steps):
                    if i and not (p_here if combinator == ">" else p_below) >> (i - 1) & 1:
                        continue
                    if compound.matches(el, position, count):
                        bits |= 1 << i
                here[id(el)], below[id(el)] = bits, bits | p_below
                if bits & last:
                    found[id(el)] = el
        order = {id(el): n for n, (el, *_rest) in enumerate(walk)}
        return sorted(found.values(), key=lambda el: order[id(el)])


def _compound(text: str, tokens: list[re.Match[str]], start: int) -> tuple[_Compound, int]:
    tag: str | None = None
    ids: list[str] = []
    classes: list[str] = []
    attrs: list[tuple[str, str | None, str]] = []
    nth: list[tuple[int, int, bool]] = []
    negated: list[_Compound] = []
    i = start
    while i < len(tokens):
        m = tokens[i]
        if m.group("type") is not None:
            if i != start:
                raise SelectorError(f"{text!r}: a type selector must come first")
            tag = None if m.group("type") == "*" else m.group("type").lower()
        elif m.group("id") is not None:
            ids.append(m.group("id"))
        elif m.group("cls") is not None:
            classes.append(m.group("cls"))
        elif m.group("attr") is not None:
            quoted = (m.group("bare"), m.group("dq"), m.group("sq"))
            want = next((g for g in quoted if g is not None), "")
            attrs.append((m.group("attr").lower(), m.group("op"), want))
        elif m.group("pseudo") is not None:
            nth.append((0, 1, m.group("pseudo") == "last-child"))
        elif m.group("nth") is not None:
            nth.append((*_parse_nth(text, m.group("nth")), False))
        elif m.group("neg") is not None:  # holds no parentheses, so never a :not() itself
            negated.append(_inner(text, m.group("neg")))
        else:  # a combinator or a comma: the compound ends
            break
        i += 1
    if i == start:
        raise SelectorError(f"{text!r}: a selector step is missing")
    return _Compound(tag, tuple(ids), tuple(classes), tuple(attrs), tuple(nth), tuple(negated)), i


def _inner(text: str, body: str) -> _Compound:
    tokens = _tokens(text, body.strip())
    compound, end = _compound(text, tokens, 0)
    if end != len(tokens):
        raise SelectorError(f"{text!r}: :not() holds one compound selector, with no combinator")
    return compound


def _parse_nth(text: str, expr: str) -> tuple[int, int]:
    # Spaces only around the sign: "2n + 1", not "2 n+1" (review finding 6).
    # Spaces around the sign of b only: "2n + 1", not "+ 3" or "2 n+1" (R6).
    expr = {"odd": "2n+1", "even": "2n"}.get(expr.lower(), re.sub(r"(?<=n) *([+-]) *(?=[0-9])",
                                                              r"\1", expr.strip()))  # fmt: skip
    m = _NTH.fullmatch(expr)
    if m is None:
        raise SelectorError(f"{text!r}: :nth-child takes an+b, odd or even")
    if m.group("b") is not None:
        return 0, int(m.group("b"))
    a = {"": 1, "+": 1, "-": -1}.get(m.group("a"), None)
    b = int(m.group("b1") or 0) * (-1 if m.group("sign") == "-" else 1)
    return (int(m.group("a")) if a is None else a), b


def _tokens(text: str, body: str) -> list[re.Match[str]]:
    tokens: list[re.Match[str]] = []
    i = 0
    while i < len(body):
        m = _TOKEN.match(body, i)
        if m is None or m.end() == i:
            raise SelectorError(f"{text!r}: not supported at {body[i:i + 20]!r} (see the "
                                "selector subset in connectors.yaml)")  # fmt: skip
        tokens.append(m)
        i = m.end()
    return tokens


def compile_selector(text: str) -> Selector:
    """A checked selector, or SelectorError saying what is outside the subset."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_SELECTOR:
        raise SelectorError(f"a selector is 1 to {MAX_SELECTOR} characters")
    tokens = _tokens(text, text.strip())
    alternatives: list[tuple[tuple[str, _Compound], ...]] = []
    steps: list[tuple[str, _Compound]] = []
    combinator = " "
    i = 0
    while True:
        compound, i = _compound(text, tokens, i)
        steps.append((combinator, compound))
        if len(steps) > MAX_STEPS:
            raise SelectorError(f"{text!r}: at most {MAX_STEPS} steps")
        if i == len(tokens) or tokens[i].lastgroup == "comma":
            alternatives.append(tuple(steps))
            if i == len(tokens):
                break
            steps, combinator, i = [], " ", i + 1
            if len(alternatives) >= MAX_ALTERNATIVES:
                raise SelectorError(f"{text!r}: at most {MAX_ALTERNATIVES} selectors in a list")
            continue
        combinator = ">" if tokens[i].lastgroup == "child" else " "
        i += 1
    return Selector(text, tuple(alternatives))
