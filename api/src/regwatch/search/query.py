"""``QueryCompiler`` (M5 interfaces): a validated ``Query`` to a SQLAlchemy ``Select`` of item
ids, reused by search, map activity, CSV export and later by M7 and M8.

- Every value reaches SQL as a bound parameter; nothing from the query is formatted into SQL.
- ``q`` is matched against ``item.search_vector`` (title weight A, summary weight B, the
  ``simple`` configuration) as an OR of its words, so items with more of the words rank first
  (acceptance 1); ``plainto_tsquery`` reads the words, so no tsquery syntax is accepted.
- Filters combine with AND; the values of one filter with OR. Term filters name a facet and
  term keys; a term a user marked ``incorrect`` never matches.
- The DSL's own limits (20 values a facet, 50 jurisdictions, page size 200) are in the schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Select,
    Text,
    and_,
    cast,
    exists,
    func,
    literal_column,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import TSQUERY

from regwatch.capture.models import Source
from regwatch.processing.models import ChangeEvent, Item, ItemJurisdiction, ItemTerm
from regwatch.search.schemas import DateRange, Query, QueryFilters
from regwatch.taxonomy.models import Facet, Jurisdiction, Term

CONFIG = "simple"
# UN M49 regions over the sub-regions jurisdictions carry (``taxonomy.services.M49_REGIONS``):
# filtering by Europe (150) means its four sub-regions (acceptance 2).
CONTINENTS = {
    "002": {"015", "202"}, "019": {"419", "021"}, "142": {"143", "030", "035", "034", "145"},
    "150": {"151", "154", "039", "155"}, "009": {"053", "054", "057", "061"},
}  # fmt: skip


def regions(codes: list[str]) -> set[str]:
    out: set[str] = set()
    for code in codes:
        out |= CONTINENTS.get(code, {code})
    return out


@dataclass(frozen=True)
class Compiled:
    ids: Select[Any]  # item ids, ordered, unpaged
    tsquery: ColumnElement[Any] | None


def tsquery(q: str) -> ColumnElement[Any]:
    """Any of the words of ``q``, as plain words (no operators)."""
    plain = func.plainto_tsquery(literal_column(f"'{CONFIG}'::regconfig"), q)  # a constant
    return func.replace(cast(plain, Text), " & ", " | ").cast(TSQUERY)


def _range(column: Any, span: DateRange | None) -> list[ColumnElement[bool]]:  # noqa: ANN401
    if span is None:
        return []
    out = []
    if span.from_ is not None:
        out.append(column >= span.from_)
    if span.to is not None:
        out.append(column <= span.to)
    return out


def conditions(filters: QueryFilters | None) -> list[ColumnElement[bool]]:
    """The WHERE conditions of ``filters`` on ``item``."""
    if filters is None:
        return []
    where: list[ColumnElement[bool]] = []
    if filters.jurisdictions:
        codes = [c.upper() for c in filters.jurisdictions]
        where.append(exists().where(
            ItemJurisdiction.item_id == Item.id,
            ItemJurisdiction.jurisdiction_id == Jurisdiction.id,
            Jurisdiction.code.in_(codes)))  # fmt: skip
    if filters.regions:
        where.append(exists().where(
            ItemJurisdiction.item_id == Item.id,
            ItemJurisdiction.jurisdiction_id == Jurisdiction.id,
            Jurisdiction.region_code.in_(regions(filters.regions))))  # fmt: skip
    for facet_key, keys in (filters.terms or {}).items():
        if keys:
            where.append(exists().where(
                ItemTerm.item_id == Item.id, ItemTerm.term_id == Term.id,
                Term.facet_id == Facet.id, Facet.key == facet_key, Term.key.in_(keys),
                or_(ItemTerm.feedback.is_(None), ItemTerm.feedback != "incorrect")))  # fmt: skip
    if filters.sources:
        where.append(Item.source_id.in_(filters.sources))
    if filters.status:
        where.append(Item.status.in_(filters.status))
    if filters.languages:
        where.append(Item.language.in_(filters.languages))
    if filters.needs_review is not None:
        where.append(Item.needs_review.is_(filters.needs_review))
    if filters.severity:
        where.append(exists().where(ChangeEvent.item_id == Item.id,
                                    ChangeEvent.severity.in_(filters.severity)))  # fmt: skip
    if filters.credibility:
        where.append(exists().where(Source.id == Item.source_id,
                                    Source.credibility.in_(filters.credibility)))  # fmt: skip
    where += _range(Item.published_at, filters.published)
    where += _range(Item.last_changed_at, filters.changed)
    return where


_ORDER: dict[str, tuple[Any, ...]] = {
    "last_changed_desc": (Item.last_changed_at.desc(), Item.id.desc()),
    "last_changed_asc": (Item.last_changed_at.asc(), Item.id.asc()),
    "published_desc": (Item.published_at.desc().nulls_last(), Item.id.desc()),
    "published_asc": (Item.published_at.asc().nulls_last(), Item.id.asc()),
    "title_asc": (Item.title.asc(), Item.id.asc()),
}


def compile_query(query: Query) -> Compiled:
    where = conditions(query.filters)
    words = (query.q or "").strip()
    found = tsquery(words) if words else None
    ids = select(Item.id)
    if found is not None:
        where.append(Item.search_vector.op("@@")(found))
    ids = ids.where(and_(*where)) if where else ids
    if query.sort == "relevance" and found is not None:
        rank = func.ts_rank_cd(Item.search_vector, found)
        ids = ids.order_by(rank.desc(), Item.last_changed_at.desc(), Item.id.desc())
    else:
        ids = ids.order_by(*_ORDER.get(query.sort, _ORDER["last_changed_desc"]))
    return Compiled(ids, found)
