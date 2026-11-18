"""Canonical URLs, the change share and diffs (M4 design notes)."""

from __future__ import annotations

import time

import pytest
from hypothesis import given
from hypothesis import strategies as st

from regwatch.processing import versioning as v


@pytest.mark.parametrize(
    ("url", "canonical"),
    [("HTTPS://Reg.Example:443/a?b=1#frag", "https://reg.example/a?b=1"),
     ("http://reg.example:80/", "http://reg.example/"), ("https://reg.example:8443/x", "https://reg.example:8443/x"),
     ("urn:sha256:" + "a" * 64, "urn:sha256:" + "a" * 64), ("javascript:alert(1)", None),
     ("urn:sha256:short", None), ("urn:sha256:<script>" + "a" * 56, None),
     ("http://[2001:db8::1]:8080/a", "http://[2001:db8::1]:8080/a"),
     ("http://[2001:db8::1:8080]/a", "http://[2001:db8::1:8080]/a")],
)  # fmt: skip
def test_canonical_urls(url: str, canonical: str | None) -> None:
    assert v.canonical_url(url) == canonical


@pytest.mark.parametrize(
    ("old", "new", "pct"),
    [("", "", 0.0), ("abc", "abc", 0.0), ("abcd", "abcx", 25.0), ("", "new", 100.0),
     ("line one\nline two", "line one\nline 2wo", 5.88),  # 1 of 17 characters
     ("Status: In force\n" + "x" * 80, "Status: Repealed\n" + "x" * 80, 7.22)],
)  # fmt: skip
def test_changed_share_counts_characters(old: str, new: str, pct: float) -> None:
    assert v.changed_pct(old, new) == pct


def test_a_long_text_stays_fast() -> None:
    """Lines times lines, never characters times characters."""
    old = "\n".join(f"line {n} of the act, with some words" for n in range(20_000))
    # 1,000 lines changed in the aligned part and 1,000 past it: about 10 percent.
    words = "of the act, with some words"
    new = "\n".join(f"LINE {n} {words}" if n % 20 == 0 else f"line {n} {words}"
                    for n in range(20_000))  # fmt: skip
    started = time.monotonic()
    pct = v.changed_pct(old, new)
    assert 0 < pct < 15 and time.monotonic() - started < 10
    huge = "y" * 5000
    # One long line past MAX_PAIR: only what lies between the common ends counts (N2).
    assert v.changed_pct(huge, huge + "z") == pytest.approx(0.02, abs=0.01)
    assert v.changed_pct(huge, "z" * 5000) == 100.0


def test_the_diff_is_unified_and_cut_at_64_kb() -> None:
    diff = v.unified_diff("a\nb\nc", "a\nB\nc")
    assert "-b" in diff and "+B" in diff and diff.startswith("--- previous")
    big = v.unified_diff("", "\n".join("x" * 100 for _ in range(2000)))
    assert len(big.encode()) <= v.MAX_DIFF_BYTES + 40 and big.endswith("(diff cut at 64 KB)")


@given(st.text(max_size=300), st.text(max_size=300))
def test_the_share_is_bounded_and_zero_only_when_equal(old: str, new: str) -> None:
    pct = v.changed_pct(old, new)
    assert 0.0 <= pct <= 100.0
    if old == new:
        assert pct == 0.0


def test_hashes_are_sha256_hex() -> None:
    assert v.sha256("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert v._chars("same", "same", [0]) == 0


@pytest.mark.parametrize(
    ("old", "new"),
    [("ab" * 1000, "ba" * 1000),
     ("\n".join("x" * 2000 + str(n) for n in range(499)),
      "\n".join("y" * 2000 + str(n) for n in range(499))),
     ("\n".join("a b " * 120 + str(n) for n in range(2000)),
      "\n".join("b a " * 120 + str(n) for n in range(2000)))],
)  # fmt: skip
def test_hostile_texts_cost_a_bounded_time(old: str, new: str) -> None:
    """M4 pipeline review finding 2: these took 141 s and 303 s before the budget."""
    started = time.monotonic()
    assert v.changed_pct(old, new) > 90
    assert time.monotonic() - started < 2


def test_small_edits_on_every_line_stay_small_past_the_budget() -> None:
    """Re-verification N2: renumbered articles, one character on each of 5,000 lines."""
    old = "\n".join(f"Article {n % 10} " + "x" * 90 for n in range(5000))
    new = "\n".join(f"Article {(n + 1) % 10} " + "x" * 90 for n in range(5000))
    assert v.changed_pct(old, new) < 2.0
