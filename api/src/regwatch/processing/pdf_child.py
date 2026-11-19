"""The limited child process: ``python -I -m regwatch.processing.pdf_child [pdf|sanitize]``.

As ``capture.extract.child`` does for HTML (ADR-0009 amendment 1), it limits itself before
reading anything (``RLIMIT_CPU``, ``RLIMIT_AS``), then reads one PDF on stdin and writes one
JSON answer: ``{"text": ...}`` or ``{"error": reason}``. A captured PDF is hostile: pypdf can
be driven into long loops or large allocations, and here the kernel stops it.
"""

from __future__ import annotations

import io
import json
import resource
import sys
from typing import Any

CPU_SECONDS = 20
ADDRESS_SPACE_BYTES = 1024 * 1024 * 1024
MAX_PAGES = 500
MAX_TEXT = 1_000_000


def _limit() -> None:  # pragma: no cover - in the child only
    for which, value in ((resource.RLIMIT_CPU, CPU_SECONDS),
                         (resource.RLIMIT_AS, ADDRESS_SPACE_BYTES)):  # fmt: skip
        _soft, hard = resource.getrlimit(which)
        cap = value if hard == resource.RLIM_INFINITY else min(hard, value)
        resource.setrlimit(which, (cap, hard))


def answer(body: bytes) -> dict[str, Any]:
    """The text of the first ``MAX_PAGES`` pages; also called directly by tests."""
    import logging

    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    logging.getLogger("pypdf").setLevel(logging.CRITICAL)  # its warnings are not our output
    try:
        reader = PdfReader(io.BytesIO(body), strict=False)
        if reader.is_encrypted:
            return {"error": "encrypted"}
        parts: list[str] = []
        size = 0
        for page in reader.pages[:MAX_PAGES]:
            got = page.extract_text() or ""
            parts.append(got)
            size += len(got)
            if size >= MAX_TEXT:
                break
    except MemoryError:
        return {"error": "too-large"}
    except (PdfReadError, ValueError, KeyError, TypeError, AttributeError, IndexError,
            RecursionError, OSError, ZeroDivisionError, AssertionError):  # fmt: skip
        return {"error": "unreadable"}
    text = "\n\n".join(parts)[:MAX_TEXT]
    return {"text": text}


def sanitized(body: bytes) -> dict[str, Any]:
    """nh3 on an HTML body (enrichment review N19: deep nesting costs quadratic time, so it
    runs here, under the same limits, never in the worker)."""
    from regwatch.processing.snapshot import sanitize

    try:
        return {"html": sanitize(body)}
    except MemoryError:
        return {"error": "too-large"}


def main() -> None:  # pragma: no cover - run as a process by processing.pdf
    _limit()
    body = sys.stdin.buffer.read()
    mode = sys.argv[1] if len(sys.argv) > 1 else "pdf"
    sys.stdout.write(json.dumps(sanitized(body) if mode == "sanitize" else answer(body)))


if __name__ == "__main__":  # pragma: no cover
    main()
