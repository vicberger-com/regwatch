"""The M4 chain for a run's manifest: items, jurisdictions and change events."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture import execution, runs
from regwatch.capture.models import CaptureRun
from regwatch.processing.models import ChangeEvent, Item, ItemJurisdiction
from regwatch.processing.pipeline import process_manifest
from regwatch.taxonomy.models import Jurisdiction
from tests.integration.test_admin import _api, admin
from tests.integration.test_auth import clear_limits, db_url
from tests.integration.test_capture_runs import _factory, _site, db
from tests.integration.test_sources import fixed_dns, rss

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db", "db_url", "fixed_dns"]  # shared fixtures

BSI = "Das Bundesamt für Sicherheit in der Informationstechnik veröffentlicht neue Regeln.\n" * 30


def manifest(sid: str, run_id: uuid.UUID, rows: list[Any]) -> tuple[str, dict[str, bytes]]:
    key = execution.manifest_key(sid, run_id)
    return key, {key: json.dumps({"run_id": str(run_id), "documents": rows}).encode()}


async def made_source(admin: httpx.AsyncClient, **extra: Any) -> str:
    made = await admin.post(_api("/sources"), json=rss(**extra))
    assert made.status_code == 201, made.text
    return str(made.json()["id"])


def loader(objects: dict[str, bytes]) -> Any:
    async def load(key: str) -> bytes | None:
        return objects.get(key)

    return load


async def test_a_new_item_is_tagged_and_raises_an_event(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Acceptance 2 through the chain: Germany at 0.9 with no source default."""
    sid = await made_source(admin)
    key, objects = manifest(
        sid,
        uuid.uuid4(),
        [
            {"url": "https://example.org/leitlinie", "text": BSI, "title": "Neue Leitlinie"},
            "not a row",
            {"url": "javascript:alert(1)"},
        ],
    )
    counts = await process_manifest(db, key, loader(objects))
    assert counts.by_kind == {"new": 1, "skipped": 1} and counts.failed == 1
    item = await db.scalar(select(Item).where(Item.source_id == uuid.UUID(sid)))
    assert item is not None
    tags = (
        await db.execute(
            select(Jurisdiction.code, ItemJurisdiction.confidence, ItemJurisdiction.assigned_by)
            .join(ItemJurisdiction, ItemJurisdiction.jurisdiction_id == Jurisdiction.id)
            .where(ItemJurisdiction.item_id == item.id)
        )
    ).all()
    assert [(c, float(v), a) for c, v, a in tags] == [("DE", 0.9, "rule")]
    events = (await db.scalars(select(ChangeEvent).where(ChangeEvent.item_id == item.id))).all()
    assert [(e.kind, e.severity) for e in events] == [("new_item", "info")]


async def test_a_change_raises_content_changed_and_a_rerun_nothing(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    sid = await made_source(admin)
    first_key, objects = manifest(
        sid, uuid.uuid4(), [{"url": "https://example.org/a", "text": BSI, "title": "Regel"}]
    )
    await process_manifest(db, first_key, loader(objects))
    again = await process_manifest(db, first_key, loader(objects))  # the same manifest twice
    assert again.by_kind == {"unchanged": 1}
    changed = BSI.replace("neue Regeln", "eine Bußgeld-Regel und weitere Pflichten")
    key, more = manifest(
        sid,
        uuid.uuid4(),
        [{"url": "https://example.org/a", "text": changed, "title": "Regel tritt in Kraft"}],
    )
    counts = await process_manifest(db, key, loader(more))
    assert counts.by_kind == {"changed": 1}
    item = await db.scalar(select(Item).where(Item.source_id == uuid.UUID(sid)))
    assert item is not None
    events = (
        await db.scalars(
            select(ChangeEvent)
            .where(ChangeEvent.item_id == item.id)
            .order_by(ChangeEvent.occurred_at)
        )
    ).all()
    assert [e.kind for e in events] == ["new_item", "content_changed"]
    assert events[1].severity == "major"  # "in Kraft" in the title (M4 Q4)


async def test_without_any_jurisdiction_the_event_is_international(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    sid = await made_source(admin)
    key, objects = manifest(
        sid,
        uuid.uuid4(),
        [{"url": "https://example.org/z", "text": "plain words " * 50, "title": "A note"}],
    )
    await process_manifest(db, key, loader(objects))
    event = await db.scalar(
        select(Jurisdiction.code).join(ChangeEvent, ChangeEvent.jurisdiction_id == Jurisdiction.id)
    )
    assert event == "INTL"


async def test_source_defaults_win_and_bad_keys_are_refused(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    fr = await db.scalar(select(Jurisdiction.id).where(Jurisdiction.code == "FR"))
    sid = await made_source(admin, default_jurisdiction_codes=["FR"])
    key, objects = manifest(
        sid, uuid.uuid4(), [{"url": "https://example.org/b", "text": BSI, "title": "Regel"}]
    )
    await process_manifest(db, key, loader(objects))
    tags = (await db.scalars(select(ItemJurisdiction.jurisdiction_id))).all()
    assert set(tags) == {fr}  # the source default alone (review finding 12)
    with pytest.raises(ValueError):
        await process_manifest(db, "raw/../../etc/passwd", loader(objects))
    missing = await process_manifest(db, execution.manifest_key(sid, uuid.uuid4()), loader({}))
    assert missing.by_kind == {} and missing.failed == 0


async def test_a_run_with_documents_hands_its_manifest_over(
    admin: httpx.AsyncClient,
    db: AsyncSession,
    processing_handovers: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made = (await admin.post(_api("/sources"), json=rss())).json()
    jid = uuid.UUID(made["job"]["id"])
    from datetime import UTC, datetime

    db.add(CaptureRun(job_id=jid, started_at=datetime.now(UTC)))
    await db.commit()

    async def with_docs(*args: Any) -> Any:
        doc = execution.RawDocument(
            url="https://e.org/a",
            fetched_at=datetime.now(UTC),
            status=200,
            body_ref="raw/x",
            mime="text/html",
        )
        return execution.Outcome("success", documents=[doc])

    monkeypatch.setattr(runs, "run_connector", with_docs)
    assert await runs.execute(db, jid, _factory(_site(""), {})) == "success"
    assert len(processing_handovers) == 1 and processing_handovers[0].startswith(
        f"raw/{made['id']}/runs/"
    )


async def test_the_sweep_hands_over_manifests_never_processed(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """M4 pipeline review finding 3: a marker once processed; the sweep finds the rest."""
    from datetime import UTC, datetime

    from regwatch.processing.pipeline import marker_key, sweep

    made = (await admin.post(_api("/sources"), json=rss())).json()
    run = CaptureRun(
        job_id=uuid.UUID(made["job"]["id"]),
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status="success",
        items_new=1,
    )
    db.add(run)
    await db.commit()
    key, objects = manifest(
        made["id"], run.id, [{"url": "https://example.org/s", "text": BSI, "title": "Regel"}]
    )
    handed: list[str] = []

    async def hand_over(k: str) -> None:
        handed.append(k)

    assert await sweep(db, loader(objects), hand_over) == 1 and handed == [key]

    async def store(k: str, body: bytes) -> None:
        objects[k] = body

    await process_manifest(db, key, loader(objects), store)
    assert marker_key(key) in objects
    assert await sweep(db, loader(objects), hand_over) == 0  # processed: not again


async def test_every_row_of_an_official_api_run_speaks_for_its_host(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Regression: the event kind of the first new row once replaced the source's kind, so
    later rows of a Federal Register run lost the provider's word for their host."""
    from sqlalchemy import update

    from regwatch.capture.models import Source

    sid = await made_source(admin)
    await db.execute(update(Source).where(Source.id == uuid.UUID(sid))
                     .values(kind="api_feed", config={"provider": "federal_register"}))  # fmt: skip
    await db.commit()
    rows = [{"url": f"https://www.federalregister.gov/d/2026-{n}", "text": f"Rule {n}. " + BSI,
             "title": f"R{n}",
             "metadata": {"provider": "federal_register"}} for n in range(3)]  # fmt: skip
    key, objects = manifest(sid, uuid.uuid4(), rows)
    await process_manifest(db, key, loader(objects))
    hosts = (await db.scalars(select(Item.fetched_host).where(
        Item.source_id == uuid.UUID(sid)))).all()  # fmt: skip
    assert hosts == ["federalregister.gov"] * 3


async def test_a_near_duplicate_title_is_kept_for_review_without_an_event(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """M4 dedupe order: a reworded copy of a story, from another source, in the same jurisdiction
    within 7 days; a different story, and the same source's own documents, are not."""
    first, second = await made_source(admin), await made_source(admin)
    title = "BSI veröffentlicht neue Regeln für Betreiber kritischer Anlagen"
    key, objects = manifest(
        first,
        uuid.uuid4(),
        [
            {"url": "https://example.org/a", "text": BSI, "title": title},
            {"url": "https://example.org/a2", "text": "Zweite. " + BSI, "title": title + "."},
        ],
    )
    assert "near_duplicate" not in (await process_manifest(db, key, loader(objects))).by_kind
    rows = [{"url": "https://mirror.example/b", "text": "Kopie. " + BSI, "title": title + "!"},
            {"url": "https://mirror.example/c", "text": "Anders. " + BSI,
             "title": "BSI warnt vor Schwachstellen in Routern"}]  # fmt: skip
    key, objects = manifest(second, uuid.uuid4(), rows)
    counts = await process_manifest(db, key, loader(objects))
    assert counts.by_kind.get("near_duplicate") == 1
    items = {i.canonical_url: i for i in (await db.scalars(select(Item).where(
        Item.source_id.in_([uuid.UUID(first), uuid.UUID(second)])))).all()}  # fmt: skip
    assert items["https://mirror.example/b"].needs_review is True
    assert items["https://mirror.example/c"].needs_review is False
    assert items["https://example.org/a2"].needs_review is False
    events = (await db.scalars(select(ChangeEvent.item_id).where(
        ChangeEvent.item_id.in_([i.id for i in items.values()])))).all()  # fmt: skip
    assert items["https://mirror.example/b"].id not in events and len(set(events)) == 3


async def test_numbered_acts_are_never_near_duplicates(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Re-verification 7, N13 (R21, R22): titles that differ only in an act number or date."""
    feed, eurlex = await made_source(admin), await made_source(admin)
    base = (
        "Commission Implementing Regulation (EU) 2026/{n} of {d} November 2026 "
        "on incident reporting"
    )
    key, objects = manifest(
        feed,
        uuid.uuid4(),
        [
            {
                "url": "https://news.example/guess",
                "text": "Guess. " + BSI,
                "title": base.format(n=1299, d=12),
            }
        ],
    )
    await process_manifest(db, key, loader(objects))
    rows = [{"url": f"https://example.org/{n}", "text": f"{n}. " + BSI,
             "title": base.format(n=n, d=13)} for n in (1300, 1301, 1302)]  # fmt: skip
    key, objects = manifest(eurlex, uuid.uuid4(), rows)
    counts = await process_manifest(db, key, loader(objects))
    assert counts.by_kind.get("new") == 3 and "near_duplicate" not in counts.by_kind


async def test_a_news_feeds_titles_never_silence_an_official_item(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Pipeline re-verification 6, N9 (R17): the same title from a news feed first does not make
    the official source's item a near-duplicate; the reverse does."""
    from sqlalchemy import update

    from regwatch.capture.models import Source

    news, official = await made_source(admin), await made_source(admin)
    await db.execute(update(Source).where(Source.id == uuid.UUID(news))
                     .values(credibility="news"))  # fmt: skip
    await db.commit()
    title = "BSI veröffentlicht neue Regeln für Betreiber kritischer Anlagen"
    for sid, url in ((news, "https://news.example/a"), (official, "https://example.org/a")):
        key, objects = manifest(sid, uuid.uuid4(), [{"url": url, "text": f"{url} " + BSI,
                                                     "title": title}])  # fmt: skip
        await process_manifest(db, key, loader(objects))
    real = await db.scalar(select(Item).where(Item.canonical_url == "https://example.org/a"))
    assert real is not None and real.needs_review is False
    assert await db.scalar(select(ChangeEvent.id).where(ChangeEvent.item_id == real.id))
    key, objects = manifest(
        news,
        uuid.uuid4(),
        [{"url": "https://news.example/b", "text": "again " + BSI, "title": title}],
    )
    await process_manifest(db, key, loader(objects))
    copy = await db.scalar(select(Item).where(Item.canonical_url == "https://news.example/b"))
    assert copy is not None and copy.needs_review is True


async def test_the_sweep_leaves_handed_manifests_alone_and_marks_empty_ones(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """BL-107 (g), N3: a manifest still queued is not handed over each hour; one with no
    document list is marked processed, so never handed over again."""
    from datetime import UTC, datetime, timedelta

    from regwatch.processing.pipeline import HANDED_GRACE, handed_key, marker_key, sweep

    made = (await admin.post(_api("/sources"), json=rss())).json()
    objects: dict[str, bytes] = {}

    async def store(k: str, body: bytes) -> None:
        objects[k] = body

    keys = []
    for rows in ([{"url": "https://example.org/q", "text": BSI}], "not a list"):
        run = CaptureRun(
            job_id=uuid.UUID(made["job"]["id"]),
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            status="success",
            items_new=1,
        )
        db.add(run)
        await db.commit()
        key = execution.manifest_key(made["id"], run.id)
        objects[key] = json.dumps({"documents": rows}).encode()
        keys.append(key)
    handed: list[str] = []

    async def hand_over(k: str) -> None:
        handed.append(k)

    assert await sweep(db, loader(objects), hand_over, store=store) == 2
    assert await sweep(db, loader(objects), hand_over, store=store) == 0  # still queued
    await process_manifest(db, keys[1], loader(objects), store)
    assert marker_key(keys[1]) in objects
    old = (datetime.now(UTC) - HANDED_GRACE - timedelta(minutes=1)).isoformat().encode()
    objects[handed_key(keys[0])] = old
    objects[handed_key(keys[1])] = old
    assert await sweep(db, loader(objects), hand_over, store=store) == 1  # the lost one only
    assert handed[-1] == keys[0]
    objects[handed_key(keys[0])] = b"2026-01-01T00:00:00"  # naive: not trusted, handed again
    assert await sweep(db, loader(objects), hand_over, store=store) == 1


@pytest.mark.parametrize("error", ["soft", "memory"])
async def test_the_time_limit_or_memory_stops_the_manifest_unmarked(
    admin: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch, error: str
) -> None:
    """BL-107 (f) and (h): the worker's soft limit, or memory running out, is not one failed
    row: processing stops, and no marker is written, so the sweep hands it over again."""
    from celery.exceptions import SoftTimeLimitExceeded

    from regwatch.processing import pipeline

    async def boom(*_: Any, **__: Any) -> None:
        raise SoftTimeLimitExceeded() if error == "soft" else MemoryError()

    monkeypatch.setattr(pipeline, "ingest", boom)
    sid = await made_source(admin)
    key, objects = manifest(sid, uuid.uuid4(), [{"url": "https://example.org/z", "text": BSI}])

    async def store(k: str, body: bytes) -> None:
        objects[k] = body

    with pytest.raises((SoftTimeLimitExceeded, MemoryError)):
        await process_manifest(db, key, loader(objects), store)
    assert pipeline.marker_key(key) not in objects
