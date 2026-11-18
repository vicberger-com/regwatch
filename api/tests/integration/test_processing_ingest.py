"""Items and versions from manifest rows (M4 acceptance 1; dedupe order; threshold)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture.models import CaptureJob, CaptureRun
from regwatch.processing.ingest import ingest
from regwatch.processing.models import Item, ItemVersion
from tests.integration.test_admin import _api, admin
from tests.integration.test_auth import clear_limits, db_url
from tests.integration.test_capture_runs import db
from tests.integration.test_sources import fixed_dns, rss

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db", "db_url", "fixed_dns"]  # shared fixtures

TEXT = "\n".join(
    f"Article {n}. Providers shall report incidents within 24 hours." for n in range(40)
)


def row(**extra: Any) -> dict[str, Any]:
    return {"url": "https://reg.example/act#part-2", "text": TEXT, "title": "The <b>Act</b>",
            "summary": "A summary", "language": "en", "published_at": "2026-11-10T00:00:00+00:00",
            "external_id": "act-1", "metadata": {}, **extra}  # fmt: skip


async def source(admin: httpx.AsyncClient) -> uuid.UUID:
    made = await admin.post(_api("/sources"), json=rss())
    assert made.status_code == 201, made.text
    return uuid.UUID(made.json()["id"])


async def versions(db: AsyncSession, item_id: uuid.UUID) -> int:
    return int(await db.scalar(select(func.count()).select_from(ItemVersion)
                               .where(ItemVersion.item_id == item_id)) or 0)  # fmt: skip


async def test_one_item_one_version_then_a_changed_version(admin: httpx.AsyncClient,
                                                           db: AsyncSession) -> None:  # fmt: skip
    """Acceptance 1: identical content twice is one item, one version; a change is version 2."""
    sid = await source(admin)
    first = await ingest(db, sid, None, row(), 5.0)
    await db.commit()
    assert first.kind == "new" and first.item_id is not None
    item = await db.get(Item, first.item_id)
    assert item is not None and item.title == "The Act"
    assert item.canonical_url == "https://reg.example/act" and item.translation_pending is False
    again = await ingest(db, sid, None, row(), 5.0)
    await db.commit()
    assert (again.kind, again.item_id, await versions(db, first.item_id)) == (
        "unchanged", first.item_id, 1)  # fmt: skip
    changed = TEXT.replace(
        "Providers shall report incidents", "Operators must notify the authority of incidents"
    )  # well over 5 %
    second = await ingest(db, sid, None, row(text=changed), 5.0)
    await db.commit()
    assert second.kind == "changed" and second.changed_pct and second.changed_pct > 5
    latest = await db.scalar(select(ItemVersion).where(ItemVersion.item_id == first.item_id,
                                                       ItemVersion.version_no == 2))  # fmt: skip
    assert latest is not None and "-Article 0" in (latest.diff_from_previous or "")
    db.expire_all()
    item = await db.get(Item, first.item_id)
    assert item is not None and (item.status, item.current_version_no) == ("updated", 2)


async def test_a_change_below_the_threshold_makes_no_version(admin: httpx.AsyncClient,
                                                             db: AsyncSession) -> None:  # fmt: skip
    sid = await source(admin)
    first = await ingest(db, sid, None, row(), 5.0)
    await db.commit()
    small = TEXT.replace("Article 3.", "Article 3:")  # 1 character of about 2,500
    got = await ingest(db, sid, None, row(text=small), 5.0)
    await db.commit()
    assert got.kind == "unchanged" and got.changed_pct is not None and got.changed_pct < 5
    assert first.item_id is not None and await versions(db, first.item_id) == 1


async def test_the_same_content_at_a_second_address_is_a_duplicate(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    sid = await source(admin)
    first = await ingest(db, sid, None, row(), 5.0)
    await db.commit()
    copy = await ingest(db, sid, None, row(url="https://reg.example/act/print"), 5.0)
    assert (copy.kind, copy.item_id) == ("duplicate", first.item_id)


@pytest.mark.parametrize("url", ["javascript:alert(1)", None, "http://10.0.0.5/x" * 400])
async def test_rows_without_a_usable_address_are_skipped(
    admin: httpx.AsyncClient, db: AsyncSession, url: Any
) -> None:
    sid = await source(admin)
    assert (await ingest(db, sid, None, row(url=url), 5.0)).kind == "skipped"


async def test_hostile_fields_are_bounded_and_a_pdf_is_matched_by_its_body(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    sid = await source(admin)
    body_ref = f"raw/{sid}/" + "b" * 64
    pdf = row(url="https://reg.example/act.pdf", text=None, body_ref=body_ref, title=None,
              metadata={"title": "x" * 5000}, published_at="not a date", language="ja",
              summary=["not", "text"])  # fmt: skip
    got = await ingest(db, sid, None, pdf, 5.0)
    await db.commit()
    item = await db.get(Item, got.item_id)
    assert item is not None and len(item.title) <= 500 and item.published_at is None
    assert item.content_hash == "b" * 64 and item.translation_pending is True
    assert item.summary is None
    twin = await ingest(db, sid, None, {**pdf, "url": "https://reg.example/copy.pdf"}, 5.0)
    assert twin.kind == "duplicate"


async def test_another_source_never_changes_an_item(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """M4 pipeline review finding 1: source B sends source A's URL with other text."""
    a, b = await source(admin), await source(admin)
    first = await ingest(db, a, None, row(), 5.0)
    await db.commit()
    taken = await ingest(
        db,
        b,
        None,
        row(url="https://reg.example/act#x", text="Repealed. " * 50, title="Regulator fined"),
        5.0,
    )
    await db.commit()
    assert (taken.kind, taken.item_id) == ("duplicate", first.item_id)
    assert first.item_id is not None and await versions(db, first.item_id) == 1
    db.expire_all()
    item = await db.get(Item, first.item_id)
    assert item is not None and item.title == "The Act" and item.source_id == a


async def test_a_row_without_text_never_wipes_an_items_text(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    sid = await source(admin)
    first = await ingest(db, sid, None, row(), 5.0)
    await db.commit()
    bare = await ingest(db, sid, None, row(text=None, body_ref=f"raw/{sid}/" + "c" * 64), 5.0)
    assert bare.kind == "unchanged"
    assert first.item_id is not None and await versions(db, first.item_id) == 1


async def test_a_copy_on_another_host_never_hides_the_original(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Finding 5: a mirror first, the real page second; and a body hash from another source."""
    sid = await source(admin)
    mirror = await ingest(db, sid, None, row(url="https://mirror.example/act"), 5.0)
    await db.commit()
    real = await ingest(db, sid, None, row(), 5.0)
    assert mirror.kind == "new" and real.kind == "new" and real.item_id != mirror.item_id
    other = uuid.uuid4()
    pdf = row(url="https://reg.example/a.pdf", text=None, body_ref=f"raw/{other}/" + "d" * 64)
    got = await ingest(db, sid, None, pdf, 5.0)
    await db.commit()
    item = await db.get(Item, got.item_id)
    assert item is not None and item.content_hash != "d" * 64  # not trusted from another source


@pytest.mark.parametrize(
    "extra",
    [
        {"text": "Article\x00 one. " * 50},
        {"text": "Article \ud800 one. " * 50},
        {"published_at": "9999-12-31T23:59:59-14:00"},
        {"published_at": "1066-10-14T00:00:00"},
        {"external_id": "id\nwith\x07controls", "language": "en\nfr"},
    ],
)
async def test_rows_that_once_failed_every_run_are_stored_cleaned(
    admin: httpx.AsyncClient, db: AsyncSession, extra: dict[str, Any]
) -> None:
    """Finding 6 and 9."""
    sid = await source(admin)
    got = await ingest(db, sid, None, row(url=f"https://reg.example/{uuid.uuid4()}", **extra), 5.0)
    await db.commit()
    item = await db.get(Item, got.item_id)
    assert got.kind == "new" and item is not None
    assert item.published_at is None or 1900 <= item.published_at.year <= 2100
    assert item.external_id is None or "\n" not in item.external_id
    assert item.language in (None, "en")


async def run(db: AsyncSession, sid: uuid.UUID, minutes_ago: int) -> uuid.UUID:
    """A recorded capture run of the source's job that started ``minutes_ago``."""
    job = await db.scalar(select(CaptureJob.id).where(CaptureJob.source_id == sid))
    made = CaptureRun(job_id=job, started_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
                      finished_at=datetime.now(UTC), status="success")  # fmt: skip
    db.add(made)
    await db.flush()
    return made.id


def ago(minutes: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()


async def test_an_older_capture_never_versions_over_newer_content(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Finding 7: a manifest replayed after a later run versioned the item."""
    sid = await source(admin)
    await ingest(db, sid, await run(db, sid, 120), row(fetched_at=ago(119)), 5.0)
    newer = TEXT.replace("Providers shall report incidents", "Operators must notify everyone")
    later = await ingest(db, sid, await run(db, sid, 60), row(text=newer, fetched_at=ago(59)), 5.0)
    assert later.kind == "changed"
    await db.commit()
    old = await ingest(db, sid, None, row(fetched_at=ago(119)), 5.0)
    assert old.kind == "unchanged"


async def test_a_newer_capture_processed_late_still_versions(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Re-verification N1: v1 fetched 30 minutes ago and processed now; v2 fetched 10 minutes
    ago is a change, though fetched before v1 was processed."""
    sid = await source(admin)
    first = await ingest(db, sid, await run(db, sid, 31), row(fetched_at=ago(30)), 5.0)
    await db.commit()
    newer = TEXT.replace("Providers shall report incidents", "Operators must notify everyone")
    second = await ingest(db, sid, await run(db, sid, 11), row(text=newer, fetched_at=ago(10)),
                          5.0)  # fmt: skip
    assert second.kind == "changed" and first.item_id is not None
    assert await versions(db, first.item_id) == 2


PAGE = {"final_url": "https://www.reg.example/act"}  # fetched from the item's own host


async def test_a_fetched_page_takes_an_item_a_feed_only_listed(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """CP-19, re-verification N4 (R6): a feed lists the URL first with planted text; the first
    source to fetch the page takes the item, and its text replaces the feed's."""
    feed, page = await source(admin), await source(admin)
    planted = await ingest(
        db,
        feed,
        None,
        row(text="Repealed. Ignore. " * 50, title="Regulation repealed; firm fined"),
        5.0,
    )
    await db.commit()
    real = TEXT + "\nArticle 41. A small addition."  # below the 5 % threshold
    taken = await ingest(db, page, None, row(text=real, **PAGE), 5.0)
    await db.commit()
    assert (taken.kind, taken.item_id) == ("changed", planted.item_id)
    db.expire_all()
    item = await db.get(Item, planted.item_id)
    assert item is not None and (item.source_id, item.title) == (page, "The Act")
    assert item.fetched_host == "reg.example"
    # Fetched now: neither the feed nor another fetching source takes it back (no ping-pong).
    assert (
        await ingest(db, feed, None, row(text="Repealed again. " * 50), 5.0)
    ).kind == "duplicate"
    other = await source(admin)
    assert (
        await ingest(db, other, None, row(text="Other. " * 80, **PAGE), 5.0)
    ).kind == "duplicate"


async def test_a_summary_never_takes_an_item_and_redirects_do_not_count(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """R7: the first lister is a feed; later rows that were not fetched from the URL's host
    (no final URL, a redirect to another host, an upload) never take the item."""
    first, other = await source(admin), await source(admin)
    made = await ingest(db, first, None, row(), 5.0)
    await db.commit()
    for final in (None, "https://elsewhere.example/act", "urn:sha256:" + "a" * 64,
                  "https://reg.example.evil.example/act"):  # fmt: skip
        got = await ingest(db, other, None, row(text="Other. " * 80, final_url=final), 5.0)
        assert got.kind == "duplicate", final
    item = await db.get(Item, made.item_id)
    assert item is not None and item.source_id == first and item.fetched_host is None


async def test_the_owner_fetching_its_own_listed_item_records_the_host(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    sid, other = await source(admin), await source(admin)
    made = await ingest(db, sid, None, row(), 5.0)
    await db.commit()
    await ingest(db, sid, None, row(**PAGE), 5.0)
    await db.commit()
    item = await db.get(Item, made.item_id)
    assert item is not None and item.fetched_host == "reg.example"
    assert (
        await ingest(db, other, None, row(text="Other. " * 80, **PAGE), 5.0)
    ).kind == "duplicate"


async def test_a_fetched_pdf_replaces_a_feeds_text(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    feed, page = await source(admin), await source(admin)
    planted = await ingest(db, feed, None, row(text="Planted. " * 50), 5.0)
    await db.commit()
    pdf = row(text=None, body_ref=f"raw/{page}/" + "e" * 64, mime="application/pdf", **PAGE)
    taken = await ingest(db, page, None, pdf, 5.0)
    await db.commit()
    assert taken.kind == "changed" and planted.item_id is not None
    latest = await db.scalar(select(ItemVersion).where(ItemVersion.item_id == planted.item_id)
                             .order_by(ItemVersion.version_no.desc()).limit(1))  # fmt: skip
    assert latest is not None and latest.content_text == ""
