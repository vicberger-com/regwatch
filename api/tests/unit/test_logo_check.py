"""BL-68, M1 acceptance 6: logo uploads are a PNG or an SVG that cannot run or fetch anything."""

from __future__ import annotations

import struct
import zlib

import pytest

from regwatch.admin.logo import MAX_BYTES, MAX_ELEMENTS, PNG, SVG, LogoRejectedError, check

NS = 'xmlns="http://www.w3.org/2000/svg"'
XLINK = 'xmlns:xlink="http://www.w3.org/1999/xlink"'


def png(width: int = 16, height: int = 16) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(kind + body))
        return struct.pack(">I", len(body)) + kind + body + crc

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


def svg(body: str, attrs: str = "") -> bytes:
    return f'<svg {NS} {XLINK} viewBox="0 0 10 10" {attrs}>{body}</svg>'.encode()


def test_png_is_accepted_by_content() -> None:
    assert check(png()) == PNG


@pytest.mark.parametrize(("w", "h"), [(0, 10), (10, 0), (4097, 10), (10, 4097)])
def test_png_size_is_bounded(w: int, h: int) -> None:
    with pytest.raises(LogoRejectedError, match="4096"):
        check(png(w, h))


def test_damaged_png_is_refused() -> None:
    with pytest.raises(LogoRejectedError, match="damaged"):
        check(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)


def test_a_plain_svg_with_local_references_is_accepted() -> None:
    body = (
        '<defs><linearGradient id="g"><stop offset="0" stop-color="#123"/></linearGradient>'
        '<symbol id="s"><circle r="2"/></symbol></defs>'
        '<rect width="10" height="10" fill="url(#g)" stroke="rgb(10, 20, 30)"/>'
        '<g transform="translate(1 2) rotate(45) scale(.5)"><path d="M0 0L1 1"/></g>'
        '<use href="#s"/><use xlink:href="#s"/><title>Logo</title><text x="1">Acme</text>'
    )
    assert check(b"\xef\xbb\xbf<?xml version='1.0'?>\n" + svg(body)) == SVG


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (svg("<script>alert(1)</script>"), "<script>"),
        (
            svg('<foreignObject><div xmlns="http://www.w3.org/1999/xhtml"/></foreignObject>'),
            "<foreignObject>",
        ),
        (svg("<style>rect{fill:url(https://e.example/x)}</style>"), "<style>"),
        (svg('<animate attributeName="href" to="javascript:alert(1)"/>'), "<animate>"),
        (svg('<set attributeName="onload" to="x"/>'), "<set>"),
        (svg('<a href="https://e.example"><rect/></a>'), "<a>"),
        (svg('<image href="https://e.example/p.png"/>'), "<image>"),
        (svg("", 'onload="alert(1)"'), "onload"),
        (svg('<rect onclick="x()"/>'), "onclick"),
        (svg('<use href="https://e.example/a.svg#x"/>'), "inside the file"),
        (svg('<use xlink:href="data:image/svg+xml,&lt;svg/&gt;"/>'), "inside the file"),
        (svg('<rect fill="url(https://e.example/x)"/>'), "elsewhere"),
        (svg('<rect fill="url(#ok) url(https://e.example/x)"/>'), "elsewhere"),
        (svg("<rect style=\"fill:red;@import 'x.css'\"/>"), "style"),
        (svg('<rect style="width:expression(alert(1))"/>'), "style"),
        (b"<?xml-stylesheet href='https://e.example/x.css'?>" + svg(""), "elsewhere"),
        (svg("", 'xmlns:ev="http://www.w3.org/2001/xml-events" ev:event="load"'), "event"),
        (b'<svg xmlns="http://www.w3.org/1999/xhtml"/>', "not an SVG"),
    ],
)
def test_unsafe_svg_is_refused(data: bytes, reason: str) -> None:
    with pytest.raises(LogoRejectedError, match=reason):
        check(data)


def test_doctype_and_entities_are_refused() -> None:
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaaaaaaaa">'
        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        b'<svg xmlns="http://www.w3.org/2000/svg"><text>&b;</text></svg>'
    )
    with pytest.raises(LogoRejectedError, match="DOCTYPE"):
        check(bomb)
    external = (
        b'<!DOCTYPE svg SYSTEM "file:///etc/passwd"><svg xmlns="http://www.w3.org/2000/svg"/>'
    )
    with pytest.raises(LogoRejectedError, match="DOCTYPE"):
        check(external)


def test_malformed_and_other_types_are_refused() -> None:
    with pytest.raises(LogoRejectedError, match="well-formed"):
        check(b"<svg><rect></svg>")
    for data in (b"GIF89a....", b"\xff\xd8\xff\xe0JFIF", b"<html><body/></html>"):
        with pytest.raises(LogoRejectedError, match="PNG or SVG"):
            check(data)
    with pytest.raises(LogoRejectedError, match="empty"):
        check(b"")


def test_size_and_element_count_are_bounded() -> None:
    with pytest.raises(LogoRejectedError, match="1 MB"):
        check(png() + b"\x00" * MAX_BYTES)
    with pytest.raises(LogoRejectedError, match=str(MAX_ELEMENTS)):
        check(svg("<g/>" * MAX_ELEMENTS))


@pytest.mark.parametrize(
    "data",
    [
        svg('<rect fill="\\75 rl(https://e.example/x)"/>'),
        svg('<rect fill="u\\rl(https://e.example/x)"/>'),
        svg("<rect mask=\"image-set('https://e.example/x.png' 1x)\"/>"),
        svg('<rect fill="url( https://e.example/x )"/>'),
        svg("<rect fill=\"url('#ok') url(//e.example/x)\"/>"),
        svg('<rect fill="red /* comment */"/>'),
        svg('<rect fill="@import"/>'),
        svg('<rect fill="rgb(var(--x))"/>'),
        svg('<rect transform="translate(url(#a))"/>'),
        svg('<rect fill="translate(1)"/>'),
        svg('<rect style="fill:red"/>'),
    ],
)
def test_css_tricks_in_values_are_refused(data: bytes) -> None:
    """BL-68 review finding 2: only url(#id), colour and transform functions may use "("."""
    with pytest.raises(LogoRejectedError):
        check(data)


def test_use_chains_are_refused_but_single_references_pass() -> None:
    """BL-68 review finding 3: references to a <use> would multiply the drawn copies."""
    single = '<defs><circle id="c" r="1"/></defs>' + '<use href="#c"/>' * 50
    assert check(svg(single)) == SVG
    chain = '<defs><circle id="a0" r="1"/><g id="a1"><use href="#a0"/><use href="#a0"/></g></defs>'
    with pytest.raises(LogoRejectedError, match="another <use>"):
        check(svg(chain + '<use href="#a1"/>'))
    direct = '<defs><circle id="c" r="1"/><use id="u" href="#c"/></defs><use xlink:href="#u"/>'
    with pytest.raises(LogoRejectedError, match="another <use>"):
        check(svg(direct))
