"""The legal page: owner-written Markdown rendered to HTML that is safe to insert (BL-68).

Two layers, so neither alone is the security boundary:

1. markdown-it-py with the ``js-default`` preset: CommonMark with raw HTML switched off, so
   ``<script>`` in the source comes out as escaped text, and with markdown-it's own link
   validation (no ``javascript:``, ``vbscript:``, ``file:`` or non-image ``data:`` URLs).
2. nh3 (ammonia) with a short allowlist of the elements CommonMark produces, links limited to
   http, https and mailto, every link given ``rel="noopener noreferrer nofollow"``, and no
   images, so the page never loads anything from another site (CSP ``img-src 'self'``).

markdown-it-py is quadratic on some inputs (``"![" * 100000`` takes seconds), so (BL-68 review
finding 4 and re-verification N1):

- every save, through ``PUT /admin/legal`` or the settings API, first renders the page in a
  separate process that is killed after ``SAVE_BUDGET`` seconds; a page that does not finish is
  refused, so only pages that render quickly are ever stored;
- ``GET /legal`` renders in a dedicated two-thread pool, never on the event loop, never in the
  shared default pool and never behind a budget check, and caches the result.
"""

from __future__ import annotations

import asyncio
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from multiprocessing.connection import Connection

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
SAVE_BUDGET = 2.0  # seconds


class LegalTooComplexError(ValueError):
    """The Markdown takes longer than ``SAVE_BUDGET`` to render."""


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


_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="legal-render")
# Budget checks wait on child processes; their own pool keeps GET /legal from queueing behind
# them (review 2, N4) and bounds the checks, and so the processes, to two at a time.
_CHECKS = ThreadPoolExecutor(max_workers=2, thread_name_prefix="legal-check")
_STARTUP = 20.0  # seconds a fresh process may take to import before the budget starts


async def render_async(markdown: str) -> str:
    """``render`` in the legal pool, off the event loop and out of the shared pool."""
    return await asyncio.get_running_loop().run_in_executor(_POOL, render, markdown)


def _child(conn: Connection, markdown: str) -> None:  # pragma: no cover - runs in the child
    conn.send("ready")  # imports are done; the budget starts now
    conn.send(render(markdown))


def _within_budget(markdown: str, budget: float) -> bool:
    parent, child = multiprocessing.get_context("spawn").Pipe(duplex=False)
    proc = multiprocessing.get_context("spawn").Process(
        target=_child, args=(child, markdown), daemon=True
    )
    proc.start()
    child.close()
    try:
        if not parent.poll(_STARTUP) or parent.recv() != "ready":
            raise RuntimeError("the legal page check could not start")
        if not parent.poll(budget):
            return False
        try:
            parent.recv()  # a child that died without an answer has not passed (review 2, N6)
        except EOFError:
            raise RuntimeError("the legal page check ended without a result") from None
        return True
    finally:
        proc.kill()  # finished or not, the child goes now
        proc.join()
        parent.close()


async def check_budget(markdown: str, budget: float = SAVE_BUDGET) -> None:
    """``LegalTooComplexError`` unless ``markdown`` renders within ``budget`` seconds."""
    if len(markdown) < 1000:
        return  # far below any input that is slow to render
    ok = await asyncio.get_running_loop().run_in_executor(_CHECKS, _within_budget, markdown, budget)
    if not ok:
        raise LegalTooComplexError
