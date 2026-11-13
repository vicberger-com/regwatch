"""Rule-based term matching (M2 "test against sample text"; reused by M4's RuleClassifier).

``match_rules`` is ``{keywords, regex, languages, min_hits, weight}`` (schema.sql). A term
matches when keyword and regex hits together reach ``min_hits``. Confidence starts at 0.6
for exactly ``min_hits`` hits (the default ``classification.min_confidence``), rises by 0.1 per
further hit up to 1.0, and is scaled by ``weight``. Patterns were checked when saved
(``services.check_match_rules``).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

MAX_HITS = 1000
SNIPPET = 40  # characters either side of a hit in the evidence
MAX_EVIDENCE = 5
# Scripts written without spaces between words: keywords match as plain substrings there.
_NO_WORD_BOUNDARIES = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")


@dataclass
class RuleResult:
    matched: bool
    confidence: float
    hits: int = 0
    evidence: list[str] = field(default_factory=list)


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


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
        if not needle:
            continue
        if _NO_WORD_BOUNDARIES.search(needle):
            pattern = re.escape(needle)
        else:
            pattern = rf"(?<!\w){re.escape(needle)}(?!\w)"
        spans += [m.span() for m in re.finditer(pattern, folded)][:MAX_HITS]
    for raw in rules.get("regex") or []:
        spans += [m.span() for m in re.finditer(raw, text)][:MAX_HITS]
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
