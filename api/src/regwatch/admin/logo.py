"""Logo checks (BL-68, M1 acceptance 6): a PNG, or an SVG that cannot run or fetch anything.

The file is refused, never rewritten: what is stored is exactly what passed. The media type comes
from the content, not from what the client declared.

SVG: parsed with defusedxml (no DTD, entities or external references), then every element must
be in the SVG namespace and on ``ELEMENTS``, and every attribute on ``ATTRIBUTES``. That leaves out
``script``, ``foreignObject``, ``style`` (element and attribute), animation and every ``on*``
handler. A ``href`` may only point inside the document (``#id``). Attribute values may not hold
CSS escapes (backslashes), comments (``/*``) or at-rules (``@``), and a ``(`` is allowed only as
``url(#id)``, a colour function (``rgb``, ``rgba``, ``hsl``, ``hsla``) with numeric arguments,
or, in transform attributes, an SVG transform function with numbers (BL-68 review finding 2).
No reference (``href`` or ``url(#id)``) may point at an element that holds a reference itself,
except a gradient, so references cannot multiply into billions of drawn copies (review finding 3
and re-verification N2). The logo is shown only through
``<img>`` (where scripts never run) and served with its own strict CSP, so this check is the
second of two layers.
"""

from __future__ import annotations

import re
import struct
from typing import TYPE_CHECKING

import defusedxml.ElementTree as SafeXML
from defusedxml import DefusedXmlException

if TYPE_CHECKING:  # types only; parsing always goes through defusedxml
    from xml.etree.ElementTree import Element  # nosec B405 - annotations only

MAX_BYTES = 1024 * 1024
MAX_ELEMENTS = 5000
MAX_SIDE = 4096  # pixels, for PNG
PNG = "image/png"
SVG = "image/svg+xml"

_SVG_NS = "{http://www.w3.org/2000/svg}"
_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

ELEMENTS = frozenset({
    "svg", "g", "defs", "title", "desc", "symbol", "use",
    "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "text", "tspan",
    "linearGradient", "radialGradient", "stop", "clipPath", "mask", "pattern",
})  # fmt: skip
ATTRIBUTES = frozenset({
    "id", "class", "version", "viewBox", "preserveAspectRatio", "width", "height",
    "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "fx", "fy",
    "d", "points", "transform", "offset",
    "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity",
    "stroke-linecap", "stroke-linejoin", "stroke-miterlimit", "stroke-dasharray",
    "stroke-dashoffset", "opacity", "clip-path", "clip-rule", "mask", "color",
    "display", "visibility", "stop-color", "stop-opacity",
    "gradientUnits", "gradientTransform", "spreadMethod", "patternUnits",
    "patternContentUnits", "patternTransform", "clipPathUnits", "maskUnits", "maskContentUnits",
    "font-family", "font-size", "font-weight", "font-style", "text-anchor",
    "dominant-baseline", "letter-spacing", "href", _XLINK_HREF, _XML_SPACE,
})  # fmt: skip
_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?(?:%|deg|rad|grad|turn)?"
_ARGS = rf"\(\s*{_NUMBER}(?:\s*[,/\s]\s*{_NUMBER})*\s*\)"
# The only parenthesised forms a value may contain; anything else with "(" is refused.
_LOCAL_URL = re.compile(r"url\(\s*(['\"]?)#([A-Za-z_][\w.-]*)\1\s*\)")
_GRADIENTS = frozenset({f"{_SVG_NS}linearGradient", f"{_SVG_NS}radialGradient"})
_FRAGMENT = re.compile(r"#[A-Za-z_][\w.-]*")
_COLOUR_FN = re.compile(rf"(?:rgba?|hsla?){_ARGS}", re.IGNORECASE)
_TRANSFORM_FN = re.compile(rf"(?:matrix|translate|scale|rotate|skewX|skewY){_ARGS}")
_TRANSFORM_ATTRS = frozenset({"transform", "gradientTransform", "patternTransform"})
_FORBIDDEN = ("\\", "/*", "@")


class LogoRejectedError(ValueError):
    """The upload is not a PNG or an acceptable SVG; the message says why, for the user."""


def check(data: bytes) -> str:
    """The media type of an acceptable logo, or ``LogoRejectedError``."""
    if not data:
        raise LogoRejectedError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise LogoRejectedError("The logo is larger than 1 MB.")
    if data.startswith(_PNG_SIGNATURE):
        _check_png(data)
        return PNG
    head = data[:512].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if head.startswith((b"<?xml", b"<svg", b"<!--", b"<!doctype")):
        _check_svg(data)
        return SVG
    raise LogoRejectedError("The logo must be a PNG or SVG file.")


def _check_png(data: bytes) -> None:
    # The first chunk must be IHDR (length 13) with a sane size; the bytes are stored unchanged.
    if len(data) < 33 or data[8:16] != b"\x00\x00\x00\x0dIHDR":
        raise LogoRejectedError("The PNG file is damaged.")
    width, height = struct.unpack(">II", data[16:24])
    if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE):
        raise LogoRejectedError(f"A PNG logo is at most {MAX_SIDE} by {MAX_SIDE} pixels.")


def _check_svg(data: bytes) -> None:
    # The parser drops processing instructions silently, so look for a stylesheet one first.
    if b"<?xml-stylesheet" in data.lower():
        raise LogoRejectedError("An SVG logo may not load anything from elsewhere.")
    try:
        root = SafeXML.fromstring(data, forbid_dtd=True, forbid_entities=True,
                                  forbid_external=True)  # fmt: skip
    except DefusedXmlException:
        raise LogoRejectedError("SVG files may not contain a DOCTYPE or entities.") from None
    except SafeXML.ParseError:
        raise LogoRejectedError("The SVG file is not well-formed XML.") from None
    if root.tag != f"{_SVG_NS}svg":
        raise LogoRejectedError("The file is not an SVG image.")
    count = 0
    for element in root.iter():
        count += 1
        if count > MAX_ELEMENTS:
            raise LogoRejectedError(f"An SVG logo has at most {MAX_ELEMENTS} elements.")
        _check_element(element)
    _check_use_chains(root)


def _references(el: Element) -> list[str]:
    """The ids an element points at: its ``href`` and every ``url(#id)`` in its attributes."""
    out = [m.group(2) for v in el.attrib.values() for m in _LOCAL_URL.finditer(v)]
    href = (el.get("href") or el.get(_XLINK_HREF) or "").strip()
    return [*out, href[1:]] if href.startswith("#") else out


def _check_use_chains(root: Element) -> None:
    """No reference may point at something that itself holds a reference (review 3 and N2).

    ``<use>``, ``pattern``, ``mask``, ``clipPath`` and ``symbol`` draw their content again at every
    reference, so a chain multiplies: ten levels of ten give 10^10 drawn copies. Gradients only
    inherit stops from the gradient they point at, so a reference to a gradient is always fine.
    """
    parent = {child: el for el in root.iter() for child in el}
    holds: set[Element] = set()  # elements that are, or contain, a referencing element
    for el in root.iter():
        node: Element | None = el if _references(el) else None
        while node is not None and node not in holds:
            holds.add(node)
            node = parent.get(node)
    # Browsers resolve a repeated id to its first element; refusing repeats means the check and
    # the browser always agree on what a reference points at (re-verification 2, N5).
    by_id: dict[str, Element] = {}
    for el in root.iter():
        el_id = el.get("id")
        if el_id is None:
            continue
        if el_id in by_id:
            raise LogoRejectedError(f'An SVG logo may not repeat the id "{el_id}".')
        by_id[el_id] = el
    for el in root.iter():
        for target_id in _references(el):
            target = by_id.get(target_id)
            if target is not None and target in holds and target.tag not in _GRADIENTS:
                raise LogoRejectedError(
                    "An SVG logo may not point at a shape, pattern or mask that points further."
                )


def _check_element(element: Element) -> None:
    tag = element.tag
    local = tag[len(_SVG_NS) :] if isinstance(tag, str) and tag.startswith(_SVG_NS) else None
    if local not in ELEMENTS:
        name = tag.rsplit("}", 1)[-1] if isinstance(tag, str) else "processing instruction"
        raise LogoRejectedError(f"SVG logos may not contain <{name}>.")
    for attr, value in element.attrib.items():
        if attr not in ATTRIBUTES:
            raise LogoRejectedError(
                f"SVG logos may not use the {attr.rsplit('}', 1)[-1]} attribute."
            )
        if attr in ("href", _XLINK_HREF) and not _FRAGMENT.fullmatch(value.strip()):
            raise LogoRejectedError("Links in an SVG logo may only point inside the file.")
        _check_value(attr, value)


def _check_value(attr: str, value: str) -> None:
    if any(mark in value for mark in _FORBIDDEN):
        raise LogoRejectedError("An SVG logo may not use CSS escapes, comments or @ rules.")
    rest = _LOCAL_URL.sub("", value)
    rest = _COLOUR_FN.sub("", rest)
    if attr in _TRANSFORM_ATTRS:
        rest = _TRANSFORM_FN.sub("", rest)
    if "(" in rest or ")" in rest:
        raise LogoRejectedError("An SVG logo may not load anything from elsewhere.")
