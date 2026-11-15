"""BL-68: the legal page renderer keeps only safe, self-contained HTML."""

from __future__ import annotations

import pytest

from regwatch.admin.legal import render


def test_commonmark_with_tables_and_links() -> None:
    table = "| a | b |\n|---|---|\n| 1 | 2 |"
    html = render(f"# Legal\n\n**Bold** [site](https://example.org)\n\n{table}")
    assert html.startswith("<h1>Legal</h1>")
    assert "<strong>Bold</strong>" in html
    assert '<a href="https://example.org" rel="noopener noreferrer nofollow">site</a>' in html
    assert "<td>1</td>" in html


@pytest.mark.parametrize(
    "source",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        '<a href="javascript:alert(1)">x</a>',
        "<iframe src=https://example.org></iframe>",
        "<style>body{display:none}</style>",
        "<!-- comment -->",
    ],
)
def test_raw_html_is_text_not_markup(source: str) -> None:
    html = render(source)
    assert "<" + source[1:4] not in html  # the tag never appears as markup
    assert "&lt;" in html


@pytest.mark.parametrize(
    "link",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "vbscript:msgbox(1)",
        "data:text/html,<b>x</b>",
        "file:///etc/passwd",
    ],
)
def test_dangerous_link_schemes_are_dropped(link: str) -> None:
    html = render(f"[x]({link})")
    assert "href" not in html


def test_mailto_and_relative_links_stay() -> None:
    html = render("[m](mailto:legal@example.org) [r](/help)")
    assert 'href="mailto:legal@example.org"' in html and 'href="/help"' in html


def test_images_are_dropped_so_nothing_loads_from_elsewhere() -> None:
    assert "<img" not in render("![pixel](https://tracker.example/p.png)")


def test_attributes_outside_the_allowlist_are_removed() -> None:
    html = render('[x](https://example.org "title")')
    assert 'title="title"' in html
    escaped = render('<a href="https://e.org" onclick="x()">y</a>')
    assert "<a " not in escaped and "&lt;a href" in escaped


def test_empty_page() -> None:
    assert render("") == ""


async def test_render_runs_off_the_event_loop() -> None:
    from regwatch.admin.legal import render_async

    assert await render_async("# Fine") == "<h1>Fine</h1>\n"


async def test_slow_pages_are_refused_and_their_render_is_killed() -> None:
    """BL-68 review finding 4 and N1: the check runs in a process that is killed at the budget."""
    import time

    from regwatch.admin.legal import LegalTooComplexError, check_budget

    await check_budget("# Short page")  # below the size where a check is needed
    await check_budget("Plain text. " * 1000, budget=5)
    started = time.monotonic()
    with pytest.raises(LegalTooComplexError):
        await check_budget("![" * 100_000 + "x", budget=0.2)
    assert time.monotonic() - started < 10  # not the 12 s a full render takes
