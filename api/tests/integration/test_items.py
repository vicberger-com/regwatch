"""Item reads (M4 interfaces): detail, versions newest first, and diffs."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.processing.pipeline import process_manifest
from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import ORIGIN, clear_limits, db_url
from tests.integration.test_capture_runs import db
from tests.integration.test_processing_pipeline import BSI, loader, made_source, manifest
from tests.integration.test_sources import fixed_dns

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db", "db_url", "fixed_dns"]  # shared fixtures

URL = "https://example.org/leitlinie"


async def three_versions(admin: httpx.AsyncClient, db: AsyncSession) -> str:
    """An item with versions 1 to 3, each well past the 5 % threshold."""
    sid = await made_source(admin)
    texts = [BSI, BSI.replace("neue Regeln", "geänderte Pflichten"),
             BSI.replace("veröffentlicht neue Regeln", "zieht alles zurück")]  # fmt: skip
    for text in texts:
        key, objects = manifest(sid, uuid.uuid4(), [{"url": URL, "text": text,
                                                     "title": "Neue Leitlinie"}])  # fmt: skip
        await process_manifest(db, key, loader(objects))
    found = await admin.get(_api(f"/sources/{sid}"))
    assert found.status_code == 200
    from sqlalchemy import select

    from regwatch.processing.models import Item

    item_id = await db.scalar(select(Item.id).where(Item.source_id == uuid.UUID(sid)))
    assert item_id is not None
    return str(item_id)


async def test_a_viewer_reads_an_item_its_versions_and_diffs(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    item_id = await three_versions(admin, db)
    viewer = await _as_new_user(admin, f"viewer-{uuid.uuid4().hex[:8]}@example.org", ["viewer"])
    try:
        got = await viewer.get(_api(f"/items/{item_id}"))
        assert got.status_code == 200, got.text
        item = got.json()
        assert item["current_version_no"] == 3 and item["status"] == "updated"
        assert "zieht alles zurück" in item["content_text"]
        assert [j["code"] for j in item["jurisdictions"]] == ["DE"]
        assert [e["kind"] for e in item["change_events"]] == [
            "content_changed", "content_changed", "new_item"]  # fmt: skip
        assert item["severity"] in ("info", "notable") and item["source_name"]
        versions = (await viewer.get(_api(f"/items/{item_id}/versions"))).json()
        assert [v["version_no"] for v in versions] == [3, 2, 1]
        assert versions[2]["changed_pct"] is None and versions[0]["changed_pct"] > 5
        stored = (await viewer.get(_api(f"/items/{item_id}/diff?from=2&to=3"))).json()
        assert stored["to_version"] == 3 and "+Das Bundesamt" in stored["unified_diff"]
        span = (await viewer.get(_api(f"/items/{item_id}/diff?from=1&to=3"))).json()
        assert span["from_version"] == 1 and span["changed_pct"] > 5
        assert "-Das Bundesamt" in span["unified_diff"] and "neue Regeln" in span["unified_diff"]
    finally:
        await viewer.aclose()


@pytest.mark.parametrize(
    ("path", "status"),
    [("/items/{missing}", 404), ("/items/{missing}/versions", 404),
     ("/items/{item}/diff?from=1&to=9", 404), ("/items/{item}/diff?from=3&to=2", 422),
     ("/items/{item}/diff?from=0&to=1", 422), ("/items/{item}/diff?from=x&to=1", 422),
     ("/items/{item}/diff?from=1", 422), ("/items/not-a-uuid", 422)],
)  # fmt: skip
async def test_reads_refuse_what_is_not_there(
    admin: httpx.AsyncClient, db: AsyncSession, path: str, status: int
) -> None:
    item_id = await three_versions(admin, db)
    got = await admin.get(_api(path.format(missing=uuid.uuid4(), item=item_id)))
    assert got.status_code == status, got.text
    assert got.headers["content-type"].startswith("application/problem+json")


async def test_an_anonymous_caller_reads_nothing(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    item_id = await three_versions(admin, db)
    anonymous = httpx.AsyncClient(transport=admin._transport, base_url="https://localhost",
                                  headers=ORIGIN)  # fmt: skip
    async with anonymous:
        for path in ("", "/versions", "/diff?from=1&to=2"):
            assert (await anonymous.get(_api(f"/items/{item_id}{path}"))).status_code == 401
