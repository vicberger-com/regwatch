"""The legal page: owner-written Markdown rendered to HTML that is safe to insert (BL-68).

Two layers, so neither alone is the security boundary:

1. markdown-it-py with the ``js-default`` preset: CommonMark with raw HTML switched off, so
   ``<script>`` in the source comes out as escaped text, and with markdown-it's own link
   validation (no ``javascript:``, ``vbscript:``, ``file:`` or non-image ``data:`` URLs).
2. nh3 (ammonia) with a short allowlist of the elements CommonMark produces, links limited to
   http, https and mailto, every link given ``rel="noopener noreferrer nofollow"``, and no
   images, so the page never loads anything from another site (CSP ``img-src 'self'``).
"""

from __future__ import annotations

from functools import lru_cache

import nh3
from markdown_it import MarkdownIt

TAGS = {
    "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "em", "code", "pre", "blockquote",
    "ul", "ol", "li", "a",
    "table", "thead", "tbody", "tr", "th", "td",
}  # fmt: skip
ATTRIBUTES = {"a": {"href", "title"}, "ol": {"start"}, "th": {"align"}, "td": {"align"}}
URL_SCHEMES = {"http", "https", "mailto"}

_markdown = MarkdownIt("js-default").enable("table")


@lru_cache(maxsize=8)
def render(markdown: str) -> str:
    """HTML for ``markdown``: rendered without raw HTML, then sanitized."""
    return nh3.clean(
        _markdown.render(markdown),
        tags=TAGS,
        attributes=ATTRIBUTES,
        url_schemes=URL_SCHEMES,
        link_rel="noopener noreferrer nofollow",
        strip_comments=True,
    )
