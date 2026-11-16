"""AttributeValidator without a database (M2 acceptance 4; test plan: each value type, and a
property test that random documents never crash it)."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from regwatch.core.errors import ProblemError
from regwatch.taxonomy.validator import AttributeValidator, FacetRule

FACETS = [
    FacetRule("topic", "term", multi=True, required=True,
              terms=frozenset({"privacy", "cybersecurity"})),
    FacetRule("regulation_type", "term", multi=False, required=False,
              terms=frozenset({"law", "guidance"})),
    FacetRule("notes", "text", multi=False, required=False),
    FacetRule("fine_eur", "number", multi=False, required=False),
    FacetRule("deadline", "date", multi=False, required=False),
    FacetRule("binding", "boolean", multi=False, required=False),
]  # fmt: skip
VALIDATOR = AttributeValidator(FACETS, version=3)


def test_valid_document_is_normalised() -> None:
    out = VALIDATOR.validate({
        "topic": ["privacy", "cybersecurity", "privacy"], "regulation_type": "law",
        "notes": "  Line one\nline two ", "fine_eur": 2.5e6, "deadline": "2027-01-17",
        "binding": True,
    })  # fmt: skip
    assert out.values["topic"] == ["cybersecurity", "privacy"]
    assert out.values["notes"] == "Line one\nline two" and out.values["deadline"] == "2027-01-17"


def _fields(doc: Any, **kw: Any) -> dict[str, str]:  # noqa: ANN401
    with pytest.raises(ProblemError) as exc:
        VALIDATOR.validate(doc, **kw)
    assert exc.value.status == 422
    return {e.field: e.message for e in exc.value.errors or []}


def test_unknown_key_and_non_term_value_name_the_field() -> None:
    """M2 acceptance 4."""
    errors = _fields({"enforcement": "x", "topic": ["not-a-term"]})
    assert set(errors) == {"attributes.enforcement", "attributes.topic"}
    assert errors["attributes.enforcement"] == "unknown facet"
    assert "not an active term" in errors["attributes.topic"]


@pytest.mark.parametrize(
    ("doc", "field"),
    [({"regulation_type": ["law"]}, "regulation_type"), ({"topic": []}, "topic"),
     ({"topic": ["privacy"] * 51}, "topic"), ({"notes": "x" * 2001}, "notes"),
     ({"notes": "bell\x07"}, "notes"), ({"notes": 5}, "notes"),
     ({"fine_eur": True}, "fine_eur"), ({"fine_eur": float("inf")}, "fine_eur"),
     ({"fine_eur": "5"}, "fine_eur"), ({"fine_eur": 10**30}, "fine_eur"),
     ({"deadline": "2027-02-30"}, "deadline"), ({"deadline": "20270117"}, "deadline"),
     ({"deadline": "2027-W03-1"}, "deadline"), ({"binding": "yes"}, "binding")],
)  # fmt: skip
def test_bad_values(doc: dict[str, Any], field: str) -> None:
    assert list(_fields(doc)) == [f"attributes.{field}"]


def test_required_facets_and_non_objects() -> None:
    assert _fields({}, require_all=True) == {"attributes.topic": "required"}
    assert VALIDATOR.validate({}).values == {}
    assert _fields(["topic"]) == {"attributes": "must be an object"}


JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=30),
    lambda children: (
        st.lists(children, max_size=5) | st.dictionaries(st.text(max_size=10), children, max_size=5)
    ),
    max_leaves=20,
)
RULES = st.lists(
    st.builds(FacetRule, key=st.text(min_size=1, max_size=8),
              value_type=st.sampled_from(["term", "text", "number", "date", "boolean"]),
              multi=st.booleans(), required=st.booleans(),
              terms=st.frozensets(st.text(max_size=6), max_size=5)),
    max_size=6,
)  # fmt: skip


@settings(max_examples=300, deadline=None)
@given(rules=RULES, doc=st.dictionaries(st.text(max_size=8), JSON, max_size=6) | JSON,
       require_all=st.booleans())  # fmt: skip
def test_random_documents_never_crash(
    rules: list[FacetRule],
    doc: Any,
    require_all: bool,  # noqa: ANN401
) -> None:
    validator = AttributeValidator(rules)
    try:
        out = validator.validate(doc, require_all=require_all)
    except ProblemError as exc:
        assert exc.status == 422 and exc.errors
    else:
        assert set(out.values) <= {r.key for r in rules}


@pytest.mark.parametrize("text", ["a\ud800b", "a b", "a​b", "a﻿b"])
def test_invisible_and_unstorable_characters_are_refused(text: str) -> None:
    """Review finding 9: PostgreSQL cannot store lone surrogates; the others are invisible."""
    assert list(_fields({"notes": text})) == ["attributes.notes"]


def test_int64_bounds_and_bounded_errors() -> None:
    assert VALIDATOR.validate({"fine_eur": 2**63 - 1}).values["fine_eur"] == 2**63 - 1
    assert list(_fields({"fine_eur": 2**63})) == ["attributes.fine_eur"]
    errors = _fields({"k" * 1_000_000: 1})
    assert all(len(f) < 100 for f in errors)
    many = _fields({f"key{i}": 1 for i in range(80)})
    assert len(many) == 51 and many["attributes"] == "and 30 more"


@pytest.mark.parametrize("text", ["سلام‌دنیا‏", "مرحبا؜ بك", "שלום‎ עולם", "﻿leading BOM"])
def test_right_to_left_marks_and_a_leading_bom_are_accepted(text: str) -> None:
    """M2 re-verification N4: Persian, Arabic and Hebrew text carries these marks."""
    assert VALIDATOR.validate({"notes": text}).values["notes"] == text.removeprefix("﻿")


class _Facet:
    def __init__(self, fid: int, key: str, value_type: str) -> None:
        self.id, self.key, self.value_type, self.multi, self.required = (
            fid,
            key,
            value_type,
            True,
            False,
        )


class _Rows:
    def __init__(self, rows: list[tuple[int, str]]) -> None:
        self._rows = rows

    def tuples(self) -> _Rows:
        return self

    def all(self) -> list[tuple[int, str]]:
        return self._rows


class _Scalars:
    def __init__(self, items: list[_Facet]) -> None:
        self._items = items

    def all(self) -> list[_Facet]:
        return self._items


class _Db:
    """Stand-in for the session: two facets, active terms for one of them, a version."""

    def __init__(self, version: int) -> None:
        self.version = version
        self.loads = 0

    async def scalars(self, stmt: object) -> _Scalars:
        self.loads += 1
        return _Scalars([_Facet(1, "topic", "term"), _Facet(2, "notes", "text")])

    async def execute(self, stmt: object) -> _Rows:
        return _Rows([(1, "privacy"), (1, "ai")])

    async def scalar(self, stmt: object) -> int:
        return self.version


async def test_load_builds_rules_from_facets_and_active_terms() -> None:
    """PR 25 peer review: the 100% unit floor covers the database loader too (7.1)."""
    from regwatch.taxonomy import validator

    v = await validator.load(_Db(3), 3)  # type: ignore[arg-type]
    assert v.version == 3
    assert v.facets["topic"].terms == frozenset({"privacy", "ai"})
    assert v.facets["notes"].terms == frozenset()


async def test_get_validator_rebuilds_only_when_the_version_moves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from regwatch.taxonomy import validator

    monkeypatch.setattr(validator, "_cached", None)
    db = _Db(1)
    first = await validator.get_validator(db)  # type: ignore[arg-type]
    assert await validator.get_validator(db) is first and db.loads == 1  # type: ignore[arg-type]
    db.version = 2
    second = await validator.get_validator(db)  # type: ignore[arg-type]
    assert second is not first and second.version == 2 and db.loads == 2
