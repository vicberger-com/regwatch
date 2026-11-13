"""Term input rules without a database (M2 test plan: synonyms, rules, hierarchy)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from regwatch.core.errors import ProblemError
from regwatch.taxonomy import rules, services
from regwatch.taxonomy.models import Term


def test_synonyms_are_normalised() -> None:
    raw = [" Data  Protection ", "data protection", "", "Café", "Café", "GDPR"]
    assert services.normalise_synonyms(raw) == ["Data Protection", "Café", "GDPR"]


@pytest.mark.parametrize("raw", [["x" * 201], ["a\x1bb"], [f"s{i}" for i in range(51)]])
def test_bad_synonyms_are_refused(raw: list[str]) -> None:
    with pytest.raises(ProblemError):
        services.normalise_synonyms(raw)


@pytest.mark.parametrize(
    "rules",
    [{"regex": ["[unclosed"]}, {"regex": [r"(?<!x)a"]}, {"regex": [r"(a)\1"]},
     {"regex": [""]}, {"regex": ["a*"]}, {"regex": ["(x|)"]},
     {"min_hits": 0}, {"weight": 11}, {"weight": 0},
     {"keywords": ["k"] * 101}, {"languages": ["x" * 201]}],
)  # fmt: skip
def test_invalid_rules_are_refused(rules: dict[str, Any]) -> None:
    with pytest.raises(ProblemError) as exc:
        services.check_match_rules(rules)
    assert exc.value.status == 422


@pytest.mark.parametrize(
    "rules",
    [{}, {"regex": [r"\bAI Act\b", r"(?i)art(icle)?\s+\d+", "(ab)+c"]},
     {"keywords": ["NIS2"], "languages": ["de", "en"], "min_hits": 2, "weight": 0.5}],
)  # fmt: skip
def test_ordinary_rules_pass(rules: dict[str, Any]) -> None:
    assert services.check_match_rules(rules) == rules


def _term(key: str, parent: uuid.UUID | None = None) -> Term:
    return Term(id=uuid.uuid4(), facet_id=uuid.uuid4(), key=key, label=key.upper(),
                parent_id=parent, synonyms=[], match_rules={}, active=True)  # fmt: skip


def test_tree_nests_children_and_promotes_orphans() -> None:
    root = _term("root")
    child = _term("child", root.id)
    orphan = _term("orphan", uuid.uuid4())  # parent inactive or filtered out
    tree = services.term_tree([root, child, orphan], "topic")
    assert [t.key for t in tree] == ["root", "orphan"]
    assert [c.key for c in tree[0].children] == ["child"]
    assert tree[0].facet_key == "topic"


@pytest.mark.parametrize(
    ("pattern", "text"),
    [("((a+))+$", "a" * 50_000 + "b"), (r"\d+\s*EUR", "1" * 50_000),
     (r"\w*\w*\w*z", "a" * 50_000), ("(a|aa){2,}$", "a" * 50_000 + "b")],
)  # fmt: skip
def test_backtracking_shapes_run_in_linear_time(pattern: str, text: str) -> None:
    """Review finding 1: patterns that froze Python re for seconds or minutes run at once."""
    import time

    services.check_match_rules({"regex": [pattern]})  # accepted: RE2 cannot backtrack
    started = time.perf_counter()
    rules.evaluate({"regex": [pattern]}, text)
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize("pattern", [r"x.{999}y", r"\pL{300}z", r"\b", r"a*\b", r"(?m)$"])
def test_costly_or_zero_width_patterns_are_refused(pattern: str) -> None:
    """M2 re-verification N1 and the finding 10 residual."""
    with pytest.raises(ProblemError):
        services.check_match_rules({"regex": [pattern]})


@pytest.mark.parametrize("pattern", [r"\bAI Act\b", r"(?i)art(icle)?\s+\d+", r"\d+\s*EUR"])
def test_realistic_patterns_still_pass(pattern: str) -> None:
    assert services.check_match_rules({"regex": [pattern]})


def test_rule_strings_refuse_lone_surrogates() -> None:
    """M2 re-verification N3."""
    for field in ("keywords", "regex", "languages"):
        with pytest.raises(ProblemError):
            services.check_match_rules({field: ["a\ud800"]})
