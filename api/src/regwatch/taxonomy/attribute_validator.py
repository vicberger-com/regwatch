"""Item attribute validation against the taxonomy (M2; called by M3, M4, M5 and M7).

``item.attributes`` maps facet keys to values (docs/contracts/schema.sql): term keys for a
``term`` facet, otherwise a string, a number, an ISO date (``YYYY-MM-DD``) or a boolean.
A ``multi`` facet holds a list (a single value is accepted and wrapped); other facets hold
one value. Term values match a term key or synonym after case and space folding and come
back as the canonical key; only active terms count. Attributes come from captured content,
so error messages name the field but never echo the value.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

MAX_TEXT = 10_000
MAX_INT = 2**53  # integers beyond this lose precision in JSON clients
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)

ValidatedAttributes = dict[str, Any]


def fold(text: str) -> str:
    """Normal form for term matching: case-folded, whitespace collapsed."""
    return " ".join(text.casefold().split())


@dataclass(frozen=True)
class FacetSpec:
    key: str
    value_type: str  # term | text | number | date | boolean
    multi: bool = True
    required: bool = False
    terms: Mapping[str, str] = field(default_factory=dict)  # folded key or synonym -> key

    @classmethod
    def with_terms(
        cls, key: str, value_type: str, terms: Mapping[str, list[str]], **flags: bool
    ) -> FacetSpec:
        """Build from ``{term_key: synonyms}``; a key wins over another term's synonym."""
        lookup = {fold(k): k for k in terms}
        for k, synonyms in terms.items():
            for s in synonyms:
                lookup.setdefault(fold(s), k)
        return cls(key, value_type, terms=lookup, **flags)


@dataclass(frozen=True)
class TaxonomySnapshot:
    version: int
    facets: Mapping[str, FacetSpec]


@dataclass(frozen=True)
class FieldError:
    field: str
    message: str


class AttributeValidationError(ValueError):
    def __init__(self, errors: list[FieldError]) -> None:
        super().__init__("; ".join(f"{e.field}: {e.message}" for e in errors))
        self.errors = errors


class _Invalid(Exception):  # noqa: N818 - internal control flow
    def __init__(self, field: str, message: str) -> None:
        self.error = FieldError(field, message)


class AttributeValidator:
    def __init__(self, snapshot: TaxonomySnapshot) -> None:
        self.snapshot = snapshot

    def validate(self, attributes: object, *, prefix: str = "attributes") -> ValidatedAttributes:
        """Return the canonical attributes or raise :class:`AttributeValidationError`."""
        if not isinstance(attributes, dict):
            raise AttributeValidationError([FieldError(prefix, "must be an object")])
        facets, errors, out = self.snapshot.facets, [], {}
        for key, value in attributes.items():
            spec = facets.get(key) if isinstance(key, str) else None
            where = f"{prefix}.{key}" if isinstance(key, str) else prefix
            if spec is None:
                errors.append(FieldError(where, "unknown attribute"))
                continue
            try:
                out[key] = _value(spec, value, where)
            except _Invalid as exc:
                errors.append(exc.error)
        errors += [
            FieldError(f"{prefix}.{s.key}", "is required")
            for s in facets.values()
            if s.required and s.key not in attributes
        ]
        if errors:
            raise AttributeValidationError(errors)
        return out


def _value(spec: FacetSpec, value: Any, where: str) -> Any:
    if not spec.multi:
        if isinstance(value, list):
            raise _Invalid(where, "takes a single value")
        return _scalar(spec, value, where)
    out: list[Any] = []
    for i, item in enumerate(value if isinstance(value, list) else [value]):
        canonical = _scalar(spec, item, f"{where}[{i}]")
        if canonical not in out:
            out.append(canonical)
    if spec.required and not out:
        raise _Invalid(where, "must not be empty")
    return out


def _scalar(spec: FacetSpec, value: Any, where: str) -> Any:
    kind = spec.value_type
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        raise _Invalid(where, "must be a boolean")
    if kind == "number":
        if isinstance(value, int) and not isinstance(value, bool) and abs(value) <= MAX_INT:
            return value
        if isinstance(value, float) and math.isfinite(value):
            return value
        raise _Invalid(where, "must be a finite number")
    if not isinstance(value, str):
        raise _Invalid(where, f"must be a {'term key' if kind == 'term' else 'string'}")
    if kind == "term":
        key = spec.terms.get(fold(value))
        if key is None:
            raise _Invalid(where, f"is not an active term of facet {spec.key}")
        return key
    if kind == "date":
        try:
            if _DATE.fullmatch(value):
                return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
        raise _Invalid(where, "must be a date (YYYY-MM-DD)")
    if "\x00" in value or len(value) > MAX_TEXT:
        raise _Invalid(where, f"must be text of at most {MAX_TEXT} characters without NUL")
    return value
