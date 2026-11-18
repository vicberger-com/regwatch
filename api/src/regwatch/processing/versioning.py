"""Canonical URLs, content hashes, the change share and diffs (M4 design notes; schema.sql).

- The canonical URL is the address as SafeFetcher parses it: scheme and host in lower case,
  no default port, no fragment. Its SHA-256 is ``item.url_hash``. A manual upload's
  ``urn:sha256:`` address is canonical already.
- ``changed_pct`` is M4's rule: differing characters over the longer text, 0 to 100. The texts
  are compared line by line first (``difflib``), and characters are counted only inside the
  lines that differ, so a long text costs lines times lines, never characters times
  characters. At most ``MAX_LINES`` lines of each are aligned; past that the lines are compared
  in place, which is linear.
- The unified diff is cut to ``MAX_DIFF_BYTES`` (64 KB, the column's documented limit).
"""

from __future__ import annotations

import difflib
import hashlib

from regwatch.capture.safe_fetch.policy import FetchRefusedError, parse_target

MAX_LINES = 5000
MAX_DIFF_BYTES = 64 * 1024
MAX_PAIR = 2000  # characters of one changed line compared character by character
DEFAULT_PORTS = {"http": 80, "https": 443}


def canonical_url(url: str) -> str | None:
    """The canonical form, or None for an address SafeFetcher would not take."""
    if url.startswith("urn:sha256:") and len(url) == 75:
        return url
    try:
        target = parse_target(url)
    except FetchRefusedError:
        return None
    port = "" if DEFAULT_PORTS.get(target.scheme) == target.port else f":{target.port}"
    return f"{target.scheme}://{target.host}{port}{target.path}"


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _chars(a: str, b: str) -> int:
    """Characters that differ between two lines."""
    if a == b:
        return 0
    if len(a) > MAX_PAIR or len(b) > MAX_PAIR:  # a long line: counted as all different
        return max(len(a), len(b))
    same = sum(block.size for block in difflib.SequenceMatcher(None, a, b, autojunk=False)
               .get_matching_blocks())  # fmt: skip
    return max(len(a), len(b)) - same


def changed_pct(old: str, new: str) -> float:
    """Differing characters over the longer text, as a percentage rounded to two places."""
    longest = max(len(old), len(new))
    if longest == 0 or old == new:
        return 0.0
    a, b = old.split("\n"), new.split("\n")
    head_a, tail_a = a[:MAX_LINES], a[MAX_LINES:]
    head_b, tail_b = b[:MAX_LINES], b[MAX_LINES:]
    differing = 0
    matcher = difflib.SequenceMatcher(None, head_a, head_b, autojunk=True)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        left, right = head_a[i1:i2], head_b[j1:j2]
        for k in range(max(len(left), len(right))):
            differing += _chars(
                left[k] if k < len(left) else "", right[k] if k < len(right) else ""
            )
    # Past MAX_LINES, lines are compared in place: linear, exact for edits and appends,
    # an over-count only when lines were also inserted or removed that far down.
    for k in range(max(len(tail_a), len(tail_b))):
        differing += _chars(tail_a[k] if k < len(tail_a) else "",
                            tail_b[k] if k < len(tail_b) else "")  # fmt: skip
    return round(min(100.0, 100.0 * differing / longest), 2)


def unified_diff(old: str, new: str) -> str:
    """The line diff between two versions, cut at ``MAX_DIFF_BYTES``."""
    lines = difflib.unified_diff(old.split("\n")[:MAX_LINES], new.split("\n")[:MAX_LINES],
                                 "previous", "current", lineterm="")  # fmt: skip
    out: list[str] = []
    size = 0
    for line in lines:
        size += len(line.encode()) + 1
        if size > MAX_DIFF_BYTES:
            out.append("... (diff cut at 64 KB)")
            break
        out.append(line)
    return "\n".join(out)
