"""Extraction in a child process with hard limits (ADR-0009 amendment 1; HTML extraction review
finding 1).

``extract_isolated`` starts ``python -I -m regwatch.capture.extract.child`` for one document,
with an empty environment but ``PATH`` and the C locale, writes the request, and waits at most
``WALL_SECONDS``. A child that runs over is killed; one that dies (for example on its CPU
limit) or answers nonsense is a ``ParseError`` too, never an internal error of the run. A plain
subprocess, not multiprocessing, so it works inside Celery's daemonic prefork workers.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import signal
import sys
import weakref
from datetime import datetime
from typing import Any

from regwatch.capture.connectors.config import ExtractionRules
from regwatch.capture.extract.text import Extracted
from regwatch.capture.extract.tree import MAX_PARSE_BYTES
from regwatch.capture.extract.tree import ParseError as ParseError  # callers import it here

WALL_SECONDS = 20.0  # over the child's CPU limit (10 s), for start-up and a busy host
MAX_ANSWER = 16 * 1024 * 1024
COMMAND = (sys.executable, "-I", "-m", "regwatch.capture.extract.child")


_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)


async def extract_isolated(body: bytes, encoding: str | None,
                           rules: ExtractionRules) -> Extracted:  # fmt: skip
    """One child at a time per worker process (HTML extraction review R4, BL-98 (a); web page
    review finding 6): each child may take 1 GiB and 10 s of CPU, so concurrent callers in one
    process wait their turn instead of multiplying that."""
    loop = asyncio.get_running_loop()
    lock = _locks.setdefault(loop, asyncio.Lock())
    async with lock:
        return await _extract(body, encoding, rules)


async def _extract(body: bytes, encoding: str | None, rules: ExtractionRules) -> Extracted:
    # Only what the child parses, plus one byte so it knows the page was cut (R5).
    body = body[: MAX_PARSE_BYTES + 1]
    request = json.dumps({"body": base64.b64encode(body).decode(), "encoding": encoding,
                          "rules": rules.model_dump(mode="json")}).encode()  # fmt: skip
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    child = await asyncio.create_subprocess_exec(
        *COMMAND, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, env=env)  # fmt: skip
    try:
        out, _ = await asyncio.wait_for(child.communicate(request), WALL_SECONDS)
    except TimeoutError:
        raise ParseError("too-slow", f"extraction took longer than {WALL_SECONDS:g} s") from None
    finally:
        # On a timeout, and on a cancellation too (a soft time limit, an aborted run): never
        # leave a child running after its caller has gone (re-verification R1).
        if child.returncode is None:
            child.kill()
            await asyncio.shield(child.wait())
    if child.returncode in (-signal.SIGXCPU, -signal.SIGKILL):  # its CPU limit
        raise ParseError("too-slow", "extraction ran past its CPU limit")
    if child.returncode != 0 or len(out) > MAX_ANSWER:
        raise ParseError("parse-failed", f"the extraction process failed ({child.returncode})")
    return _answer(out)


def _answer(out: bytes) -> Extracted:
    try:
        got: Any = json.loads(out)
        if "error" in got:
            raise ParseError(str(got["error"])[:40], "the page could not be extracted")
        published = got["published_at"]
        return Extracted(text=got["text"], content_hash=got["content_hash"], title=got["title"],
                         published_at=datetime.fromisoformat(published) if published else None,
                         method=got["method"], warnings=list(got["warnings"]))  # fmt: skip
    except ParseError:
        raise
    except (ValueError, KeyError, TypeError):
        raise ParseError("parse-failed", "the extraction process answered nonsense") from None
