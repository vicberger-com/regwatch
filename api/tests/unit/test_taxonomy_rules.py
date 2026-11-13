"""Term input rules without a database (M2 test plan: synonyms, rules, hierarchy)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from regwatch.core.errors import ProblemError
from regwatch.taxonomy import services
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
    [{"regex": ["(a+)+"]}, {"regex": [r"(\w*)*x"]}, {"regex": ["(a|aa){2,}"]},
     {"regex": ["[unclosed"]}, {"min_hits": 0}, {"weight": 11}, {"weight": 0},
     {"keywords": ["k"] * 101}, {"languages": ["x" * 201]}],
)  # fmt: skip
def test_unsafe_or_invalid_rules_are_refused(rules: dict[str, Any]) -> None:
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
