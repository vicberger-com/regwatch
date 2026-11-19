"""Effective-date extraction (M4 scope, owner decision 2026-11-19)."""

from __future__ import annotations

import time
from datetime import date

import pytest

from regwatch.processing.dates import effective_date


@pytest.mark.parametrize(
    ("text", "expected"),
    [("This Regulation shall enter into force on 1 January 2027.", date(2027, 1, 1)),
     ("This Regulation enters into force on 1 January 2027.", date(2027, 1, 1)),
     ("It shall apply from 17 October 2026, except Article 3.", date(2026, 10, 17)),
     ("The rule takes effect on March 5, 2027.", date(2027, 3, 5)),
     ("Effective date: 2027-04-01.", date(2027, 4, 1)),
     ("Das Gesetz tritt am 1. Januar 2027 in Kraft.", date(2027, 1, 1)),
     ("Diese Verordnung gilt ab 18.10.2026.", date(2026, 10, 18)),
     ("Le décret entre en vigueur le 1er juillet 2027.", date(2027, 7, 1)),
     ("La ley entrará en vigor el 1 de enero de 2027.", date(2027, 1, 1)),
     ("A lei entra em vigor em 1 de março de 2027.", date(2027, 3, 1)),
     ("本法は2027年4月1日から施行する。", date(2027, 4, 1)),
     ("Published on 1 January 2027. Consultation closes 3 March 2027.", None),
     ("enters into force on 31 February 2027", None), ("enters into force on 1 January 1066", None),
     ("enters into force" + " " * 100 + "1 January 2027", None)],
)  # fmt: skip
def test_effective_date(text: str, expected: date | None) -> None:
    assert effective_date("", text) == expected


def test_hostile_text_stays_linear() -> None:
    text = "enters into force " * 20_000 + "1 " * 50_000
    started = time.monotonic()
    effective_date("t", text)
    assert time.monotonic() - started < 2


@pytest.mark.parametrize(
    ("text", "expected"),
    [("This Regulation applies to providers. Done at Brussels, 12 March 2026.", None),
     ("guidance on effective incident handling on 3 April 2026", None),
     ("Der Eintritt ist am 01.02.2026 frei.", None), ("Zutritt ab 5. Mai 2026", None),
     ("It enters into force on 1 December 2026 and shall apply from 1 January 2027.",
      date(2027, 1, 1)),
     ("本法は2027年4月1日から施行する。It shall apply from 1 May 2027.", date(2027, 5, 1))],
)  # fmt: skip
def test_ordinary_words_are_not_triggers(text: str, expected: date | None) -> None:
    """Enrichment review N22."""
    assert effective_date("", text) == expected
