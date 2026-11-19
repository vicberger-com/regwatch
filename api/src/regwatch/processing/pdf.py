"""PDF and XHTML text for body-only rows (M4 scope, roadmap 4.5; owner decision 2026-11-19:
pypdf 7.1.1, in a sandboxed child; closes BL-107 (b) and R15, BL-109 (b)).

A manifest row without text whose body this source stored itself (``raw/{source_id}/<hex64>``)
gets its text here, before ingest: a PDF through ``pdf_child`` (pypdf, CPU and memory limits, a
wall clock, one child at a time per process), XHTML (EUR-Lex, legislation.gov.uk) through M3's
isolated HTML extractor. Bodies over ``MAX_BYTES`` are left as they are. A failure leaves the
row body-only, as before; it never fails the row.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
import weakref
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

MAX_BYTES = 20 * 1024 * 1024
WALL_SECONDS = 30.0  # over the child's CPU limit (20 s)
MAX_ANSWER = 8 * 1024 * 1024
COMMAND = (sys.executable, "-I", "-m", "regwatch.processing.pdf_child")
PDF = ("application/pdf",)
XHTML = ("application/xhtml+xml",)  # not text/html: a feed's fetched page keeps its rules (N7)
_log = structlog.get_logger(__name__)
_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)
Load = Callable[[str], Awaitable[bytes | None]]


async def pdf_text(body: bytes) -> str | None:
    loop = asyncio.get_running_loop()
    async with _locks.setdefault(loop, asyncio.Lock()):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
        child = await asyncio.create_subprocess_exec(
            *COMMAND, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=env)  # fmt: skip
        try:
            out, _ = await asyncio.wait_for(child.communicate(body), WALL_SECONDS)
        except TimeoutError:
            return None
        finally:
            if child.returncode is None:
                child.kill()
                await asyncio.shield(child.wait())
    if child.returncode != 0 or len(out) > MAX_ANSWER:
        return None
    try:
        got: Any = json.loads(out)
    except ValueError:
        return None
    text = got.get("text") if isinstance(got, dict) else None
    return text if isinstance(text, str) and text.strip() else None


async def xhtml_text(body: bytes) -> str | None:
    from regwatch.capture.connectors.config import ExtractionRules
    from regwatch.capture.extract.isolate import ParseError, extract_isolated

    try:
        got = await extract_isolated(body, None, ExtractionRules())
    except ParseError:
        return None
    return got.text or None


async def with_text(row: dict[str, Any], source_id: uuid.UUID, load: Load) -> dict[str, Any]:
    """``row`` with ``text`` filled from its stored body when it had none."""
    if isinstance(row.get("text"), str) and row["text"].strip():
        return row
    ref, mime = row.get("body_ref"), str(row.get("mime") or "").split(";")[0].strip().lower()
    if not isinstance(ref, str) or not re.fullmatch(rf"raw/{source_id}/[0-9a-f]{{64}}", ref):
        return row
    if mime not in PDF + XHTML:
        return row
    try:
        body = await load(ref)
        if body is None or len(body) > MAX_BYTES:
            return row
        text = await (pdf_text(body) if mime in PDF else xhtml_text(body))
    except Exception as exc:  # noqa: BLE001 - extraction never fails the row
        _log.warning("body_text_failed", mime=mime, error=type(exc).__name__)
        return row
    return {**row, "text": text} if text else row
