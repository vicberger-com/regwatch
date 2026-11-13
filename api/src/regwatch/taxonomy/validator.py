"""``AttributeValidator``: checks ``item.attributes`` against the facets (M2; used by M3, M4,
M5 and M7).

``item.attributes`` is ``{facet_key: value}`` (schema.sql): a term facet holds term keys (a list
when the facet is ``multi``, else one key), and text, number, date and boolean facets hold one
value. Every problem is collected and raised as one 422 problem naming each field (M2
acceptance 4). A validator works on a snapshot of the taxonomy; :func:`get_validator` keeps one
per process and rebuilds it when ``taxonomy.version`` moves (M2 design notes).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.core.schemas import has_control
from regwatch.taxonomy.models import Facet, Term

MAX_TEXT = 2000
MAX_TERMS_PER_FACET = 50
MAX_ERRORS = 50
INT64 = (-(2**63), 2**63 - 1)


def _field(key: object) -> str:
    """A field name for the problem body, bounded: keys come from hostile documents."""
    text = key if isinstance(key, str) else repr(key)
    return "attributes." + (text if len(text) <= 64 else text[:61] + "...")


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$", re.ASCII)


@dataclass(frozen=True)
class FacetRule:
    key: str
    value_type: str
    multi: bool
    required: bool
    terms: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ValidatedAttributes:
    """Normalised attributes: term keys deduplicated and sorted, text trimmed."""

    values: dict[str, Any] = field(default_factory=dict)


class AttributeValidator:
    def __init__(self, facets: list[FacetRule], version: int = 0) -> None:
        self.facets = {f.key: f for f in facets}
        self.version = version

    def validate(self, attributes: Any, *, require_all: bool = False) -> ValidatedAttributes:  # noqa: ANN401 - any JSON
        """Return the normalised attributes, or raise a 422 problem listing every bad field.

        ``require_all`` also demands every facet flagged ``required``.
        """
        if not isinstance(attributes, dict):
            raise _problem([ProblemFieldError(field="attributes", message="must be an object")])
        errors: list[ProblemFieldError] = []
        out: dict[str, Any] = {}
        for key, value in attributes.items():
            rule = self.facets.get(key) if isinstance(key, str) else None
            if rule is None:
                errors.append(ProblemFieldError(field=_field(key), message="unknown facet"))
                continue
            try:
                out[key] = _check(rule, value)
            except ValueError as exc:
                errors.append(ProblemFieldError(field=_field(key), message=str(exc)[:200]))
        if require_all:
            for rule in self.facets.values():
                if rule.required and rule.key not in attributes:
                    errors.append(ProblemFieldError(field=f"attributes.{rule.key}",
                                                    message="required"))  # fmt: skip
        if errors:
            if len(errors) > MAX_ERRORS:
                more = len(errors) - MAX_ERRORS
                rest = ProblemFieldError(field="attributes", message=f"and {more} more")
                errors = [*errors[:MAX_ERRORS], rest]
            raise _problem(errors)
        return ValidatedAttributes(out)


def _problem(errors: list[ProblemFieldError]) -> ProblemError:
    return ProblemError(422, "validation", "The attributes failed validation.", errors=errors)


def _check(rule: FacetRule, value: Any) -> Any:  # noqa: ANN401 - any JSON
    match rule.value_type:
        case "term":
            keys = value if isinstance(value, list) else [value]
            if isinstance(value, list) and not rule.multi:
                raise ValueError("takes one term key, not a list")
            if not keys or len(keys) > MAX_TERMS_PER_FACET:
                raise ValueError(f"needs 1 to {MAX_TERMS_PER_FACET} term keys")
            unknown = [k for k in keys if not isinstance(k, str) or k not in rule.terms]
            if unknown:
                shown = [k[:40] if isinstance(k, str) else type(k).__name__ for k in unknown[:5]]
                raise ValueError(f"not an active term of {rule.key}: {shown!r}")
            return sorted(set(keys)) if rule.multi else keys[0]
        case "text":
            if isinstance(value, str):
                value = value.removeprefix("\ufeff")  # a leading byte-order mark (N4)
            if (
                not isinstance(value, str)
                or len(value) > MAX_TEXT
                or has_control(value, allow_newlines=True)
            ):
                raise ValueError(f"must be text of up to {MAX_TEXT} characters")
            return value.strip()
        case "number":
            # Ints are always finite; math.isfinite would overflow on very large ones.
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError("must be a finite number")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("must be a finite number")
            if isinstance(value, int) and not INT64[0] <= value <= INT64[1]:
                raise ValueError("must be a number within 64-bit range")
            return value
        case "date":
            # Exactly YYYY-MM-DD: fromisoformat alone also takes 20261113 and week dates.
            if not isinstance(value, str) or not _ISO_DATE.match(value):
                raise ValueError("must be a date as YYYY-MM-DD")
            try:
                return date.fromisoformat(value).isoformat()
            except ValueError as exc:
                raise ValueError("must be a date as YYYY-MM-DD") from exc
        case "boolean":
            if not isinstance(value, bool):
                raise ValueError("must be true or false")
            return value
    raise ValueError(f"facet type {rule.value_type!r} is not supported")  # pragma: no cover


async def load(db: AsyncSession, version: int) -> AttributeValidator:
    facets = (await db.scalars(select(Facet))).all()
    rows = await db.execute(select(Term.facet_id, Term.key).where(Term.active.is_(True)))
    terms: dict[Any, set[str]] = {}
    for facet_id, key in rows.tuples().all():
        terms.setdefault(facet_id, set()).add(key)
    rules = [FacetRule(f.key, f.value_type, f.multi, f.required, frozenset(terms.get(f.id, ())))
             for f in facets]  # fmt: skip
    return AttributeValidator(rules, version)


_cached: AttributeValidator | None = None


async def get_validator(db: AsyncSession) -> AttributeValidator:
    """The process's validator, rebuilt when ``taxonomy.version`` has moved."""
    global _cached
    from regwatch.taxonomy.services import current_version

    version = await current_version(db)
    if _cached is None or _cached.version != version:
        _cached = await load(db, version)
    return _cached
