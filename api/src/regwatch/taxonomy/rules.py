"""Rule-based term matching (M2 "test against sample text"; reused by M4's RuleClassifier).

``match_rules`` is ``{keywords, regex, languages, min_hits, weight}`` (schema.sql). A term
matches when keyword and regex hits together reach ``min_hits``. Confidence starts at 0.6
for exactly ``min_hits`` hits (the default ``classification.min_confidence``), rises by 0.1 per
further hit up to 1.0, and is scaled by ``weight``.

Captured text is hostile and rule patterns are entered by administrators, so matching runs in
time linear in the text (M2 review finding 1, BL-74): regexes use RE2 (google-re2, BSD-3), which
does not backtrack, and keywords use a plain substring scan. Patterns are compiled with RE2 when
saved (``compile_pattern``), so syntax RE2 lacks (backreferences, lookaround) is refused there.

RE2's ``\\w``, ``\\d``, ``\\s`` and ``\\b`` are ASCII only: ``\\w+`` finds ``caf`` in ``café``,
and ``\\bcafé\\b`` never matches. The Unicode classes (``\\pL``) compile to more than the
``MAX_PROGRAM_SIZE`` budget, so words in other languages belong in ``keywords``, whose
boundaries use ``str.isalnum`` and know every script; a pattern can bound a word with whitespace and
punctuation instead, as in ``(?:^|\\s)café(?:$|[\\s.,;:!?])`` (PR 26 peer review; BL-85).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import islice
from typing import Any

import re2

MAX_HITS = 1000
# RE2 is linear in the text, but its per-character cost grows with the compiled program: a
# 1,000-state pattern such as x.{999}y costs about 6.5 µs per character once the DFA runs out
# of memory (M2 re-verification N1). Typical rule patterns compile to well under 100.
MAX_PROGRAM_SIZE = 1000
# Probes for patterns that can match zero characters somewhere in ordinary text, such as \b.
_ZERO_WIDTH_PROBES = ("", "a", "a b", "1", "é", "a.")
SNIPPET = 40  # characters either side of a hit in the evidence
MAX_EVIDENCE = 5
_WORDLESS = ((0x3040, 0x30FF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xAC00, 0xD7AF))


class PatternError(ValueError):
    """The pattern is not valid RE2 syntax or can match an empty string."""


@lru_cache(maxsize=128)  # each entry keeps its DFA cache, a few MB for large programs
def compile_pattern(pattern: str) -> Any:  # noqa: ANN401 - re2 has no type stubs
    try:
        compiled = re2.compile(pattern)
    except re2.error as exc:
        raise PatternError(
            f"not supported by RE2 (no backreferences or lookaround): {exc}"
        ) from exc
    if compiled.programsize > MAX_PROGRAM_SIZE:
        size = compiled.programsize
        raise PatternError(f"too complex ({size} RE2 states, at most {MAX_PROGRAM_SIZE}); "
                           "shorten counted repetitions such as {999}")  # fmt: skip
    for probe in _ZERO_WIDTH_PROBES:
        if any(m.end() == m.start() for m in compiled.finditer(probe)):
            raise PatternError("can match zero characters (for example \\b or a*), so it "
                               "would match almost every text")  # fmt: skip
    return compiled


@dataclass
class RuleResult:
    matched: bool
    confidence: float
    hits: int = 0
    evidence: list[str] = field(default_factory=list)


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _wordless(text: str) -> bool:
    return any(lo <= ord(c) <= hi for c in text for lo, hi in _WORDLESS)


def _keyword_spans(folded: str, needle: str, limit: int) -> list[tuple[int, int]]:
    """Occurrences of ``needle`` not inside a longer word, by a linear substring scan."""
    spans: list[tuple[int, int]] = []
    boundaries = not _wordless(needle)
    start = folded.find(needle)
    while start != -1 and len(spans) < limit:
        end = start + len(needle)
        if not boundaries or (
            (start == 0 or not folded[start - 1].isalnum())
            and (end == len(folded) or not folded[end].isalnum())
        ):
            spans.append((start, end))
        start = folded.find(needle, start + 1)
    return spans


def _snippet(text: str, start: int, end: int) -> str:
    left, right = max(0, start - SNIPPET), min(len(text), end + SNIPPET)
    body = " ".join(text[left:right].split())
    return ("…" if left else "") + body + ("…" if right < len(text) else "")


def evaluate(rules: dict[str, Any], text: str, language: str | None = None) -> RuleResult:
    languages = [lang.lower() for lang in rules.get("languages") or []]
    if languages and language and language.lower().split("-")[0] not in languages:
        return RuleResult(False, 0.0, evidence=[f"language {language!r} is not in {languages}"])
    folded = _fold(text)
    spans: list[tuple[int, int]] = []
    for keyword in rules.get("keywords") or []:
        needle = _fold(keyword).strip()
        if needle:
            spans += _keyword_spans(folded, needle, MAX_HITS - len(spans))
    for raw in rules.get("regex") or []:
        if len(spans) >= MAX_HITS:
            break
        pattern = compile_pattern(raw)
        spans += [m.span() for m in islice(pattern.finditer(text), MAX_HITS - len(spans))]
    hits = min(len(spans), MAX_HITS)
    min_hits = max(1, int(rules.get("min_hits", 1)))
    if hits < min_hits:
        return RuleResult(False, 0.0, hits)
    weight = float(rules.get("weight", 1.0))
    confidence = round(min(1.0, (0.6 + 0.1 * (hits - min_hits)) * weight), 3)
    # NFKC can change lengths; snippets are taken from the original only where it did not.
    source = text if len(folded) == len(text) else folded
    evidence = [_snippet(source, s, e) for s, e in sorted(spans)[:MAX_EVIDENCE]]
    return RuleResult(True, confidence, hits, evidence)
