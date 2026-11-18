"""Fuzzy title near-duplicates (M4 dedupe order; property: symmetric)."""

from __future__ import annotations

import pytest
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


def test_a_short_or_catch_all_title_never_matches_what_contains_it() -> None:
    """Pipeline re-verification 6, N9 (R17): containment is not similarity."""
    real = "Commission Implementing Regulation (EU) 2026/1234 of 12 November 2026"
    assert similar("Regulation (EU) 2026", real) == 0  # too short, and too different in length
    assert similar("incident reporting", "Guidance on incident reporting for operators") == 0
    catch_all = " ".join(["regulation", "guidance", "incident", "reporting", "operators",
                          "commission", "data", "protection", "rules", "new"] * 3)  # fmt: skip
    assert similar(catch_all, "New rules on incident reporting for operators") < 80


@pytest.mark.parametrize(("value", "ok"), [(0, False), (79, False), (80, True), (92, True),
                                           (100, True), (101, False)])  # fmt: skip
def test_the_ratio_setting_is_bounded(value: int, ok: bool) -> None:
    """N11: at 0 every item sharing a jurisdiction would be silenced."""
    from regwatch.admin.services import check_value
    from regwatch.core import registry
    from regwatch.core.errors import ProblemError

    defn = registry.settings()["processing.near_duplicate_ratio"]
    if ok:
        assert check_value(defn, value) == value
    else:
        with pytest.raises(ProblemError):
            check_value(defn, value)
