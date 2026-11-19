"""Fuzzy title near-duplicates (M4 design notes, dedupe order: after the URL and content
hashes; Q6, rapidfuzz 3.14.6 approved 2026-11-18).

A new item is a near-duplicate (the same news under another address) of an earlier item when:

- both titles have at least ``MIN_WORDS`` words, neither is only a URL, and their lengths are
  within ``MIN_LENGTH_RATIO`` of each other;
- rapidfuzz's token-sort ratio (word order aside, never mere containment: a short or catch-all
  title cannot match the long titles it is part of; pipeline re-verification 6, N9) reaches
  ``processing.near_duplicate_ratio`` (92, at least 80);
- they carry the same numbers (act numbers, years, dates are identity; re-verification 7, N13);
- they come from different sources (one source's distinct URLs are distinct documents);
- they share a jurisdiction, the earlier one was discovered in the last ``WINDOW_DAYS`` days,
  and its source is at least as credible as the new item's (a news feed never silences an
  official source), and a fetched item is silenced only by another fetched one.

It is kept and marked ``needs_review``, and raises no ``new_item`` event, so one story is not
announced twice. The comparison is symmetric; at most ``MAX_CANDIDATES`` recent items are
compared.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

from rapidfuzz import fuzz, utils
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture.models import Source
from regwatch.processing.models import Item, ItemJurisdiction

WINDOW_DAYS = 7
MAX_CANDIDATES = 200
DEFAULT_RATIO = 92
MIN_TITLE = 12  # characters; shorter titles ("Notice", "Press release") say too little
MIN_WORDS = 4
MIN_LENGTH_RATIO = 0.8
RANK = {"official": 3, "secondary": 2, "news": 1}
_DIGITS = re.compile(r"\d+")


def similar(a: str, b: str) -> float:
    """Token-sort ratio of two titles, ignoring case, punctuation and word order; symmetric.
    Titles too short, or of too different lengths, to be the same story give 0."""
    if not (_comparable(a) and _comparable(b)):
        return 0.0
    if sorted(_DIGITS.findall(a)) != sorted(_DIGITS.findall(b)):
        return 0.0  # numbers are identity: Regulation 2026/1234 is not 2026/1235 (N13)
    x, y = utils.default_process(a), utils.default_process(b)
    if min(len(x), len(y)) < MIN_LENGTH_RATIO * max(len(x), len(y)):
        return 0.0
    return float(fuzz.token_sort_ratio(x, y))


def _comparable(title: str) -> bool:
    title = title.strip()
    return (len(title) >= MIN_TITLE and len(title.split()) >= MIN_WORDS
            and not title.startswith(("http://", "https://", "urn:")))  # fmt: skip


def comparable(item: Item) -> bool:
    return _comparable(item.title)


async def near_duplicate(db: AsyncSession, item: Item, jurisdiction_ids: list[uuid.UUID],
                         ratio: float = DEFAULT_RATIO) -> uuid.UUID | None:  # fmt: skip
    """The earlier item ``item`` nearly duplicates, if any."""
    if not jurisdiction_ids or not comparable(item):
        return None
    since = datetime.now(UTC) - timedelta(days=WINDOW_DAYS)
    mine = await db.scalar(select(Source.credibility).where(Source.id == item.source_id))
    standing = [c for c, rank in RANK.items() if rank >= RANK.get(mine or "", 0)]
    rows = await db.execute(
        select(Item.id, Item.title).distinct()
        .join(ItemJurisdiction, ItemJurisdiction.item_id == Item.id)
        .join(Source, Source.id == Item.source_id)
        .where(ItemJurisdiction.jurisdiction_id.in_(jurisdiction_ids), Item.id != item.id,
               Item.source_id != item.source_id,  # a source's own URLs are its own documents
               Item.discovered_at >= since, Source.credibility.in_(standing),
               # an item only listed (a feed's copy) never silences one fetched from its host
               # (re-verification 8, N17)
               *([Item.fetched_host.is_not(None)] if item.fetched_host is not None else []))
        .order_by(Item.id.desc()).limit(MAX_CANDIDATES))  # fmt: skip
    for other_id, title in rows.tuples().all():
        if similar(item.title, title) >= max(ratio, 80.0):
            return other_id
    return None
