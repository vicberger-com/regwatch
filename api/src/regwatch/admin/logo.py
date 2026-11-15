"""Logo checks (BL-68, M1 acceptance 6): a PNG, or an SVG that cannot run or fetch anything.

The file is refused, never rewritten: what is stored is exactly what passed. The media type comes
from the content, not from what the client declared.

SVG: parsed with defusedxml (no DTD, entities or external references), then every element must
be in the SVG namespace and on ``ELEMENTS``, and every attribute on ``ATTRIBUTES``. That leaves out
``script``, ``foreignObject``, ``style``, animation and every ``on*`` handler. A ``href`` may only
point inside the document (``#id``), and ``url(...)`` in a value may only be ``url(#id)``. The
logo is shown only through ``<img>`` (where scripts never run) and served with its own strict CSP,
so this check is the second of two layers.
"""

from __future__ import annotations

import re
import struct
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as SafeXML
from defusedxml import DefusedXmlException

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
    "dominant-baseline", "letter-spacing", "style", "href", _XLINK_HREF, _XML_SPACE,
})  # fmt: skip
_URL = re.compile(r"url\s*\(", re.IGNORECASE)
_LOCAL_URL = re.compile(r"url\s*\(\s*['\"]?#", re.IGNORECASE)
_STYLE_DENY = re.compile(r"@import|expression\s*\(|javascript:|behavio(u)?r\s*:|-moz-binding", re.I)


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
        if attr in ("href", _XLINK_HREF) and not value.strip().startswith("#"):
            raise LogoRejectedError("Links in an SVG logo may only point inside the file.")
        if _URL.search(value) and len(_URL.findall(value)) != len(_LOCAL_URL.findall(value)):
            raise LogoRejectedError("An SVG logo may not load anything from elsewhere.")
        if attr == "style" and _STYLE_DENY.search(value):
            raise LogoRejectedError("The style in this SVG logo is not allowed.")
