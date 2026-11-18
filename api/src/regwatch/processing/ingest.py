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

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture.connectors.rss import plain_text
from regwatch.processing import versioning
from regwatch.processing.models import Item, ItemVersion

MAX_TEXT = 1_000_000
MAX_TITLE = 500
MAX_SUMMARY = 4000
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_LANGUAGE = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8}){0,3}")
Kind = Literal["new", "changed", "unchanged", "duplicate", "skipped"]


@dataclass(frozen=True)
class Ingested:
    kind: Kind
    item_id: uuid.UUID | None = None
    changed_pct: float | None = None


def _clean(value: str) -> str:
    """Text PostgreSQL stores: no NUL, no lone surrogate (finding 6)."""
    return value.replace("\x00", "").encode("utf-8", "replace").decode("utf-8")


def _text(value: Any, limit: int) -> str | None:  # noqa: ANN401 - a manifest field
    return _clean(value[:limit]) if isinstance(value, str) else None


def _field(value: Any, limit: int) -> str | None:  # noqa: ANN401 - a manifest field
    """A one-line field (external id): no control characters or line breaks (finding 9)."""
    text = _text(value, limit)
    return _CONTROL.sub("", text).strip() or None if text is not None else None


def _language(value: Any) -> str | None:  # noqa: ANN401 - a manifest field
    return value if isinstance(value, str) and _LANGUAGE.fullmatch(value) else None


def _when(value: Any) -> datetime | None:  # noqa: ANN401 - a manifest field
    """A date the database can hold, between 1900 and 2100 (finding 6), else None."""
    if not isinstance(value, str):
        return None
    try:
        got = datetime.fromisoformat(value)
        got = got if got.tzinfo else got.replace(tzinfo=UTC)
        got = got.astimezone(UTC)
    except (ValueError, OverflowError):
        return None
    return got if 1900 <= got.year <= 2100 else None


def _content(row: dict[str, Any], source_id: uuid.UUID) -> tuple[str, str]:
    """(text, content hash): the extracted text when there is any, else the stored body's own
    hash (a PDF, which M4 reads later), trusted only under this source's own raw key
    (finding 5), so two copies of one file still match."""
    text = _text(row.get("text"), MAX_TEXT) or ""
    if text:
        return text, versioning.sha256(text)
    ref = row.get("body_ref")
    if isinstance(ref, str) and re.fullmatch(rf"raw/{source_id}/[0-9a-f]{{64}}", ref):
        return "", ref.rsplit("/", 1)[1]
    return "", versioning.sha256(f"no-body:{row.get('url')}")


def _host(url: str) -> str:
    return url.split("://", 1)[1].split("/", 1)[0] if "://" in url else url


async def ingest(
    db: AsyncSession,
    source_id: uuid.UUID,
    run_id: uuid.UUID | None,
    row: dict[str, Any],
    threshold_pct: float,
    retried: bool = False,
) -> Ingested:
    """One manifest row as an item; the caller commits."""
    url = row.get("url")
    canonical = versioning.canonical_url(url) if isinstance(url, str) else None
    if canonical is None:
        return Ingested("skipped")
    url_hash = versioning.sha256(canonical)
    text, content_hash = _content(row, source_id)
    fetched = _when(row.get("fetched_at"))
    found = row.get("metadata")
    metadata: dict[str, Any] = found if isinstance(found, dict) else {}
    title = plain_text(_text(row.get("title"), MAX_TITLE * 4) or metadata.get("title"),
                       MAX_TITLE) or canonical[:MAX_TITLE]  # fmt: skip
    now = datetime.now(UTC)
    item = await db.scalar(select(Item).where(Item.url_hash == url_hash).with_for_update())
    if item is not None and item.source_id != source_id:
        # Another source's item: a row from this source never changes it, whatever its URL
        # (M4 pipeline review finding 1).
        return Ingested("duplicate", item.id)
    if item is None:
        # The same content at another address of the same host and source is a duplicate; a
        # copy on another host never hides the original (finding 5).
        candidates = (await db.execute(
            select(Item.id, Item.canonical_url)
            .where(Item.source_id == source_id, Item.content_hash == content_hash)
            .limit(20))).tuples().all()  # fmt: skip
        same = next((i for i, u in candidates if _host(u) == _host(canonical)), None)
        if same is not None:
            return Ingested("duplicate", same)
        language = _language(row.get("language"))
        item = Item(source_id=source_id, canonical_url=canonical, url_hash=url_hash,
                    external_id=_field(row.get("external_id"), 500), title=title,
                    summary=plain_text(_text(row.get("summary"), MAX_SUMMARY * 4), MAX_SUMMARY),
                    language=language, published_at=_when(row.get("published_at")),
                    content_hash=content_hash, status="new", current_version_no=1,
                    translation_pending=bool(language) and not str(language).startswith("en"),
                    discovered_at=now, last_changed_at=now)  # fmt: skip
        try:
            async with db.begin_nested():  # a concurrent insert of the same URL (finding 7)
                db.add(item)
                await db.flush()
        except IntegrityError:
            if retried:  # not the race: let the row fail, logged by the pipeline
                raise
            return await ingest(db, source_id, run_id, row, threshold_pct, retried=True)
        db.add(ItemVersion(item_id=item.id, run_id=run_id, version_no=1, content_text=text,
                           content_hash=content_hash))  # fmt: skip
        return Ingested("new", item.id)
    if item.content_hash == content_hash:  # the same document again: no version (idempotent)
        return Ingested("unchanged", item.id, 0.0)
    if fetched is not None and fetched < item.last_changed_at:
        # An older capture than the item's last change (a replayed manifest): never a new
        # version over newer content (finding 7).
        return Ingested("unchanged", item.id)
    if not text:
        # No extracted text (a PDF, or a body-only row): never versions over text the item
        # has, and a body change waits for M4's text extraction (finding 1, BL-107).
        return Ingested("unchanged", item.id)
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
