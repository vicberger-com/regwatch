"""Unit: the report renderer's escaping helpers (M7.2)."""

from __future__ import annotations

import pytest

from regwatch.reports.render import css_text, web_link


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("Page 1", "Page 1"),
        ('x"; } *', "x\\000022 \\00003b  \\00007d  \\00002a "),
        ("\\", "\\00005c "),
        ("</style>", "\\00003c \\00002f style\\00003e "),
        ("é", "\\0000e9 "),
        ("a, b", "a\\00002c  b"),  # the space after the comma survives
    ],
)
def test_css_text_leaves_only_letters_digits_and_spaces(raw: str, escaped: str) -> None:
    out = css_text(raw)
    assert out == escaped
    assert all(c.isalnum() or c in " \\" for c in out)


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://example.org/a", True), ("http://example.org/", True),
        ("javascript:alert(1)", False), ("data:text/html,x", False), ("//example.org", False),
        ("https://user@example.org/", False), ("https:///nohost", False), ("", False),
        ("https://example.org/" + "a" * 2048, False),
    ],
)  # fmt: skip
def test_only_web_links_become_links(url: str, ok: bool) -> None:
    assert (web_link(url) is not None) is ok
