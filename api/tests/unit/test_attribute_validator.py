"""AttributeValidator: every value type, synonyms, required and multi rules, fuzzing (#34)."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from regwatch.taxonomy.attribute_validator import (
    MAX_INT,
    MAX_TEXT,
    AttributeValidationError,
    AttributeValidator,
    FacetSpec,
    TaxonomySnapshot,
    fold,
)

TOPIC = FacetSpec.with_terms(
    "topic", "term", {"privacy": ["Data  Privacy"], "ai": ["AI", "privacy"]}, required=True
)
FACETS = {
    f.key: f
    for f in (
        TOPIC,
        FacetSpec.with_terms("stage", "term", {"draft": []}, multi=False),
        FacetSpec("note", "text", multi=False),
        FacetSpec("fine", "number", multi=False),
        FacetSpec("due", "date", multi=False),
        FacetSpec("binding", "boolean", multi=False),
        FacetSpec("tags", "text"),
    )
}
V = AttributeValidator(TaxonomySnapshot(1, FACETS))


def errors(attributes: object) -> list[tuple[str, str]]:
    with pytest.raises(AttributeValidationError) as info:
        V.validate(attributes)
    return [(e.field, e.message) for e in info.value.errors]


def test_valid_document_comes_back_canonical() -> None:
    doc = {"topic": ["DATA privacy", "ai", "privacy"], "stage": "Draft", "note": "x",
           "fine": 2.5, "due": "2026-01-31", "binding": False, "tags": "one"}  # fmt: skip
    assert V.validate(doc) == {**doc, "topic": ["privacy", "ai"], "stage": "draft",
                               "tags": ["one"]}  # fmt: skip


def test_term_key_wins_over_another_terms_synonym() -> None:
    assert V.validate({"topic": "PRIVACY"}) == {"topic": ["privacy"]}
    assert fold("  Data\tPrivacy ") == "data privacy"
    assert V.validate({"topic": "ai", "fine": -MAX_INT})["fine"] == -MAX_INT


@pytest.mark.parametrize(
    ("attrs", "field", "message"),
    [
        ({"topic": "ai", "region": "x"}, "attributes.region", "unknown attribute"),
        ({"topic": "ai", 3: "x"}, "attributes", "unknown attribute"),
        ({"topic": "gdpr"}, "attributes.topic[0]", "is not an active term of facet topic"),
        ({"topic": 7}, "attributes.topic[0]", "must be a term key"),
        ({"topic": []}, "attributes.topic", "must not be empty"),
        ({"topic": "ai", "stage": ["draft"]}, "attributes.stage", "takes a single value"),
        ({"topic": "ai", "note": 1}, "attributes.note", "must be a string"),
        ({"topic": "ai", "note": "a\x00b"}, "attributes.note", "without NUL"),
        ({"topic": "ai", "note": "x" * (MAX_TEXT + 1)}, "attributes.note", "without NUL"),
        ({"topic": "ai", "fine": True}, "attributes.fine", "must be a finite number"),
        ({"topic": "ai", "fine": MAX_INT + 1}, "attributes.fine", "must be a finite number"),
        ({"topic": "ai", "fine": float("nan")}, "attributes.fine", "must be a finite number"),
        ({"topic": "ai", "fine": "3"}, "attributes.fine", "must be a finite number"),
        ({"topic": "ai", "due": "2026-02-30"}, "attributes.due", "must be a date (YYYY-MM-DD)"),
        ({"topic": "ai", "due": "20260101"}, "attributes.due", "must be a date (YYYY-MM-DD)"),
        ({"topic": "ai", "binding": "true"}, "attributes.binding", "must be a boolean"),
        ({"stage": "draft"}, "attributes.topic", "is required"),
    ],
)
def test_rejections_name_the_field(attrs: dict[Any, Any], field: str, message: str) -> None:
    [(got_field, got_message)] = errors(attrs)
    assert got_field == field and message in got_message


def test_every_error_is_reported_and_values_are_not_echoed() -> None:
    found = errors({"secret-value": 1, "fine": "secret-value"})
    assert [f for f, _ in found] == [
        "attributes.secret-value", "attributes.fine", "attributes.topic",
    ]  # fmt: skip
    assert not any("secret-value" in m for _, m in found)


def test_non_object_is_rejected() -> None:
    assert errors(["topic"]) == [("attributes", "must be an object")]
    with pytest.raises(AttributeValidationError, match="items.attributes: must be an object"):
        V.validate(None, prefix="items.attributes")


# --- property-based: random facet sets and random JSON documents never crash ------------

KEYS = st.text("abcdef_", min_size=2, max_size=4)
JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=12),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=4), inner),
    max_leaves=12,
)
TYPES = st.sampled_from(["term", "text", "number", "date", "boolean"])


@st.composite
def snapshots(draw: st.DrawFn) -> TaxonomySnapshot:
    specs = {}
    for key in draw(st.lists(KEYS, max_size=5, unique=True)):
        terms = draw(st.dictionaries(KEYS, st.lists(st.text(max_size=6), max_size=2), max_size=4))
        specs[key] = FacetSpec.with_terms(
            key, draw(TYPES), terms, multi=draw(st.booleans()), required=draw(st.booleans())
        )
    return TaxonomySnapshot(0, specs)


@given(snapshots(), st.dictionaries(KEYS | st.text(max_size=3), JSON, max_size=6) | JSON)
def test_validator_never_crashes_and_is_idempotent(snap: TaxonomySnapshot, doc: Any) -> None:
    validator = AttributeValidator(snap)
    try:
        out = validator.validate(doc)
    except AttributeValidationError as exc:
        assert exc.errors and all(e.field.startswith("attributes") for e in exc.errors)
        return
    assert set(out) <= set(snap.facets)
    assert validator.validate(out) == out
