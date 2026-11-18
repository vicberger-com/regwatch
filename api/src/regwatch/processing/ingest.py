"""Items and versions from a capture run's manifest (M4 ``process.extract``, ``process.dedupe``
and ``process.version``; acceptance 1; design notes: dedupe order, change threshold,
idempotency).

A manifest row is hostile like any capture, and is read field by field with checks: the URL
must canonicalise, text and titles are bounded, dates must parse. For each row:

1. ``url_hash`` of the canonical URL finds the item; its row is locked for the update.
2. A new URL whose content hash matches another item of the same source is a duplicate (the
   same document at a second address): no item is made.
3. A new item gets version 1. A known item with the same content hash is unchanged (processing
   a document twice makes no version). Otherwise the change share is computed against the
   latest version; below the job's ``change_threshold_pct`` the item is ``unchanged`` and no
   version is made, else version n+1 with its diff.

Fuzzy title near-duplicates (rapidfuzz) and language detection wait for their dependencies
(M4 Q6); a non-English item is flagged ``translation_pending`` (no provider at launch, Q5).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture.connectors.rss import plain_text
from regwatch.processing import versioning
from regwatch.processing.models import Item, ItemVersion

MAX_TEXT = 1_000_000
MAX_TITLE = 500
MAX_SUMMARY = 4000
Kind = Literal["new", "changed", "unchanged", "duplicate", "skipped"]


@dataclass(frozen=True)
class Ingested:
    kind: Kind
    item_id: uuid.UUID | None = None
    changed_pct: float | None = None


def _text(value: Any, limit: int) -> str | None:  # noqa: ANN401 - a manifest field
    return value[:limit] if isinstance(value, str) else None


def _when(value: Any) -> datetime | None:  # noqa: ANN401 - a manifest field
    if not isinstance(value, str):
        return None
    try:
        got = datetime.fromisoformat(value)
    except ValueError:
        return None
    return got if got.tzinfo else got.replace(tzinfo=UTC)


def _content(row: dict[str, Any]) -> tuple[str, str]:
    """(text, content hash): the extracted text when there is any, else the stored body's own
    hash (a PDF, which M4 reads later), so two copies of one file still match."""
    text = _text(row.get("text"), MAX_TEXT) or ""
    if text:
        return text, versioning.sha256(text)
    ref = row.get("body_ref")
    body = ref.rsplit("/", 1)[-1] if isinstance(ref, str) else ""
    return "", body if len(body) == 64 else versioning.sha256(str(row.get("url")))


async def ingest(db: AsyncSession, source_id: uuid.UUID, run_id: uuid.UUID | None,
                 row: dict[str, Any], threshold_pct: float) -> Ingested:  # fmt: skip
    """One manifest row as an item; the caller commits."""
    url = row.get("url")
    canonical = versioning.canonical_url(url) if isinstance(url, str) else None
    if canonical is None:
        return Ingested("skipped")
    url_hash = versioning.sha256(canonical)
    text, content_hash = _content(row)
    found = row.get("metadata")
    metadata: dict[str, Any] = found if isinstance(found, dict) else {}
    title = plain_text(_text(row.get("title"), MAX_TITLE * 4) or metadata.get("title"),
                       MAX_TITLE) or canonical[:MAX_TITLE]  # fmt: skip
    now = datetime.now(UTC)
    item = await db.scalar(select(Item).where(Item.url_hash == url_hash).with_for_update())
    if item is None:
        same = await db.scalar(select(Item.id).where(Item.source_id == source_id,
                                                     Item.content_hash == content_hash)
                               .limit(1))  # fmt: skip
        if same is not None:
            return Ingested("duplicate", same)
        language = _text(row.get("language"), 35)
        item = Item(source_id=source_id, canonical_url=canonical, url_hash=url_hash,
                    external_id=_text(row.get("external_id"), 500), title=title,
                    summary=plain_text(_text(row.get("summary"), MAX_SUMMARY * 4), MAX_SUMMARY),
                    language=language, published_at=_when(row.get("published_at")),
                    content_hash=content_hash, status="new", current_version_no=1,
                    translation_pending=bool(language) and not str(language).startswith("en"),
                    discovered_at=now, last_changed_at=now)  # fmt: skip
        db.add(item)
        await db.flush()
        db.add(ItemVersion(item_id=item.id, run_id=run_id, version_no=1, content_text=text,
                           content_hash=content_hash))  # fmt: skip
        return Ingested("new", item.id)
    if item.content_hash == content_hash:  # the same document again: no version (idempotent)
        return Ingested("unchanged", item.id, 0.0)
    latest = await db.scalar(select(ItemVersion).where(ItemVersion.item_id == item.id)
                             .order_by(ItemVersion.version_no.desc()).limit(1))  # fmt: skip
    previous = latest.content_text if latest is not None else ""
    pct = versioning.changed_pct(previous, text)
    if pct < threshold_pct:  # below the job's threshold: no version, no event (M4 design)
        item.status = "unchanged"
        return Ingested("unchanged", item.id, pct)
    number = item.current_version_no + 1
    db.add(ItemVersion(item_id=item.id, run_id=run_id, version_no=number, content_text=text,
                       content_hash=content_hash, changed_pct=Decimal(str(pct)),
                       diff_from_previous=versioning.unified_diff(previous, text)))  # fmt: skip
    item.current_version_no = number
    item.content_hash = content_hash
    item.status = "updated"
    item.last_changed_at = now
    item.title = title
    return Ingested("changed", item.id, pct)
