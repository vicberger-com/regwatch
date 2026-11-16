"""Rule evaluation used by the rule test and M4 (M2 design notes; M4 acceptance 3)."""

from __future__ import annotations

from regwatch.taxonomy.rules import evaluate

RANSOMWARE = {"keywords": ["ransomware", "incident reporting"], "min_hits": 1, "weight": 1.0}


def test_keywords_match_whole_words_case_insensitively() -> None:
    hit = evaluate(RANSOMWARE, "New Incident Reporting duties after a RANSOMWARE attack.")
    assert hit.matched and hit.hits == 2 and hit.confidence == 0.7
    assert any("RANSOMWARE" in e for e in hit.evidence)
    miss = evaluate(RANSOMWARE, "Antiransomwareware vendors and data reporting rules.")
    assert not miss.matched and miss.confidence == 0.0


def test_min_hits_weight_and_cap() -> None:
    rules = {"keywords": ["ai"], "min_hits": 2, "weight": 0.5}
    assert not evaluate(rules, "AI only once").matched
    two = evaluate(rules, "AI and AI")
    assert two.matched and two.confidence == 0.3
    many = evaluate({"keywords": ["x"]}, " ".join(["x"] * 20))
    assert many.confidence == 1.0 and len(many.evidence) == 5


def test_regex_languages_and_cjk() -> None:
    rules = {"regex": [r"Art(icle|\.)\s*\d+"], "languages": ["en", "de"]}
    assert evaluate(rules, "See Article 23 and Art. 5", "en-GB").hits == 2
    skipped = evaluate(rules, "Article 23", "fr")
    assert not skipped.matched and "fr" in skipped.evidence[0]
    assert evaluate(rules, "Article 23").matched  # no language given
    japanese = evaluate(
        {"keywords": ["個人情報保護委員会"]}, "本日、個人情報保護委員会は指針を公表した。"
    )
    assert japanese.matched


def test_empty_rules_never_match() -> None:
    assert not evaluate({}, "anything").matched
    assert not evaluate({"keywords": ["  "]}, "anything").matched


def test_keyword_boundaries_with_unicode_and_hit_cap() -> None:
    from regwatch.taxonomy.rules import MAX_HITS

    assert evaluate({"keywords": ["café"]}, "Le café, un CAFÉ.").hits == 2
    assert not evaluate({"keywords": ["café"]}, "cafés").matched  # longer word
    capped = evaluate({"keywords": ["x"], "regex": ["y"]}, "x " * 5000 + "y" * 5000)
    assert capped.hits == MAX_HITS


def test_regex_hits_stop_at_the_cap_without_building_every_match() -> None:
    import time

    from regwatch.taxonomy.rules import MAX_HITS

    started = time.perf_counter()
    result = evaluate({"regex": ["a"]}, "a" * 10_000_000)  # 10 MB, the captured-body cap
    assert result.hits == MAX_HITS and time.perf_counter() - started < 2.0


def test_re2_word_classes_are_ascii_and_keywords_are_not() -> None:
    """PR 26 peer review: \\w and \\b are ASCII in RE2, and \\pL exceeds the program budget."""
    import pytest

    from regwatch.taxonomy.rules import PatternError, compile_pattern

    text = "Le café über alles"
    assert not evaluate({"regex": [r"\bcafé\b"]}, text).matched  # ASCII \b: no match
    with pytest.raises(PatternError, match="too complex"):
        compile_pattern(r"caf\pL")  # Unicode classes are over the budget
    assert evaluate({"regex": [r"(?:^|\s)café(?:$|[\s.,;:!?])"]}, text).matched
    assert evaluate({"keywords": ["café", "über"]}, text).hits == 2  # keywords know every script
