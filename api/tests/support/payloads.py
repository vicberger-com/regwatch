"""Load the security payload files in ``tests/security/payloads/`` (issue #12, REQ-25).

Each file starts with a comment header (lines beginning with ``#``) that must contain an
``# encoding:`` line:

- ``raw``: every following non-blank line is one payload, used as written.
- ``escaped``: the same, after decoding ``\\n``, ``\\r``, ``\\t``, ``\\\\``, ``\\uXXXX`` and
  ``\\UXXXXXXXX``, so control, zero-width and bidi characters stay readable in the file.
- ``spec``: each line is ``name<TAB>length<TAB>pattern``; the payload is the escaped pattern
  repeated to exactly ``length`` characters. Large inputs are built at test time only.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

PAYLOAD_DIR = Path(__file__).resolve().parent.parent / "security" / "payloads"
CATEGORIES = ("xss", "prompt_injection", "csv_formula", "email_header")
_ESCAPE = re.compile(r"\\(U[0-9A-Fa-f]{8}|u[0-9A-Fa-f]{4}|[nrt\\])")
_SIMPLE = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\"}


def decode_escapes(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        token = m.group(1)
        if token[0] in "uU":
            return chr(int(token[1:], 16))
        return _SIMPLE[token]

    return _ESCAPE.sub(repl, text)


def _split(path: Path) -> tuple[str, list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header: list[str] = []
    while lines and lines[0].startswith("#"):
        header.append(lines.pop(0))
    encodings = [h.split(":", 1)[1].split()[0] for h in header if h.startswith("# encoding:")]
    if len(encodings) != 1:
        raise ValueError(f"{path.name}: header needs exactly one '# encoding:' line")
    return encodings[0], [line for line in lines if line.strip()]


@cache
def load(category: str) -> tuple[str, ...]:
    """Payloads of one category, in file order."""
    encoding, lines = _split(PAYLOAD_DIR / f"{category}.txt")
    if encoding == "raw":
        return tuple(lines)
    if encoding == "escaped":
        return tuple(decode_escapes(line) for line in lines)
    raise ValueError(f"{category}.txt: encoding {encoding!r} is not a payload list")


def oversized_specs() -> dict[str, tuple[int, str]]:
    """``name -> (length, decoded pattern)`` from ``oversized.txt``."""
    encoding, lines = _split(PAYLOAD_DIR / "oversized.txt")
    if encoding != "spec":
        raise ValueError("oversized.txt must use '# encoding: spec'")
    specs: dict[str, tuple[int, str]] = {}
    for line in lines:
        name, length, pattern = line.split("\t", 2)
        specs[name] = (int(length), decode_escapes(pattern))
    return specs


def oversized(name: str) -> str:
    """Build one oversized payload of exactly the specified length in characters."""
    length, pattern = oversized_specs()[name]
    return (pattern * (length // len(pattern) + 1))[:length]
