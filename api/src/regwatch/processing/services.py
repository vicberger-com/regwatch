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
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.admin.services import not_found
from regwatch.capture.models import Source
from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.core.services import audit
from regwatch.processing import versioning
from regwatch.processing.models import ChangeEvent, Item, ItemJurisdiction, ItemTerm, ItemVersion
from regwatch.processing.schemas import ChangeEvent as EventOut
from regwatch.processing.schemas import ItemDetail, ItemDiff, TagsUpdate, TermAssignment
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


async def queue_reprocess(db: AsyncSession, item_id: uuid.UUID, actor: uuid.UUID,
                          ip: str | None) -> None:  # fmt: skip
    """Audit and queue ``process.reprocess_item``; 503 when the queue cannot take it."""
    from regwatch.processing import tasks

    await _item(db, item_id)
    audit(db, "item.reprocess", "item", item_id, actor=actor, ip=ip)
    await db.commit()
    try:
        await asyncio.to_thread(tasks.enqueue_reprocess, str(item_id))
    except Exception:  # noqa: BLE001 - any broker failure is the same answer to the caller
        raise ProblemError(503, "queue-unavailable", "Reprocessing could not be queued; "
                           "try again.") from None  # fmt: skip


MAX_TAGS = 100
MAX_CODE = 16


def _field_error(field: str, message: str) -> ProblemError:
    return ProblemError(422, "validation", message,
                        errors=[ProblemFieldError(field=field, message=message)])  # fmt: skip


async def update_tags(db: AsyncSession, item_id: uuid.UUID, body: TagsUpdate, actor: uuid.UUID,
                      ip: str | None) -> ItemDetail:  # fmt: skip
    """A user's own tags (``assigned_by='user'``, M4 acceptance 5).

    - Adding a term or jurisdiction makes it the user's at confidence 1, whoever set it before.
    - Removing a user's term deletes it; removing a rule, model or default term marks it
      ``incorrect``, so a later run never tags it again. Removing a jurisdiction deletes it.
    - ``feedback`` judges terms the item has; a judged term is kept as judged by later runs.
    """
    add_ids, drop_ids = body.add_term_ids or [], body.remove_term_ids or []
    add_codes = body.add_jurisdiction_codes or []
    drop_codes = body.remove_jurisdiction_codes or []
    verdicts = body.feedback or []
    sizes = {"add_term_ids": len(add_ids), "remove_term_ids": len(drop_ids),
             "add_jurisdiction_codes": len(add_codes),
             "remove_jurisdiction_codes": len(drop_codes), "feedback": len(verdicts)}  # fmt: skip
    for field, size in sizes.items():
        if size > MAX_TAGS:
            raise _field_error(field, f"at most {MAX_TAGS} at once")
    add_terms, drop_terms = set(add_ids), set(drop_ids)
    if any(len(c) > MAX_CODE for c in [*add_codes, *drop_codes]):
        raise _field_error("add_jurisdiction_codes", "not a jurisdiction code")
    add_places = {c.upper() for c in add_codes}
    drop_places = {c.upper() for c in drop_codes}
    if add_terms & drop_terms:
        raise _field_error("remove_term_ids", "a term cannot be added and removed at once")
    if add_places & drop_places:
        raise _field_error("remove_jurisdiction_codes",
                           "a jurisdiction cannot be added and removed at once")  # fmt: skip
    item = await db.scalar(select(Item).where(Item.id == item_id).with_for_update())
    if item is None:
        raise not_found("item")
    known = set((await db.scalars(select(Term.id).where(Term.id.in_(add_terms),
                                                        Term.active))).all())  # fmt: skip
    if add_terms - known:
        raise _field_error("add_term_ids", "unknown or inactive term")
    codes = add_places | drop_places
    found = await db.execute(select(Jurisdiction.code, Jurisdiction.id)
                             .where(Jurisdiction.code.in_(codes)))  # fmt: skip
    places = dict(found.tuples().all())
    if add_places - set(places) or drop_places - set(places):
        raise _field_error("add_jurisdiction_codes", "unknown jurisdiction code")
    rows = {t.term_id: t for t in (await db.scalars(
        select(ItemTerm).where(ItemTerm.item_id == item.id).with_for_update())).all()}  # fmt: skip
    judged = {f.term_id: f.feedback for f in verdicts}
    if set(judged) - set(rows) - add_terms:
        raise _field_error("feedback", "feedback only on a term the item has")
    before = {"terms": sorted(str(t) for t in rows),
              "jurisdictions": sorted(await _codes(db, item.id))}  # fmt: skip
    for term_id in add_terms:
        row = rows.get(term_id)
        if row is None:
            row = ItemTerm(item_id=item.id, term_id=term_id)
            db.add(row)
            rows[term_id] = row
        row.assigned_by, row.assigned_user_id = "user", actor
        row.confidence, row.feedback = Decimal("1"), None
    for term_id in drop_terms:
        row = rows.pop(term_id, None)
        if row is None:
            continue
        if row.assigned_by == "user":
            await db.delete(row)
        else:
            row.feedback = "incorrect"
            rows[term_id] = row
    for term_id, verdict in judged.items():
        if term_id in rows:
            rows[term_id].feedback = verdict
    if drop_places:
        await db.execute(delete(ItemJurisdiction).where(
            ItemJurisdiction.item_id == item.id,
            ItemJurisdiction.jurisdiction_id.in_([places[c] for c in drop_places])))  # fmt: skip
    for code in add_places:
        await db.execute(
            pg_insert(ItemJurisdiction)
            .values(item_id=item.id, jurisdiction_id=places[code], assigned_by="user",
                    assigned_user_id=actor, confidence=Decimal("1"))
            .on_conflict_do_update(index_elements=["item_id", "jurisdiction_id"],
                                   set_={"assigned_by": "user", "assigned_user_id": actor,
                                         "confidence": Decimal("1")}))  # fmt: skip
    await db.flush()
    after = {"terms": sorted(str(t) for t in rows),
             "jurisdictions": sorted(await _codes(db, item.id)),
             "feedback": {str(k): v for k, v in judged.items()}}  # fmt: skip
    audit(db, "item.tags", "item", item.id, actor=actor, ip=ip, before=before, after=after)
    await db.commit()
    return await item_detail(db, item.id)


async def _codes(db: AsyncSession, item_id: uuid.UUID) -> list[str]:
    return list((await db.scalars(
        select(Jurisdiction.code).join(ItemJurisdiction,
                                       ItemJurisdiction.jurisdiction_id == Jurisdiction.id)
        .where(ItemJurisdiction.item_id == item_id))).all())  # fmt: skip
