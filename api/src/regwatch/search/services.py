"""Service layer; other modules call this module only through here (ADR-0001).

``POST /search`` (M5 acceptance 1): the compiled query, counted and paged, each item with its
jurisdictions, its terms (no ``incorrect`` ones), its highest severity and its source.

Highlights are built here, not by ``ts_headline``: the field is HTML-escaped first and only
then are the query's words wrapped in ``<mark>``, so a highlight holds no markup from the
captured (hostile) text, only ``<mark>`` and ``</mark>`` around escaped words.
"""

from __future__ import annotations

import hashlib
import html
import re
import time
import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture.models import Source
from regwatch.processing.models import ChangeEvent, Item, ItemJurisdiction, ItemTerm
from regwatch.processing.schemas import ItemJurisdiction as PlaceOut
from regwatch.processing.schemas import ItemSummary, TermAssignment
from regwatch.search.query import compile_query
from regwatch.search.schemas import Query, SearchResult
from regwatch.taxonomy.models import Facet, Jurisdiction, Term

MAX_WORDS = 20
SNIPPET = 300
_RANK = {"info": 0, "notable": 1, "major": 2}
_log = structlog.get_logger(__name__)


def words(q: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\w+", q.casefold())))[:MAX_WORDS]


def highlight(value: str | None, found: list[str], snippet: bool = False) -> list[str]:
    """``value`` escaped, its words of ``found`` in ``<mark>``; around the first match if
    ``snippet``. Empty if nothing matches."""
    if not value or not found:
        return []
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, found)) + r")\b", re.IGNORECASE)
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


async def _summaries(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, ItemSummary]:
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
            .where(ChangeEvent.item_id.in_(ids)))).tuples():  # fmt: skip
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


async def search(db: AsyncSession, query: Query, user_id: uuid.UUID | None) -> SearchResult:
    started = time.monotonic()
    compiled = compile_query(query)
    total = int(await db.scalar(select(func.count()).select_from(compiled.ids.subquery())) or 0)
    paged = compiled.ids.limit(query.page_size).offset((query.page - 1) * query.page_size)
    page_ids = list((await db.scalars(paged)).all())
    found = await _summaries(db, page_ids) if page_ids else {}
    marks = words(query.q or "") if query.highlight else []
    items = []
    for item_id in page_ids:
        summary = found[item_id]
        if marks:
            lit: dict[str, list[str]] = {}
            for field, value, snip in (("title", summary.title, False),
                                       ("summary", summary.summary, True)):  # fmt: skip
                if got := highlight(value, marks, snip):
                    lit[field] = got
            summary.highlights = lit
        items.append(summary)
    took = int((time.monotonic() - started) * 1000)
    digest = hashlib.sha256(query.model_dump_json(exclude_unset=True).encode()).hexdigest()[:16]
    _log.info("search", query_hash=digest, user_id=str(user_id) if user_id else None,
              took_ms=took, total=total)  # fmt: skip
    return SearchResult(items=items, total=total, page=query.page, page_size=query.page_size,
                        facets={}, took_ms=took)  # fmt: skip
