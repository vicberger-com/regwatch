"""Service layer; other modules call this module only through here (ADR-0001).

Item reads (M4 interfaces: ``GET /items/{id}``, its versions and diffs):

- An item's text is its latest version's; ``content_html_url`` stays empty until the sanitized
  snapshot is written (BL-106 (b)).
- ``severity`` is the latest change event's; ``change_events`` are the latest ``MAX_EVENTS``.
- A diff between consecutive versions is the stored one; any other pair is computed with the
  same bounded functions as the pipeline (``versioning``), off the event loop.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.admin.services import not_found
from regwatch.capture.models import Source
from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.processing import versioning
from regwatch.processing.models import ChangeEvent, Item, ItemJurisdiction, ItemTerm, ItemVersion
from regwatch.processing.schemas import ChangeEvent as EventOut
from regwatch.processing.schemas import ItemDetail, ItemDiff, TermAssignment
from regwatch.processing.schemas import ItemJurisdiction as PlaceOut
from regwatch.processing.schemas import ItemVersion as VersionOut
from regwatch.taxonomy.models import Facet, Jurisdiction, Term

MAX_EVENTS = 50
MAX_VERSIONS = 200


async def _item(db: AsyncSession, item_id: uuid.UUID) -> Item:
    item = await db.get(Item, item_id)
    if item is None:
        raise not_found("item")
    return item


async def _version(db: AsyncSession, item_id: uuid.UUID, number: int) -> ItemVersion:
    where = (ItemVersion.item_id == item_id, ItemVersion.version_no == number)
    found = await db.scalar(select(ItemVersion).where(*where))
    if found is None:
        raise not_found("version")
    return found


async def item_detail(db: AsyncSession, item_id: uuid.UUID) -> ItemDetail:
    item = await _item(db, item_id)
    source_name = await db.scalar(select(Source.name).where(Source.id == item.source_id))
    places = await db.execute(
        select(Jurisdiction.code, Jurisdiction.name, ItemJurisdiction.confidence)
        .join(ItemJurisdiction, ItemJurisdiction.jurisdiction_id == Jurisdiction.id)
        .where(ItemJurisdiction.item_id == item.id).order_by(Jurisdiction.code))  # fmt: skip
    terms = await db.execute(
        select(ItemTerm, Term.key, Term.label, Facet.key)
        .join(Term, Term.id == ItemTerm.term_id).join(Facet, Facet.id == Term.facet_id)
        .where(ItemTerm.item_id == item.id).order_by(Facet.key, Term.key))  # fmt: skip
    events = await db.execute(
        select(ChangeEvent, Jurisdiction.code)
        .join(Jurisdiction, Jurisdiction.id == ChangeEvent.jurisdiction_id)
        .where(ChangeEvent.item_id == item.id)
        .order_by(ChangeEvent.occurred_at.desc(), ChangeEvent.id.desc())
        .limit(MAX_EVENTS))  # fmt: skip
    latest = await db.scalar(select(ItemVersion.content_text).where(ItemVersion.item_id == item.id)
                             .order_by(ItemVersion.version_no.desc()).limit(1))  # fmt: skip
    change_events = [
        EventOut(id=e.id, item_id=e.item_id, jurisdiction_code=code, kind=e.kind,
                 occurred_at=e.occurred_at, severity=e.severity, summary=e.summary,
                 acknowledged_by=e.acknowledged_by)
        for e, code in events.tuples().all()
    ]  # fmt: skip
    return ItemDetail(
        id=item.id, title=item.title, title_en=item.title_en, summary=item.summary,
        summary_en=item.summary_en, canonical_url=item.canonical_url, source_id=item.source_id,
        source_name=source_name or "", language=item.language, published_at=item.published_at,
        last_changed_at=item.last_changed_at, status=item.status,
        severity=change_events[0].severity if change_events else None,
        jurisdictions=[PlaceOut(code=c, name=n, confidence=float(conf))
                       for c, n, conf in places.tuples().all()],
        terms=[TermAssignment(term_id=t.term_id, facet_key=facet, key=key, label=label,
                              confidence=float(t.confidence), assigned_by=t.assigned_by,
                              feedback=t.feedback)
               for t, key, label, facet in terms.tuples().all()],
        attributes=item.attributes or {}, content_text=latest or "", content_text_en=None,
        content_html_url=None, current_version_no=item.current_version_no,
        needs_review=item.needs_review, translation_pending=item.translation_pending,
        regulation=None, change_events=change_events,
    )  # fmt: skip


async def item_versions(db: AsyncSession, item_id: uuid.UUID) -> list[VersionOut]:
    await _item(db, item_id)
    rows = await db.scalars(select(ItemVersion).where(ItemVersion.item_id == item_id)
                            .order_by(ItemVersion.version_no.desc())
                            .limit(MAX_VERSIONS))  # fmt: skip
    return [VersionOut(version_no=v.version_no, created_at=v.created_at, run_id=v.run_id,
                       content_hash=v.content_hash,
                       changed_pct=float(v.changed_pct) if v.changed_pct is not None else None,
                       translations=v.translations or {}) for v in rows.all()]  # fmt: skip


def _invalid(message: str) -> ProblemError:
    return ProblemError(422, "validation", message,
                        errors=[ProblemFieldError(field="from", message=message)])  # fmt: skip


async def item_diff(db: AsyncSession, item_id: uuid.UUID, start: int, end: int) -> ItemDiff:
    """The diff from version ``start`` to the later version ``end``."""
    if start < 1 or end <= start:
        raise _invalid("from must be a version before to")
    await _item(db, item_id)
    old, new = await _version(db, item_id, start), await _version(db, item_id, end)
    if end == start + 1 and new.diff_from_previous is not None and new.changed_pct is not None:
        return ItemDiff(from_version=start, to_version=end, changed_pct=float(new.changed_pct),
                        unified_diff=new.diff_from_previous)  # fmt: skip

    def compute() -> tuple[float, str]:
        a, b = old.content_text, new.content_text
        return versioning.changed_pct(a, b), versioning.unified_diff(a, b)

    pct, diff = await asyncio.to_thread(compute)
    return ItemDiff(from_version=start, to_version=end, changed_pct=pct, unified_diff=diff)
