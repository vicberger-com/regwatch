"""``QueryCompiler`` (M5 interfaces): a validated ``Query`` to a SQLAlchemy ``Select`` of item
ids, reused by search, map activity, CSV export and later by M7 and M8.

- Every value reaches SQL as a bound parameter; nothing from the query is formatted into SQL.
- ``check`` holds the DSL to what the planner and the driver can take (search review findings
  1 and 3): at most ``MAX_FACETS`` facets, ``MAX_VALUES`` values in any list, a page window of
  ``MAX_WINDOW`` items, no lone surrogates; a 400 otherwise, never a 500.
- Term filters are resolved to term ids before compiling (``resolve_terms``), so a facet is one
  ``item_term.term_id IN (...)`` test, not a four-table join; an unknown facet is a 400.
- ``q`` (search review finding 8): plain words match any of them, items with more of the words
  first (acceptance 1), then by ``ts_rank_cd`` (finding 7: repeating one word never beats having
  two); a query with websearch syntax (quotes, a leading ``-``, ``or``) is read by
  ``websearch_to_tsquery``, so phrases and exclusions hold.
- ``severity`` means the item's events inside ``filters.changed`` when it is given (the
  contract's "in the query period", finding 9), else any event.
- Region Europe (150) includes the European supranational bodies (finding 10).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Integer,
    Select,
    Text,
    and_,
    case,
    cast,
    exists,
    func,
    literal_column,
    select,
    union,
)
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from regwatch.capture.models import Source
from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.processing.models import ChangeEvent, Item, ItemJurisdiction, ItemTerm
from regwatch.search.schemas import DateRange, Query, QueryFilters
from regwatch.taxonomy.models import Facet, Jurisdiction, Term

CONFIG = "simple"
MAX_FACETS = 10
MAX_VALUES = 50
MAX_WINDOW = 10_000  # page * page_size
MAX_WORDS = 20
RANK_CANDIDATES = 2_000
RANK_WORDS = 8  # words counted for ranking: each costs a stemmed test per candidate
# UN M49 regions over the sub-regions jurisdictions carry (``taxonomy.services.M49_REGIONS``):
# filtering by Europe (150) means its four sub-regions (acceptance 2).
CONTINENTS = {
    "002": {"015", "202"}, "019": {"419", "021"}, "142": {"143", "030", "035", "034", "145"},
    "150": {"151", "154", "039", "155"}, "009": {"053", "054", "057", "061"},
}  # fmt: skip
SUPRANATIONAL = {"150": {"EU", "COE"}}  # bodies a continent includes, though they carry no region
_WEBSEARCH = re.compile(r'"|(^|\s)-\w|\bor\b', re.IGNORECASE)
_REGCONFIG: ColumnElement[Any] = literal_column(f"'{CONFIG}'::regconfig")  # a constant, never input
# Stemmed matching per item language (Q1), on the stored ``search_vector_stemmed`` (CP-21).
STEMMED = {"en": "english", "de": "german", "fr": "french", "es": "spanish", "pt": "portuguese"}


def _query_for(config: str, q: str, words_only: bool = False,
               every_word: bool = False) -> ColumnElement[Any]:  # fmt: skip
    reg: ColumnElement[Any] = literal_column(f"'{config}'::regconfig")  # a constant, never input
    if _WEBSEARCH.search(q) and not words_only:
        return func.websearch_to_tsquery(reg, q)
    if every_word:
        return func.plainto_tsquery(reg, q)
    return func.replace(cast(func.plainto_tsquery(reg, q), Text), " & ", " | ").cast(TSQUERY)


def matches(q: str, found: ColumnElement[Any], words_only: bool = False) -> ColumnElement[bool]:
    """``search_vector_stemmed`` holds the simple lexemes and the item's own stems (CP-21), so
    one combined query (simple, or any language's stems) through one GIN index matches."""
    combined = found
    for config in STEMMED.values():
        combined = combined.op("||")(_query_for(config, q, words_only))
    return Item.search_vector_stemmed.op("@@")(combined)


def matches_all(q: str) -> ColumnElement[bool]:
    """Every word, as written or stemmed, in one configuration (a best-match candidate)."""
    combined = _query_for(CONFIG, q, every_word=True)
    for config in STEMMED.values():
        combined = combined.op("||")(_query_for(config, q, every_word=True))
    return Item.search_vector_stemmed.op("@@")(combined)


@dataclass(frozen=True)
class Compiled:
    ids: Select[Any]  # item ids, ordered, unpaged
    tsquery: ColumnElement[Any] | None
    # Every match, newest change first: what counts and facets read a bounded prefix of, so the
    # planner can walk the date index and stop (the 1M-item load test, acceptance 3).
    matches: Select[Any] | None = None
    ranked: bool = (
        False  # relevance: ``matches`` is the candidate set, at most twice RANK_CANDIDATES
    )


def _bad(field: str, message: str) -> ProblemError:
    return ProblemError(400, "invalid-query", message,
                        errors=[ProblemFieldError(field=field, message=message)])  # fmt: skip


def _strings(value: Any) -> list[str]:  # noqa: ANN401 - any part of the DSL
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (*_strings(k), *_strings(v))]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def check(query: Query) -> None:
    """400 for a query past the limits (findings 1, 3 and 14)."""
    if query.page * query.page_size > MAX_WINDOW:
        raise _bad("page", f"at most the first {MAX_WINDOW} results can be paged")
    filters = query.filters
    if filters is not None:
        if len(filters.terms or {}) > MAX_FACETS:
            raise _bad("filters.terms", f"at most {MAX_FACETS} facets")
        for field in ("languages", "status", "severity", "credibility"):
            if len(getattr(filters, field) or []) > MAX_VALUES:
                raise _bad(f"filters.{field}", f"at most {MAX_VALUES} values")
    dumped = query.model_dump(mode="python", exclude_unset=True)
    for value in _strings(dumped):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise _bad("filters", "text must be valid Unicode") from None


async def resolve_terms(
    db: AsyncSession, filters: QueryFilters | None
) -> dict[str, list[uuid.UUID]]:
    """Facet key to the ids of its named terms; an unknown facet is a 400."""
    wanted = {k: v for k, v in ((filters.terms or {}) if filters else {}).items() if v}
    if not wanted:
        return {}
    known = set((await db.scalars(select(Facet.key).where(Facet.key.in_(wanted)))).all())
    if unknown := sorted(set(wanted) - known):
        raise _bad("filters.terms", f"unknown facet {unknown[0][:60]!r}")
    out: dict[str, list[uuid.UUID]] = {k: [] for k in wanted}
    pairs = [(f, t) for f, keys in wanted.items() for t in keys]
    rows = await db.execute(
        select(Facet.key, Term.key, Term.id).join(Term, Term.facet_id == Facet.id)
        .where(Facet.key.in_(wanted), Term.key.in_({t for _, t in pairs})))  # fmt: skip
    for facet, key, term_id in rows.tuples().all():
        if key in wanted[facet]:
            out[facet].append(term_id)
    return out


def regions(codes: list[str]) -> set[str]:
    out: set[str] = set()
    for code in codes:
        out |= CONTINENTS.get(code, {code})
    return out


_MARKS = "\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f"
WORD = rf"[\w{_MARKS}]+"  # a word keeps its combining marks (re-verification 1, #11)


def words(q: str) -> list[str]:
    """The words ``q`` looks for, as written (case is matched later, ignoring it); in websearch
    syntax neither ``or`` nor an excluded ``-word`` is a word looked for (N3)."""
    if _WEBSEARCH.search(q):
        q = re.sub(r'(^|\s)-("[^"]*"|\S+)', " ", q)
        q = re.sub(r"\bor\b", " ", q, flags=re.IGNORECASE)
    seen: dict[str, str] = {}
    for word in re.findall(WORD, q):
        seen.setdefault(word.lower(), word)
    return list(seen.values())[:MAX_WORDS]


def tsquery(q: str) -> ColumnElement[Any]:
    """Websearch syntax when ``q`` uses it, else any of its words (no operators either way)."""
    if _WEBSEARCH.search(q):
        return func.websearch_to_tsquery(_REGCONFIG, q)
    plain = func.plainto_tsquery(_REGCONFIG, q)
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


def period(filters: QueryFilters | None) -> tuple[datetime | None, datetime | None]:
    span = filters.changed if filters is not None else None
    return (span.from_, span.to) if span is not None else (None, None)


def conditions(filters: QueryFilters | None,
               term_ids: dict[str, list[uuid.UUID]]) -> list[ColumnElement[bool]]:  # fmt: skip
    """The WHERE conditions of ``filters`` on ``item``."""
    if filters is None:
        return []
    # Each EXISTS has its own aliases and correlates to ``item`` only, so a caller that already
    # joins change_event or jurisdiction (map activity) gets the same meaning (slice 2 S4, S5).
    ij, jur, ev, it = (aliased(ItemJurisdiction), aliased(Jurisdiction), aliased(ChangeEvent),
                       aliased(ItemTerm))  # fmt: skip
    where: list[ColumnElement[bool]] = []
    if filters.jurisdictions:
        codes = [c.upper() for c in filters.jurisdictions]
        where.append(exists().correlate(Item).where(
            ij.item_id == Item.id,
            ij.jurisdiction_id == jur.id,
            jur.code.in_(codes)))  # fmt: skip
    if filters.regions:
        bodies = {b for r in filters.regions for b in SUPRANATIONAL.get(r, set())}
        where.append(exists().correlate(Item).where(
            ij.item_id == Item.id,
            ij.jurisdiction_id == jur.id,
            jur.region_code.in_(regions(filters.regions))
            | jur.code.in_(bodies)))  # fmt: skip
    for ids in term_ids.values():
        where.append(exists().correlate(Item).where(
            it.item_id == Item.id, it.term_id.in_(ids),
            it.feedback.is_distinct_from("incorrect")))  # fmt: skip
    if filters.sources:
        where.append(Item.source_id.in_(filters.sources))
    if filters.status:
        where.append(Item.status.in_(set(filters.status)))
    if filters.languages:
        where.append(Item.language.in_(set(filters.languages)))
    if filters.needs_review is not None:
        where.append(Item.needs_review.is_(filters.needs_review))
    if filters.severity:
        start, end = period(filters)
        within = [ev.occurred_at >= start] if start else []
        within += [ev.occurred_at <= end] if end else []
        levels = ev.severity.in_(set(filters.severity))
        where.append(exists().correlate(Item).where(ev.item_id == Item.id, levels, *within))
    if filters.credibility:
        where.append(exists().correlate(Item).where(Source.id == Item.source_id,
                                    Source.credibility.in_(set(filters.credibility))))  # fmt: skip
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


def compile_query(query: Query, term_ids: dict[str, list[uuid.UUID]] | None = None) -> Compiled:
    where = conditions(query.filters, term_ids or {})
    text = (query.q or "").strip()
    found = tsquery(text) if text else None
    ids = select(Item.id)
    if found is not None:
        where.append(matches(text, found))
    ids = ids.where(and_(*where)) if where else ids
    newest = ids.order_by(Item.last_changed_at.desc(), Item.id.desc())
    if query.sort == "relevance" and found is not None:
        # Ranking costs per row, so only the ``RANK_CANDIDATES`` most recently changed matches
        # are ranked (re-verification 1, N1; the 1M-item load test).
        # Candidates: the newest matches with every word, and the newest with any (re-verification
        # R1: an old item with every word is still found); relevance pages only through them.
        best = ids.where(matches_all(text)).order_by(Item.last_changed_at.desc(), Item.id.desc())
        candidates = union(newest.limit(RANK_CANDIDATES),
                           best.limit(RANK_CANDIDATES)).subquery()  # fmt: skip
        # A word counts when it matches as written or by its stem in the item's language.
        matched = sum((case((matches(w, func.plainto_tsquery(_REGCONFIG, w), True), 1), else_=0)
                       for w in words(text)[:RANK_WORDS]),
                      start=cast(literal_column("0"), Integer))  # fmt: skip
        rank = func.ts_rank_cd(Item.search_vector, found)
        ids = (select(Item.id).where(Item.id.in_(select(candidates.c.id)))
               .order_by(matched.desc(), rank.desc(), Item.last_changed_at.desc(),
                         Item.id.desc()))  # fmt: skip
    else:
        ids = ids.order_by(*_ORDER.get(query.sort, _ORDER["last_changed_desc"]))
    if query.sort == "relevance" and found is not None:
        return Compiled(ids, found, select(candidates.c.id), ranked=True)
    return Compiled(ids, found, newest)
