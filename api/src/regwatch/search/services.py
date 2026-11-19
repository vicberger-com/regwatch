"""Service layer; other modules call this module only through here (ADR-0001).

``POST /search`` (M5 acceptance 1): the compiled query, counted and paged, each item with its
jurisdictions, its terms (no ``incorrect`` ones), its highest severity and its source.

Highlights are built here, not by ``ts_headline``: the field is HTML-escaped first and only
then are the query's words wrapped in ``<mark>``, so a highlight holds no markup from the
captured (hostile) text, only ``<mark>`` and ``</mark>`` around escaped words.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import re
import time
import unicodedata
import uuid
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import func, literal, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture.models import Source
from regwatch.core.errors import ProblemError
from regwatch.core.settings import get_settings
from regwatch.identity.services import SlidingWindow
from regwatch.processing.models import ChangeEvent, Item, ItemJurisdiction, ItemTerm
from regwatch.processing.schemas import ItemJurisdiction as PlaceOut
from regwatch.processing.schemas import ItemSummary, TermAssignment
from regwatch.search import index, indexed
from regwatch.search.query import WORD, check, compile_query, period, resolve_terms
from regwatch.search.query import words as query_words
from regwatch.search.schemas import FacetCount, Query, SearchResult
from regwatch.taxonomy.models import Facet, Jurisdiction, Term

SEARCH_RATE = 60  # per user and minute (08 security 8.2)
STATEMENT_TIMEOUT = "5s"
MAX_TOTAL = 10_000
FACET_VALUES = 50
FACET_SAMPLE = 2_000  # the most recently changed matches facet counts cover
FACET_TTL = 30.0
FACET_CACHE_KEYS = 1000
_facet_cache: dict[str, tuple[float, dict[str, list[FacetCount]]]] = {}
searches = SlidingWindow(60.0)
SNIPPET = 300
_RANK = {"info": 0, "notable": 1, "major": 2}
_log = structlog.get_logger(__name__)


def words(q: str) -> list[str]:
    return query_words(unicodedata.normalize("NFC", q))


def highlight(value: str | None, found: list[str], snippet: bool = False) -> list[str]:
    """``value`` escaped, its words of ``found`` in ``<mark>``; around the first match if
    ``snippet``. Empty if nothing matches."""
    if not value or not found:
        return []
    value = unicodedata.normalize("NFC", value)  # an accent stays with its letter (finding 11)
    edge = WORD.removesuffix("+")
    pattern = re.compile(rf"(?<!{edge})(" + "|".join(map(re.escape, found)) + rf")(?!{edge})",
                         re.IGNORECASE)  # fmt: skip
    first = pattern.search(value)
    if first is None:
        return []
    if snippet and len(value) > SNIPPET:
        start = max(0, first.start() - SNIPPET // 3)
        value = ("…" if start else "") + value[start : start + SNIPPET] + "…"
    out, last = [], 0
    for match in pattern.finditer(value):
        out.append(html.escape(value[last : match.start()]))
        out.append(f"<mark>{html.escape(match.group(0))}</mark>")
        last = match.end()
    out.append(html.escape(value[last:]))
    return ["".join(out)]


async def summaries(db: AsyncSession, ids: list[uuid.UUID], start: datetime | None = None,
                     end: datetime | None = None) -> dict[uuid.UUID, ItemSummary]:  # fmt: skip
    items = {i.id: i for i in (await db.scalars(select(Item).where(Item.id.in_(ids)))).all()}
    names = dict((await db.execute(select(Source.id, Source.name).where(
        Source.id.in_({i.source_id for i in items.values()})))).tuples().all())  # fmt: skip
    places: dict[uuid.UUID, list[PlaceOut]] = {i: [] for i in ids}
    for item_id, code, name, conf in (await db.execute(
            select(ItemJurisdiction.item_id, Jurisdiction.code, Jurisdiction.name,
                   ItemJurisdiction.confidence)
            .join(Jurisdiction, Jurisdiction.id == ItemJurisdiction.jurisdiction_id)
            .where(ItemJurisdiction.item_id.in_(ids))
            .order_by(Jurisdiction.code))).tuples():  # fmt: skip
        places[item_id].append(PlaceOut(code=code, name=name, confidence=float(conf)))
    terms: dict[uuid.UUID, list[TermAssignment]] = {i: [] for i in ids}
    for t, key, label, facet in (await db.execute(
            select(ItemTerm, Term.key, Term.label, Facet.key)
            .join(Term, Term.id == ItemTerm.term_id).join(Facet, Facet.id == Term.facet_id)
            .where(ItemTerm.item_id.in_(ids),
                   ItemTerm.feedback.is_distinct_from("incorrect"))
            .order_by(Facet.key, Term.key))).tuples():  # fmt: skip
        terms[t.item_id].append(TermAssignment(
            term_id=t.term_id, facet_key=facet, key=key, label=label,
            confidence=float(t.confidence), assigned_by=t.assigned_by,
            feedback=t.feedback))  # fmt: skip
    levels: dict[uuid.UUID, str] = {}
    for item_id, level in (await db.execute(
            select(ChangeEvent.item_id, ChangeEvent.severity).distinct()
            .where(ChangeEvent.item_id.in_(ids),
                   *([ChangeEvent.occurred_at >= start] if start else []),
                   *([ChangeEvent.occurred_at <= end] if end else [])))).tuples():  # fmt: skip
        if _RANK.get(level, -1) > _RANK.get(levels.get(item_id, ""), -1):
            levels[item_id] = level
    return {
        i.id: ItemSummary(
            id=i.id, title=i.title, title_en=i.title_en, summary=i.summary,
            summary_en=i.summary_en, canonical_url=i.canonical_url, source_id=i.source_id,
            source_name=names.get(i.source_id, ""), language=i.language,
            published_at=i.published_at, last_changed_at=i.last_changed_at, status=i.status,
            severity=levels.get(i.id), jurisdictions=places[i.id], terms=terms[i.id],
            attributes=i.attributes or {})
        for i in items.values()
    }  # fmt: skip


async def facet_counts(db: AsyncSession, ids: list[uuid.UUID],
                       query: Query) -> dict[str, list[FacetCount]]:  # fmt: skip
    """Per facet shown in the filters, and for jurisdictions: the matching items each value has
    (never an ``incorrect`` term), at most ``FACET_VALUES`` values a facet, most first; over the
    ``FACET_SAMPLE`` most recently changed matches; cached ``FACET_TTL`` seconds per query (M5
    design notes)."""
    key = query_hash(query.model_copy(update={"page": 1, "page_size": 1, "sort": "relevance",
                                              "highlight": False}))  # fmt: skip
    now = time.monotonic()
    if (hit := _facet_cache.get(key)) is not None and now - hit[0] < FACET_TTL:
        return hit[1]
    if not ids:
        return {}
    out: dict[str, list[FacetCount]] = {}
    # Driven from the ids (``unnest``) through each table's primary key: an ``IN`` list made the
    # planner scan by term and filter every tag (BL-118: 487 ms a facet query at 1M items).
    sample = (func.unnest(literal(ids, ARRAY(PG_UUID(as_uuid=True)))).table_valued("id")
              .render_derived(name="s"))  # fmt: skip
    # Counted per id straight from the list through each table's primary key, then labelled:
    # joining terms first made the planner loop terms times ids (BL-118: 1.2 s at 1M items).
    by_term = dict((await db.execute(
        select(ItemTerm.term_id, func.count()).select_from(sample)
        .join(ItemTerm, ItemTerm.item_id == sample.c.id)
        .where(ItemTerm.feedback.is_distinct_from("incorrect"))
        .group_by(ItemTerm.term_id))).tuples().all())  # fmt: skip
    if by_term:
        labels = await db.execute(
            select(Term.id, Facet.key, Term.key, Term.label).join(Facet, Facet.id == Term.facet_id)
            .where(Term.id.in_(list(by_term)), Facet.show_in_filters))  # fmt: skip
        for term_id, facet, term, label in labels.tuples().all():
            out.setdefault(facet, []).append(
                FacetCount(key=term, label=label, count=by_term[term_id]))  # fmt: skip
    by_place = dict((await db.execute(
        select(ItemJurisdiction.jurisdiction_id, func.count()).select_from(sample)
        .join(ItemJurisdiction, ItemJurisdiction.item_id == sample.c.id)
        .group_by(ItemJurisdiction.jurisdiction_id))).tuples().all())  # fmt: skip
    places = await db.execute(select(Jurisdiction.id, Jurisdiction.code, Jurisdiction.name)
                              .where(Jurisdiction.id.in_(list(by_place))))  # fmt: skip
    # The contract's name for it (slice 2 S11); a facet may not be called that.
    out["jurisdiction"] = [FacetCount(key=c, label=n, count=by_place[j])
                           for j, c, n in places.tuples().all()]  # fmt: skip
    for values_ in out.values():
        values_.sort(key=lambda f: (-f.count, f.key))
        del values_[FACET_VALUES:]
    if len(_facet_cache) >= FACET_CACHE_KEYS:
        _facet_cache.clear()
    _facet_cache[key] = (now, out)
    return out


def timed_out(exc: DBAPIError) -> bool:
    """The statement timeout (``query_canceled``)."""
    return getattr(exc.orig, "sqlstate", None) == "57014"


def busy() -> ProblemError:
    return ProblemError(503, "busy", "The search took too long; narrow it and try again.",
                        headers={"Retry-After": "5"})  # fmt: skip


def limited(user_id: uuid.UUID | None) -> None:
    key = str(user_id)
    if searches.count(key) >= SEARCH_RATE:
        raise ProblemError(429, "rate-limited", "Too many searches; try again shortly.",
                           headers={"Retry-After": str(searches.retry_after(key))})  # fmt: skip
    searches.hit(key)


def query_hash(query: Query) -> str:
    """Keyed, so a log reader cannot confirm a guessed query (finding 13); stable, so the facet
    cache can key on it."""
    key = get_settings().secret_key.get_secret_value().encode()
    body = query.model_dump_json(exclude_unset=True).encode()
    return hmac.new(key, body, hashlib.sha256).hexdigest()[:16]


async def search(db: AsyncSession, query: Query, user_id: uuid.UUID | None) -> SearchResult:
    """One search: at most ``SEARCH_RATE`` a minute per user (8.2), ``STATEMENT_TIMEOUT`` per
    statement (finding 1), an exact total up to ``MAX_TOTAL`` (finding 5)."""
    started = time.monotonic()
    check(query)
    limited(user_id)
    terms = await resolve_terms(db, query.filters)  # an unknown facet is a 400 on either path
    if index.configured():
        # No pooled connection waits on the index (review finding 1); nothing here is written.
        await db.commit()
    from_index = await _from_index(db, query)  # ADR-0011: the index when it is configured
    await db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))  # constant
    if from_index is not None:
        page_ids, total, facets = from_index
    else:
        page_ids, total, facets = await _from_postgresql(db, query, terms)
    start, end = period(query.filters)
    found = await summaries(db, page_ids, start, end) if page_ids else {}
    marks = words(query.q or "") if query.highlight else []
    items = []
    for item_id in page_ids:
        summary = found.get(item_id)
        if summary is None:  # removed meanwhile (finding 16), or not yet removed from the index
            continue
        if marks:
            lit: dict[str, list[str]] = {}
            for field, value, snip in (("title", summary.title, False),
                                       ("summary", summary.summary, True),
                                       ("title_en", summary.title_en, False),
                                       ("summary_en", summary.summary_en, True)):  # fmt: skip
                if got := highlight(value, marks, snip):
                    lit[field] = got
            summary.highlights = lit
        items.append(summary)
    took = int((time.monotonic() - started) * 1000)
    engine = "index" if from_index is not None else "sql"
    _log.info("search", query_hash=query_hash(query), user_id=str(user_id) if user_id else None,
              took_ms=took, total=total, engine=engine)  # fmt: skip
    return SearchResult(items=items, total=min(total, MAX_TOTAL), page=query.page,
                        page_size=query.page_size, facets=facets, took_ms=took)  # fmt: skip


async def _from_index(
    db: AsyncSession, query: Query
) -> tuple[list[uuid.UUID], int, dict[str, list[FacetCount]]] | None:
    """The page, total and facets from the index; None when it is not configured or cannot
    be reached (then PostgreSQL answers); a timeout is a 503."""
    if not index.configured():
        return None
    try:
        page_ids, total, aggs = await indexed.search(index.IndexClient(), query,
                                                     query.facet_counts)  # fmt: skip
    except index.IndexFailedError as exc:
        if exc.reason == "index-timeout":
            raise busy() from None
        unavailable(exc)
        return None
    try:
        facets = await _labelled(db, aggs) if query.facet_counts else {}
    except (KeyError, TypeError, ValueError, AttributeError):
        unavailable(index.IndexFailedError("index-answer", "unexpected facet buckets"))
        return None
    return page_ids, total, facets


def unavailable(exc: index.IndexFailedError) -> None:
    """Logged; refused credentials are an error, as every request then falls back (finding 4)."""
    if exc.reason == "index-auth":
        _log.error("index_refused_credentials", reason=exc.reason)
    else:
        _log.warning("index_unavailable", reason=exc.reason)


async def _labelled(db: AsyncSession, aggs: dict[str, Any]) -> dict[str, list[FacetCount]]:
    """The index's facet buckets with labels from PostgreSQL; only facets shown in filters."""
    counts: dict[tuple[str, str], int] = {}
    for bucket in aggs.get("terms", {}).get("buckets", []):
        facet, _, key = str(bucket["key"]).partition(":")
        counts[(facet, key)] = int(bucket["doc_count"])
    out: dict[str, list[FacetCount]] = {}
    if counts:
        rows = await db.execute(
            select(Facet.key, Term.key, Term.label).join(Term, Term.facet_id == Facet.id)
            .where(Facet.show_in_filters, Facet.key.in_({f for f, _ in counts}),
                   Term.key.in_({k for _, k in counts})))  # fmt: skip
        for facet, key, label in rows.tuples().all():
            if (facet, key) in counts:
                out.setdefault(facet, []).append(
                    FacetCount(key=key, label=label, count=counts[(facet, key)]))  # fmt: skip
    places = {str(b["key"]): int(b["doc_count"])
              for b in aggs.get("jurisdiction", {}).get("buckets", [])}  # fmt: skip
    if places:
        names = await db.execute(select(Jurisdiction.code, Jurisdiction.name)
                                 .where(Jurisdiction.code.in_(list(places))))  # fmt: skip
        out["jurisdiction"] = [FacetCount(key=c, label=n, count=places[c])
                               for c, n in names.tuples().all()]  # fmt: skip
    for values_ in out.values():
        values_.sort(key=lambda f: (-f.count, f.key))
        del values_[FACET_VALUES:]
    return out


async def _from_postgresql(
    db: AsyncSession, query: Query, terms: dict[str, list[uuid.UUID]]
) -> tuple[list[uuid.UUID], int, dict[str, list[FacetCount]]]:
    """The page, total and facets from PostgreSQL (no index, or the index unreachable)."""
    compiled = compile_query(query, terms)
    # First every match, unordered, up to MAX_TOTAL + 1: cheap however rare the words (an
    # ordered read walks the date index and, for a rare word, all of it; BL-118). If they all
    # fit, the page, its order, the total and the facets come from that list; if not, the
    # matches are many, and the ordered reads stop early.
    try:
        found_ids = list((await db.scalars(compiled.every.limit(MAX_TOTAL + 1))).all())
        if len(found_ids) <= MAX_TOTAL:
            matched_ids, total = found_ids, len(found_ids)
            compiled = compile_query(query, terms, within=found_ids)
        elif compiled.ranked:  # many matches: relevance pages through its candidates (R1)
            matched_ids = list((await db.scalars(compiled.matches)).all())
            total = len(matched_ids)
        else:
            matched_ids = list((await db.scalars(compiled.matches.limit(FACET_SAMPLE))).all())
            total = MAX_TOTAL + 1
        paged = compiled.ids.limit(query.page_size).offset((query.page - 1) * query.page_size)
        page_ids = list((await db.scalars(paged)).all())
    except DBAPIError as exc:
        if not timed_out(exc):
            raise
        await db.rollback()
        raise ProblemError(
            503,
            "busy",
            "The search took too long; narrow it and try again.",
            headers={"Retry-After": "5"},
        ) from None  # N2
    facets: dict[str, list[FacetCount]] = {}
    if query.facet_counts:
        try:
            facets = await facet_counts(db, matched_ids[:FACET_SAMPLE], query)
        except DBAPIError as exc:  # past the timeout: the results without counts (S9)
            if not timed_out(exc):
                raise
            await db.rollback()
    return page_ids, total, facets
