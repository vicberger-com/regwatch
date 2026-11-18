"""Items and versions from manifest rows (M4 acceptance 1; dedupe order; threshold)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
