"""The M4 chain for one capture run's manifest (``process.extract`` with the stages it runs:
dedupe, version, geotag, classify, events; translate joins when a provider is chosen).

The manifest is read back from the object store under the exact key the run wrote, and each
document is processed in its own transaction, so one bad row never loses the others. A row
that fails is logged by kind, never by content, and counted.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.admin.services import values
from regwatch.capture.models import CaptureJob, CaptureRun, Source
from regwatch.processing import geotag, neardup
from regwatch.processing.classify import MIN_CONFIDENCE, classify, load_rules
from regwatch.processing.events import raise_events, tag_jurisdictions
from regwatch.processing.ingest import ingest
from regwatch.processing.models import Item, ItemVersion
from regwatch.taxonomy.models import Jurisdiction

MANIFEST = re.compile(r"raw/([0-9a-f-]{36})/runs/([0-9a-f-]{36})\.json")
MAX_ROWS = 2000
Load = Callable[[str], Awaitable[bytes | None]]
Store = Callable[[str, bytes], Awaitable[None]]
_log = structlog.get_logger("regwatch.processing")


@dataclass
class Counts:
    by_kind: dict[str, int] = field(default_factory=dict)
    failed: int = 0

    def add(self, kind: str) -> None:
        self.by_kind[kind] = self.by_kind.get(kind, 0) + 1


def marker_key(manifest: str) -> str:
    """Written when a manifest has been processed; the hourly sweep looks for it."""
    return manifest.removesuffix(".json") + ".processed"


async def process_manifest(db: AsyncSession, key: str, load: Load,
                           store: Store | None = None) -> Counts:  # fmt: skip
    """Every document of the run whose manifest is ``key``."""
    counts = Counts()
    match = MANIFEST.fullmatch(key)
    if match is None:
        raise ValueError("not a run manifest key")
    source_id, run_id = uuid.UUID(match[1]), uuid.UUID(match[2])
    raw = await load(key)
    data: Any = json.loads(raw) if raw else {}
    rows = data.get("documents") if isinstance(data, dict) else None
    source = await db.scalar(select(Source).where(Source.id == source_id))
    job = await db.scalar(select(CaptureJob).where(CaptureJob.source_id == source_id))
    if not isinstance(rows, list) or source is None:
        return counts
    threshold = float(job.change_threshold_pct) if job is not None else 5.0
    # The version names the run that brought it, if that run is still recorded.
    known: uuid.UUID | None = await db.scalar(select(CaptureRun.id).where(CaptureRun.id == run_id))
    # ``api_feed:<provider>`` for an official API source, from the source row (never the manifest)
    provider = (source.config or {}).get("provider") if source.kind == "api_feed" else None
    kind = f"api_feed:{provider}" if isinstance(provider, str) else source.kind
    wanted = list(source.default_jurisdiction_ids or [])
    found = await db.scalars(select(Jurisdiction.code).where(Jurisdiction.id.in_(wanted)))
    defaults = list(found.all())
    rules = await load_rules(db)
    settings = await values(db, ["classification.min_confidence",
                                 "processing.near_duplicate_ratio"])  # fmt: skip
    try:
        min_confidence = float(settings["classification.min_confidence"])
    except (TypeError, ValueError):
        min_confidence = MIN_CONFIDENCE
    try:
        ratio = float(settings["processing.near_duplicate_ratio"])
    except (TypeError, ValueError):
        ratio = float(neardup.DEFAULT_RATIO)
    terms = list(source.default_term_ids or [])
    await db.commit()
    for row in rows[:MAX_ROWS]:
        if not isinstance(row, dict):
            counts.failed += 1
            continue
        try:
            got = await ingest(
                db, source_id, known, row, threshold, kind=kind, credibility=source.credibility
            )
            counts.add(got.kind)
            if got.kind in ("new", "changed") and got.item_id is not None:
                item = await db.get(Item, got.item_id)
                assert item is not None  # noqa: S101 - just made or locked
                value = row.get("text")
                text = value if isinstance(value, str) else ""
                hits = geotag.detect(item.title, text, item.canonical_url, defaults)
                ids = await tag_jurisdictions(db, item, hits)
                await classify(db, item, text, rules, terms, min_confidence)
                event = "new_item" if got.kind == "new" else "content_changed"
                twin = (
                    await neardup.near_duplicate(db, item, ids, ratio)
                    if got.kind == "new"
                    else None
                )
                if twin is not None:  # the same story at another address: no second event
                    item.needs_review = True
                    counts.add("near_duplicate")
                else:
                    await raise_events(db, item, event, ids, got.changed_pct)
            await db.commit()
        except SoftTimeLimitExceeded:  # the worker's limit: stop, the sweep hands it over again
            await db.rollback()
            raise
        except Exception as exc:  # noqa: BLE001 - one row never stops the run's others
            await db.rollback()
            counts.failed += 1
            _log.warning("processing_row_failed", run_id=str(run_id), error=type(exc).__name__)
    if store is not None:
        await store(marker_key(key), json.dumps({"failed": counts.failed,
                                                 **counts.by_kind}).encode())  # fmt: skip
    return counts


async def sweep(db: AsyncSession, load: Load, hand_over: Callable[[str], Awaitable[None]],
                hours: int = 48) -> int:  # fmt: skip
    """Hand over again every run of the last ``hours`` that stored documents and whose
    manifest has no processed marker: a broker that was down, a worker that died, a task that
    was killed (M4 pipeline review finding 3). Processing is idempotent, so a repeat is safe."""
    since = datetime.now(UTC) - timedelta(hours=hours)
    stored = (CaptureRun.finished_at >= since,
              (CaptureRun.items_new + CaptureRun.items_changed) > 0)  # fmt: skip
    joined = select(CaptureRun.id, CaptureJob.source_id).join(
        CaptureJob, CaptureJob.id == CaptureRun.job_id)  # fmt: skip
    rows = await db.execute(joined.where(*stored))
    handed = 0
    for run_id, source_id in rows.tuples().all():
        key = f"raw/{source_id}/runs/{run_id}.json"
        if await load(marker_key(key)) is None and await load(key) is not None:
            await hand_over(key)
            handed += 1
    return handed


async def reprocess_item(db: AsyncSession, item_id: uuid.UUID) -> bool:
    """Tag ``item_id`` again from its latest version with today's rules and source defaults
    (M4 acceptance 5): jurisdictions and terms are replaced, a user's own tags and judged tags
    are kept, and no change event is raised (the content did not change). False if gone."""
    item = await db.scalar(select(Item).where(Item.id == item_id).with_for_update())
    if item is None:
        return False
    source = await db.scalar(select(Source).where(Source.id == item.source_id))
    text = await db.scalar(select(ItemVersion.content_text).where(ItemVersion.item_id == item.id)
                           .order_by(ItemVersion.version_no.desc()).limit(1))  # fmt: skip
    wanted = list(source.default_jurisdiction_ids or []) if source is not None else []
    found = await db.scalars(select(Jurisdiction.code).where(Jurisdiction.id.in_(wanted)))
    settings = await values(db, ["classification.min_confidence"])
    try:
        min_confidence = float(settings["classification.min_confidence"])
    except (TypeError, ValueError):
        min_confidence = MIN_CONFIDENCE
    hits = geotag.detect(item.title, text or "", item.canonical_url, list(found.all()))
    await tag_jurisdictions(db, item, hits)
    terms = list(source.default_term_ids or []) if source is not None else []
    await classify(db, item, text or "", await load_rules(db), terms, min_confidence)
    await db.commit()
    return True
