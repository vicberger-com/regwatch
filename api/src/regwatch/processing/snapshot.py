"""Sanitized HTML snapshots (M4 design notes: "sanitize extracted HTML with nh3 before storage;
store plain text for search and sanitized HTML reference for display"; owner decision
2026-11-19: stored now, served later through a CP'd route).

- Only an HTML body this source stored itself (``raw/{source_id}/<hex64>``) is read, and only up
  to ``MAX_BYTES``; it is decoded as UTF-8 (the charset the page declares comes with the
  serving route's CP), with errors replaced.
- nh3 (ammonia) keeps a short allowlist of text and structure elements: no scripts, styles,
  forms, frames, media or event attributes; links keep ``href`` with http, https and mailto
  only and get ``rel="noopener noreferrer nofollow"``; images are dropped (no fetches from a
  stored page). The result is stored at ``html/{item_id}/{version_no}.html``.
- A snapshot never fails a row: anything that goes wrong leaves ``content_html_ref`` empty.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable

import nh3
import structlog

MAX_BYTES = 5 * 1024 * 1024
TAGS = {"a", "abbr", "article", "b", "blockquote", "br", "caption", "cite", "code", "dd",
        "del", "details", "dfn", "div", "dl", "dt", "em", "figcaption", "figure", "h1", "h2",
        "h3", "h4", "h5", "h6", "hr", "i", "ins", "kbd", "li", "main", "mark", "ol", "p",
        "pre", "q", "s", "section", "small", "span", "strong", "sub", "summary", "sup",
        "table", "tbody", "td", "tfoot", "th", "thead", "time", "tr", "u", "ul"}  # fmt: skip
ATTRIBUTES = {"a": {"href", "title"}, "td": {"colspan", "rowspan"}, "th": {"colspan", "rowspan",
              "scope"}, "time": {"datetime"}, "ol": {"start"}}  # fmt: skip
URL_SCHEMES = {"http", "https", "mailto"}
_log = structlog.get_logger(__name__)

Load = Callable[[str], Awaitable[bytes | None]]
Store = Callable[[str, bytes], Awaitable[None]]


def sanitize(body: bytes) -> str:
    return nh3.clean(body[:MAX_BYTES].decode("utf-8", errors="replace"), tags=TAGS,
                     clean_content_tags={"script", "style", "template", "noscript"},
                     attributes=ATTRIBUTES, url_schemes=URL_SCHEMES,
                     link_rel="noopener noreferrer nofollow", strip_comments=True)  # fmt: skip


def key(item_id: uuid.UUID, version_no: int) -> str:
    return f"html/{item_id}/{version_no}.html"


async def snapshot(row: dict[str, object], source_id: uuid.UUID, item_id: uuid.UUID,
                   version_no: int, load: Load, store: Store) -> str | None:  # fmt: skip
    """The stored snapshot's key, or None (not HTML, not this source's body, or a failure)."""
    ref, mime = row.get("body_ref"), row.get("mime")
    if not isinstance(ref, str) or not isinstance(mime, str) or not mime.startswith("text/html"):
        return None
    if not re.fullmatch(rf"raw/{source_id}/[0-9a-f]{{64}}", ref):
        return None
    try:
        body = await load(ref)
        if body is None or len(body) > MAX_BYTES:
            return None
        made = key(item_id, version_no)
        await store(made, sanitize(body).encode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - a snapshot never fails the row
        _log.warning("snapshot_failed", error=type(exc).__name__)
        return None
    return made
