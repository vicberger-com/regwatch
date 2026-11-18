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

Fuzzy title near-duplicates (rapidfuzz) wait for their slice; a row without a language gets
the detected one (``processing.language``, M4 Q6); a non-English item is flagged
``translation_pending`` (no provider at launch, Q5).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture.connectors.rss import plain_text
from regwatch.capture.models import CaptureRun, Source
from regwatch.processing import versioning
from regwatch.processing.language import detect as detect_language
from regwatch.processing.models import Item, ItemVersion

MAX_TEXT = 1_000_000
RANK = {"official": 3, "secondary": 2, "news": 1}  # source credibility, for N8
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


# The official APIs (``api_feed``) and the hosts of the documents they describe: their rows
# speak for these URLs though the content comes from another address (EUR-Lex's Cellar) or
# from the API's record (re-verification 3, findings N5 and N6).
PROVIDER_HOSTS = {
    "federal_register": frozenset({"federalregister.gov"}),
    "eur_lex": frozenset({"eur-lex.europa.eu"}),
    "legislation_gov_uk": frozenset({"legislation.gov.uk"}),
}


def _fetched_host(row: dict[str, Any], canonical: str, kind: str = "") -> str | None:
    """The canonical URL's host when the row speaks for that URL (CP-19): its final URL, after
    redirects, is on that host (``www.`` aside), or it comes from the official API for that
    host. None for a feed summary, an upload or a page that redirected elsewhere (N4)."""
    want = _bare(canonical)
    found = row.get("metadata")
    provider = found.get("provider") if isinstance(found, dict) else None
    configured = kind.removeprefix("api_feed:") if kind.startswith("api_feed:") else None
    # The row's provider must be the one the source is configured for (a later adapter such as
    # ``generic_json`` can never speak for a provider's host by naming it; re-verification 4).
    if configured and provider == configured and want in PROVIDER_HOSTS.get(configured, ()):
        return want
    final = row.get("final_url")
    got = versioning.canonical_url(final) if isinstance(final, str) else None
    if got is None or not got.startswith(("http://", "https://")):
        return None
    return want if want and _bare(got) == want else None


def _bare(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return host.removeprefix("www.")


async def _captured(db: AsyncSession, item_id: uuid.UUID) -> datetime | None:
    """When the content of the item's latest version was captured: its run's start (a fetch
    is never before its run started), or None when the run is not recorded (finding N1)."""
    started: datetime | None = await db.scalar(
        select(CaptureRun.started_at).select_from(ItemVersion)
        .outerjoin(CaptureRun, ItemVersion.run_id == CaptureRun.id)
        .where(ItemVersion.item_id == item_id)
        .order_by(ItemVersion.version_no.desc()).limit(1))  # fmt: skip
    return started


async def ingest(
    db: AsyncSession,
    source_id: uuid.UUID,
    run_id: uuid.UUID | None,
    row: dict[str, Any],
    threshold_pct: float,
    retried: bool = False,
    kind: str = "",
    credibility: str = "",
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
    # The row speaks for the URL only when fetched from its host with extracted text, or from
    # its official API, on every path: a feed's full page (no text, the feed's title) never
    # marks an item fetched, so the publisher can still take it (re-verification 4, N7).
    fetched_host = (
        _fetched_host(row, canonical, kind) if text or kind.startswith("api_feed:") else None
    )
    claimed = False
    if item is not None and item.source_id != source_id:
        # Another source's item: a row from this source never changes it (M4 pipeline review
        # finding 1), unless the item's content was never fetched (a feed's summary) and this
        # row speaks for the URL: fetched from its host with text, or from its official API;
        # then the item passes to this source, and its content and title replace the summary
        # whatever the change share (CP-19, findings N4 to N6). A fetched item is never taken,
        # so two sources fetching one page never take it in turn. A fetched page without text
        # (a feed's full page, a PDF) waits for M4's extraction: no empty version over text.
        # A fetched item passes only to a more credible source that fetched it too (official
        # over secondary over news; BL-109 (a), finding N8): a search hit never holds the
        # publisher's page, and sources of equal standing never take it in turn.
        # Credibility counts on every claim (N10): an item never fetched passes to a fetching
        # source at least as credible as its owner, a fetched one only to a more credible one.
        if fetched_host is None:
            return Ingested("duplicate", item.id)
        owner = await db.scalar(select(Source.credibility)
                                .where(Source.id == item.source_id))  # fmt: skip
        mine, theirs = RANK.get(credibility, 0), RANK.get(owner or "", 0)
        if mine < theirs or (item.fetched_host is not None and mine == theirs):
            return Ingested("duplicate", item.id)
        item.source_id = source_id
        claimed = True
    if item is not None and item.fetched_host is None and fetched_host is not None:
        item.fetched_host = fetched_host  # the item's own source fetched it at last
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
        # The row's own language, else detected from the text (M4 Q6)
        language = _language(row.get("language")) or detect_language(title, text)
        item = Item(source_id=source_id, canonical_url=canonical, url_hash=url_hash,
                    external_id=_field(row.get("external_id"), 500), title=title,
                    summary=plain_text(_text(row.get("summary"), MAX_SUMMARY * 4), MAX_SUMMARY),
                    language=language, published_at=_when(row.get("published_at")),
                    content_hash=content_hash, fetched_host=fetched_host, status="new",
                    current_version_no=1,
                    translation_pending=bool(language) and not str(language).startswith("en"),
                    discovered_at=now, last_changed_at=now)  # fmt: skip
        try:
            async with db.begin_nested():  # a concurrent insert of the same URL (finding 7)
                db.add(item)
                await db.flush()
        except IntegrityError:
            if retried:  # not the race: let the row fail, logged by the pipeline
                raise
            return await ingest(
                db,
                source_id,
                run_id,
                row,
                threshold_pct,
                retried=True,
                kind=kind,
                credibility=credibility,
            )
        db.add(ItemVersion(item_id=item.id, run_id=run_id, version_no=1, content_text=text,
                           content_hash=content_hash))  # fmt: skip
        return Ingested("new", item.id)
    if item.content_hash == content_hash:  # the same document again: no version (idempotent)
        if claimed:
            item.title = title
        return Ingested("unchanged", item.id, 0.0)
    captured = await _captured(db, item.id)
    if not claimed and fetched is not None and captured is not None and fetched < captured:
        # Captured before the run of the item's latest version (a replayed manifest): never a
        # new version over newer content (finding 7). Processing time does not count (N1).
        return Ingested("unchanged", item.id)
    if not text and not claimed:
        # No extracted text (a PDF, or a body-only row): never versions over text the item
        # has, and a body change waits for M4's text extraction (finding 1, BL-107).
        return Ingested("unchanged", item.id)
    latest = await db.scalar(select(ItemVersion).where(ItemVersion.item_id == item.id)
                             .order_by(ItemVersion.version_no.desc()).limit(1))  # fmt: skip
    previous = latest.content_text if latest is not None else ""
    pct = versioning.changed_pct(previous, text)
    if pct < threshold_pct and not claimed:  # below the threshold: no version, no event (M4)
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
