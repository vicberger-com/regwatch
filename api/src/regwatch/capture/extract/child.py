"""The extraction child process: ``python -I -m regwatch.capture.extract.child``.

It limits itself before reading anything, then reads one JSON request on stdin (the body in
base64, the server's charset, the extraction rules), and writes one JSON answer on stdout: the
extracted fields, or ``{"error": reason}``. The limits hold where the in-process caps cannot
(HTML extraction review finding 1): html5lib can spend minutes in its tokenizer, or in quadratic
string building, without pushing an element, and a thread cannot be stopped. Here the kernel
stops it: ``RLIMIT_CPU`` and ``RLIMIT_AS``, and the parent's wall-clock timeout (isolate.py).
"""

from __future__ import annotations

import base64
import json
import resource
import sys
from typing import Any

CPU_SECONDS = 10  # a normal 2 MiB page takes about 1 s
ADDRESS_SPACE_BYTES = 1024 * 1024 * 1024


def _limit() -> None:  # pragma: no cover - in the child only; a test checks the limits
    for which, value in ((resource.RLIMIT_CPU, CPU_SECONDS),
                         (resource.RLIMIT_AS, ADDRESS_SPACE_BYTES)):  # fmt: skip
        _soft, hard = resource.getrlimit(which)
        cap = value if hard == resource.RLIM_INFINITY else min(hard, value)
        resource.setrlimit(which, (cap, hard))


def answer(request: dict[str, Any]) -> dict[str, Any]:
    """The answer to one request; also called directly by tests."""
    from regwatch.capture.connectors.config import ExtractionRules
    from regwatch.capture.extract import text, tree

    try:
        page = tree.parse(base64.b64decode(request["body"]), request.get("encoding"))
        got = text.extract(page, ExtractionRules.model_validate(request.get("rules") or {}))
    except tree.ParseError as exc:
        return {"error": exc.reason}
    except MemoryError:
        return {"error": "too-large"}
    return {"text": got.text, "content_hash": got.content_hash, "title": got.title,
            "published_at": got.published_at.isoformat() if got.published_at else None,
            "method": got.method, "warnings": got.warnings}  # fmt: skip


def main() -> None:  # pragma: no cover - run as a process by isolate.py; tested there
    _limit()
    result = answer(json.loads(sys.stdin.buffer.read()))
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":  # pragma: no cover
    main()
