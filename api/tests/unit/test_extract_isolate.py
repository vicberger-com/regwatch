"""Extraction in a child process with hard limits (ADR-0009 amendment 1; review finding 1)."""

from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from typing import Any

import pytest

from regwatch.capture.connectors.config import ExtractionRules
from regwatch.capture.extract import child, isolate
from regwatch.capture.extract.tree import ParseError

PAGE = (
    b"<title>T</title><main><p>" + b"word " * 100 + b"<time datetime=2026-11-17>x</time></p></main>"
)


async def test_a_page_is_extracted_in_a_child_process() -> None:
    got = await isolate.extract_isolated(PAGE, "utf-8", ExtractionRules(date_selector="time"))
    day = datetime(2026, 11, 17, tzinfo=UTC)
    assert (got.method, got.title, got.published_at) == ("main", "T", day)
    assert got.text.startswith("word word") and len(got.content_hash) == 64


async def test_the_tokenizer_cannot_stall_a_run() -> None:
    """The review's slowest probe ran 295 s in process; the child's CPU limit ends it."""
    started = time.monotonic()
    with pytest.raises(ParseError) as exc:
        await isolate.extract_isolated(b"<p>" + b"< " * 1_048_574, None, ExtractionRules())
    assert exc.value.reason == "too-slow" and time.monotonic() - started < isolate.WALL_SECONDS


@pytest.mark.parametrize(
    ("script", "reason"),
    [("import time; time.sleep(30)", "too-slow"),
     ("import sys; sys.exit(3)", "parse-failed"),
     ("print('not json')", "parse-failed"),
     ("print('{\"text\": 1}')", "parse-failed"),
     ("print('{\"error\": \"too-deep\"}')", "too-deep"),
     ("import os, signal; os.kill(os.getpid(), signal.SIGXCPU)", "too-slow")],
)  # fmt: skip
async def test_a_child_that_fails_is_a_parse_error(monkeypatch: pytest.MonkeyPatch, script: str,
                                                   reason: str) -> None:  # fmt: skip
    monkeypatch.setattr(isolate, "COMMAND", (sys.executable, "-I", "-c", script))
    monkeypatch.setattr(isolate, "WALL_SECONDS", 2.0)
    with pytest.raises(ParseError) as exc:
        await isolate.extract_isolated(b"<p>x</p>", None, ExtractionRules())
    assert exc.value.reason == reason


def test_the_child_answers_errors_by_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    body = base64.b64encode(b"<div>" * 1000).decode()
    assert child.answer({"body": body}) == {"error": "too-deep"}

    def no_memory(body: bytes, encoding: str | None = None) -> None:
        raise MemoryError

    monkeypatch.setattr("regwatch.capture.extract.tree.parse", no_memory)
    assert child.answer({"body": body, "rules": {}}) == {"error": "too-large"}


def test_the_child_answers_a_page_and_limits_itself() -> None:
    got = child.answer({"body": base64.b64encode(PAGE).decode(), "encoding": None,
                        "rules": {"date_selector": "time"}})  # fmt: skip
    assert got["method"] == "main" and got["published_at"] == "2026-11-17T00:00:00+00:00"
    probe = ("import resource; from regwatch.capture.extract import child; child._limit(); "
             "print(resource.getrlimit(resource.RLIMIT_CPU)[0], "
             "resource.getrlimit(resource.RLIMIT_AS)[0])")  # fmt: skip
    out = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, check=True,  # noqa: S603 - a fixed probe
                         text=True).stdout.split()  # fmt: skip
    assert [int(x) for x in out] == [child.CPU_SECONDS, child.ADDRESS_SPACE_BYTES]


async def test_a_cancelled_caller_leaves_no_child(monkeypatch: pytest.MonkeyPatch,
                                                  tmp_path: Any) -> None:  # fmt: skip
    """Re-verification R1: a soft time limit or an aborted run cancels the call."""
    pid_file = tmp_path / "pid"
    script = (
        f"import os, time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(60)"
    )
    monkeypatch.setattr(isolate, "COMMAND", (sys.executable, "-I", "-c", script))
    task = asyncio.create_task(isolate.extract_isolated(b"<p>x</p>", None, ExtractionRules()))
    for _ in range(100):
        if pid_file.exists() and pid_file.read_text():
            break
        await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


async def test_only_what_is_parsed_is_sent() -> None:
    """R5: a 6 MiB body sends 2 MiB and one byte; the child still reports the cut."""
    got = await isolate.extract_isolated(b"<p>" + b"word " * 1_200_000, None, ExtractionRules())
    assert got.warnings[0].startswith("the page was longer")
