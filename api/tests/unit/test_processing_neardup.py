"""Fuzzy title near-duplicates (M4 dedupe order; property: symmetric)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from regwatch.processing.neardup import similar


def test_reworded_titles_match_and_different_ones_do_not() -> None:
    a = "BSI publishes new rules for operators of critical facilities"
    assert similar(a, "BSI publishes NEW rules for operators of critical facilities!") >= 92
    assert similar(a, "New rules for operators of critical facilities: BSI publishes") >= 92
    assert similar(a, "CNIL fines a retailer for cookie consent failures") < 92


@given(st.text(max_size=200), st.text(max_size=200))
def test_similarity_is_symmetric_and_bounded(a: str, b: str) -> None:
    assert similar(a, b) == similar(b, a)
    assert 0 <= similar(a, b) <= 100
