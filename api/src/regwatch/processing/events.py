"""Jurisdiction tags and change events (M4 ``process.geotag`` and ``process.events``; design
notes: severity rules; events ``item.captured`` and ``item.changed``).

- The detected jurisdictions replace the item's earlier ones of the same origin; a user's
  assignment (``assigned_by='user'``) is never replaced (acceptance 5's rule, for places too).
- A new item raises ``new_item`` and a changed one ``content_changed``, once per jurisdiction;
  an item with none is placed under ``INTL``, so no change goes unrecorded.
- Severity (M4 Q4): ``major`` when the title names an enforcement action or a regulation
  coming into force or adopted; ``notable`` when more than ``NOTABLE_PCT`` changed; else
  ``info``. Status changes of a regulation come with the regulation table (later).
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.processing.geotag import Hit
from regwatch.processing.models import ChangeEvent, Item, ItemJurisdiction
from regwatch.taxonomy.models import Jurisdiction

NOTABLE_PCT = 20.0
FALLBACK = "INTL"
MAX_SUMMARY = 500
# Enforcement, or an act's entry into force (M4 Q4); ordinary words such as "fine", "adopted"
# or "sanctions" alone are not enough (M4 pipeline review finding 4). CJK terms match as
# written: a word boundary never falls between two ideographs.
_MAJOR = re.compile(
    r"\b(enforcement action|fined|penalty notice|monetary penalt(y|ies)"
    r"|(enters|entered|entry) into force|tritt in kraft|in kraft getreten|bußgeldbescheid"
    r"|entre en vigueur|entra en vigor|entrou em vigor|sanction pécuniaire)\b"
    r"|施行される|施行された|罰金|課徴金",
    re.IGNORECASE,
)


def severity(title: str, changed_pct: float | None) -> str:
    if _MAJOR.search(title):
        return "major"
    if changed_pct is not None and changed_pct > NOTABLE_PCT:
        return "notable"
    return "info"


async def tag_jurisdictions(db: AsyncSession, item: Item, hits: list[Hit]) -> list[uuid.UUID]:
    """Replace the item's detected jurisdictions with ``hits``; the ids it now has."""
    by_code: dict[str, uuid.UUID] = {}
    if hits:
        wanted = [h.code for h in hits]
        active = (Jurisdiction.code.in_(wanted), Jurisdiction.active)
        found = await db.execute(select(Jurisdiction.code, Jurisdiction.id).where(*active))
        by_code = dict(found.tuples().all())
    mine = (ItemJurisdiction.item_id == item.id, ItemJurisdiction.assigned_by != "user")
    await db.execute(delete(ItemJurisdiction).where(*mine))
    users = set((await db.scalars(select(ItemJurisdiction.jurisdiction_id)
                                  .where(ItemJurisdiction.item_id == item.id))).all())  # fmt: skip
    for hit in hits:
        jid = by_code.get(hit.code)
        if jid is None or jid in users:
            continue
        origin = "source_default" if hit.evidence == "source default" else "rule"
        db.add(ItemJurisdiction(item_id=item.id, jurisdiction_id=jid, assigned_by=origin,
                                confidence=Decimal(str(hit.confidence))))  # fmt: skip
        users.add(jid)
    return sorted(users)


async def raise_events(db: AsyncSession, item: Item, kind: str, jurisdiction_ids: list[uuid.UUID],
                       changed_pct: float | None) -> list[ChangeEvent]:  # fmt: skip
    """``new_item`` or ``content_changed`` for each jurisdiction, or for ``INTL`` if none."""
    if not jurisdiction_ids:
        fallback = await db.scalar(select(Jurisdiction.id).where(Jurisdiction.code == FALLBACK))
        jurisdiction_ids = [fallback] if fallback is not None else []
    level = severity(item.title, changed_pct)
    summary = (f"{item.title[:400]} ({changed_pct:.1f} % changed)" if kind == "content_changed"
               and changed_pct is not None else item.title)[:MAX_SUMMARY]  # fmt: skip
    events = [ChangeEvent(item_id=item.id, jurisdiction_id=jid, kind=kind, severity=level,
                          summary=summary) for jid in jurisdiction_ids]  # fmt: skip
    db.add_all(events)
    return events
