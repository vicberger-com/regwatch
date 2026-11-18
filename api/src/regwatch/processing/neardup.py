"""Fuzzy title near-duplicates (M4 design notes, dedupe order: after the URL and content
hashes; Q6, rapidfuzz 3.14.6 approved 2026-11-18).

A new item whose title reaches ``processing.near_duplicate_ratio`` (92) by rapidfuzz's token-set
ratio against an item that shares one of its jurisdictions and was discovered in the last
``WINDOW_DAYS`` days is a near-duplicate: the same news under another address. It is kept and
marked ``needs_review``, and raises no ``new_item`` event, so one story is not announced twice.
A title that is only the URL (a row without one) is never compared. The comparison is
symmetric, and at most ``MAX_CANDIDATES`` recent items are compared.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from rapidfuzz import fuzz, utils
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.processing.models import Item, ItemJurisdiction

WINDOW_DAYS = 7
MAX_CANDIDATES = 200
DEFAULT_RATIO = 92
MIN_TITLE = 12  # characters; shorter titles ("Notice", "Press release") say too little


def similar(a: str, b: str) -> float:
    """Token-set ratio of two titles, ignoring case and punctuation; symmetric."""
    return float(fuzz.token_set_ratio(a, b, processor=utils.default_process))


def comparable(item: Item) -> bool:
    title = item.title.strip()
    return len(title) >= MIN_TITLE and not title.startswith(("http://", "https://", "urn:"))


async def near_duplicate(db: AsyncSession, item: Item, jurisdiction_ids: list[uuid.UUID],
                         ratio: float = DEFAULT_RATIO) -> uuid.UUID | None:  # fmt: skip
    """The earlier item ``item`` nearly duplicates, if any."""
    if not jurisdiction_ids or not comparable(item):
        return None
    since = datetime.now(UTC) - timedelta(days=WINDOW_DAYS)
    rows = await db.execute(
        select(Item.id, Item.title).distinct()
        .join(ItemJurisdiction, ItemJurisdiction.item_id == Item.id)
        .where(ItemJurisdiction.jurisdiction_id.in_(jurisdiction_ids), Item.id != item.id,
               Item.discovered_at >= since)
        .order_by(Item.id.desc()).limit(MAX_CANDIDATES))  # fmt: skip
    for other_id, title in rows.tuples().all():
        if len(title.strip()) >= MIN_TITLE and similar(item.title, title) >= ratio:
            return other_id
    return None
