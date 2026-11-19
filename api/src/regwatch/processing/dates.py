"""Effective-date extraction from text patterns (M4 scope; owner decision 2026-11-19: stored in
``item.attributes["effective_date"]``, a seeded system facet of value type date; ASSUMPTIONS:
no dateparser, the project's own month tables for the rule languages).

A date counts only right after a phrase that says the text applies from it ("enters into force
on", "shall apply from", "tritt am ... in Kraft", "entre en vigueur le", "entrará en vigor el",
"entra em vigor em", "から施行"), within ``WINDOW`` characters; the first such date in the
title and the first ``SCAN_CHARS`` characters wins. Dates between 1990 and 2100 only. The
patterns are fixed, linear (no nested repetition) and built once.
"""

from __future__ import annotations

import re
from datetime import date

SCAN_CHARS = 20_000
WINDOW = 60
MONTHS = {
    **dict.fromkeys(["january", "januar", "jänner", "janvier", "enero", "janeiro"], 1),
    **dict.fromkeys(["february", "februar", "février", "fevrier", "febrero", "fevereiro"], 2),
    **dict.fromkeys(["march", "märz", "maerz", "mars", "marzo", "março", "marco"], 3),
    **dict.fromkeys(["april", "avril", "abril"], 4),
    **dict.fromkeys(["may", "mai", "mayo", "maio"], 5),
    **dict.fromkeys(["june", "juni", "juin", "junio", "junho"], 6),
    **dict.fromkeys(["july", "juli", "juillet", "julio", "julho"], 7),
    **dict.fromkeys(["august", "août", "aout", "agosto"], 8),
    **dict.fromkeys(["september", "septembre", "septiembre", "setiembre", "setembro"], 9),
    **dict.fromkeys(["october", "oktober", "octobre", "octubre", "outubro"], 10),
    **dict.fromkeys(["november", "novembre", "noviembre", "novembro"], 11),
    **dict.fromkeys(["december", "dezember", "décembre", "decembre", "diciembre", "dezembro"],
                    12),
}  # fmt: skip
_TRIGGER = re.compile(
    r"(enters? into force|entered into force|entry into force|shall apply|applies|apply from"
    r"|with effect from|effective (?:from|on|as of)?|takes? effect"
    r"|tritt|in kraft|gilt ab|anzuwenden ab|wirksam ab"
    r"|entre(?:ra)? en vigueur|s'applique|applicable à partir"
    r"|entrar[áa] en vigor|entra en vigor|será aplicable|aplicar[áa] a partir"
    r"|entra(?:rá)? em vigor|aplica-se a partir)",
    re.IGNORECASE,
)
_MONTH = "|".join(sorted(map(re.escape, MONTHS), key=len, reverse=True))
_DATES = [
    (re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"), ("y", "m", "d")),
    (re.compile(rf"(\d{{1,2}})(?:er|\.|º|°)?\s+(?:de\s+)?({_MONTH})\s+(?:de\s+)?(\d{{4}})",
                re.IGNORECASE), ("d", "M", "y")),
    (re.compile(rf"({_MONTH})\s+(\d{{1,2}}),?\s+(\d{{4}})", re.IGNORECASE), ("M", "d", "y")),
    (re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})"), ("d", "m", "y")),
    (re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日"), ("y", "m", "d")),
]  # fmt: skip
_JA = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:から|より)施行")


def _read(match: re.Match[str], order: tuple[str, ...]) -> date | None:
    parts = dict(zip(order, match.groups(), strict=True))
    month = MONTHS.get(parts["M"].lower()) if "M" in parts else int(parts["m"])
    try:
        found = date(int(parts["y"]), month or 0, int(parts["d"]))
    except ValueError:
        return None
    return found if 1990 <= found.year <= 2100 else None


def _after(text: str, start: int) -> date | None:
    window = text[start : start + WINDOW]
    best: tuple[int, date] | None = None
    for pattern, order in _DATES:
        match = pattern.search(window)
        if match and (got := _read(match, order)) and (best is None or match.start() < best[0]):
            best = (match.start(), got)
    return best[1] if best else None


def effective_date(title: str, text: str) -> date | None:
    """The date the document says it applies from, or None."""
    scan = f"{title}\n{text[:SCAN_CHARS]}"
    if ja := _JA.search(scan):
        return _read(ja, ("y", "m", "d"))
    for trigger in _TRIGGER.finditer(scan):
        if got := _after(scan, trigger.end()):
            return got
    return None
