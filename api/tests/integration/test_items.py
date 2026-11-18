"""Item reads (M4 interfaces): detail, versions newest first, and diffs."""

from __future__ import annotations

import uuid
from typing import Any

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


@pytest.fixture(autouse=True)
def clear_diffs() -> None:
    from regwatch.processing import services

    services.diffs._hits.clear()


async def three_versions(admin: httpx.AsyncClient, db: AsyncSession, url: str = URL) -> str:
    """An item with versions 1 to 3, each well past the 5 % threshold."""
    sid = await made_source(admin)
    texts = [BSI, BSI.replace("neue Regeln", "geänderte Pflichten"),
             BSI.replace("veröffentlicht neue Regeln", "zieht alles zurück")]  # fmt: skip
    for text in texts:
        key, objects = manifest(sid, uuid.uuid4(), [{"url": url, "text": text,
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
     ("/items/{item}/diff?from=1", 422), ("/items/not-a-uuid", 422),
     ("/items/{item}/diff?from=1&to=2147483648", 422),
     ("/items/{item}/diff?from=99999999999&to=99999999999999", 422)],
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


async def test_tags_reprocessing_and_who_may_change_them(
    admin: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance 5 through the routes: a user's tags survive reprocessing; a removed rule tag
    stays removed (marked incorrect); reprocessing is queued, audited and refused to viewers."""
    from sqlalchemy import select

    from regwatch.core.models import AuditLog
    from regwatch.processing import tasks
    from regwatch.processing.pipeline import reprocess_item
    from tests.integration.test_processing_classify import term

    item_id = await three_versions(admin, db)
    rule = await term(admin, {"keywords": ["Bundesamt"]})
    mine = await term(admin, {"keywords": ["nothing-matches-this"]})
    assert await reprocess_item(db, uuid.UUID(item_id))  # the new rule tags the item
    got = (await admin.get(_api(f"/items/{item_id}"))).json()
    assert {t["term_id"]: t["assigned_by"] for t in got["terms"]}[str(rule)] == "rule"
    body = {"add_term_ids": [str(mine)], "remove_term_ids": [str(rule)],
            "add_jurisdiction_codes": ["fr"], "remove_jurisdiction_codes": ["DE"]}  # fmt: skip
    put = await admin.put(_api(f"/items/{item_id}/tags"), json=body)
    assert put.status_code == 200, put.text
    terms = {t["term_id"]: (t["assigned_by"], t["feedback"]) for t in put.json()["terms"]}
    assert terms == {str(mine): ("user", None), str(rule): ("rule", "incorrect")}
    assert [j["code"] for j in put.json()["jurisdictions"]] == ["FR"]
    assert await reprocess_item(db, uuid.UUID(item_id))  # taxonomy run again
    db.expire_all()
    again = (await admin.get(_api(f"/items/{item_id}"))).json()
    terms = {t["term_id"]: (t["assigned_by"], t["feedback"]) for t in again["terms"]}
    assert terms == {str(mine): ("user", None), str(rule): ("rule", "incorrect")}
    assert "FR" in [j["code"] for j in again["jurisdictions"]]
    judged = await admin.put(
        _api(f"/items/{item_id}/tags"),
        json={"feedback": [{"term_id": str(rule), "feedback": "correct"}]},
    )
    assert {t["term_id"]: t["feedback"] for t in judged.json()["terms"]}[str(rule)] == "correct"
    dropped = await admin.put(_api(f"/items/{item_id}/tags"), json={"remove_term_ids": [str(mine)]})
    assert str(mine) not in {t["term_id"] for t in dropped.json()["terms"]}

    queued: list[str] = []
    monkeypatch.setattr(tasks, "enqueue_reprocess", queued.append)
    assert (await admin.post(_api(f"/items/{item_id}/reprocess"))).status_code == 202
    assert queued == [item_id]
    actions = (await db.scalars(select(AuditLog.action).where(AuditLog.entity_id == item_id))).all()
    assert actions.count("item.tags") == 3 and "item.reprocess" in actions

    def down(_: str) -> None:
        raise ConnectionError("broker down")

    monkeypatch.setattr(tasks, "enqueue_reprocess", down)
    assert (await admin.post(_api(f"/items/{item_id}/reprocess"))).status_code == 503
    viewer = await _as_new_user(admin, f"viewer-{uuid.uuid4().hex[:8]}@example.org", ["viewer"])
    try:
        assert (await viewer.post(_api(f"/items/{item_id}/reprocess"))).status_code == 403
        assert (await viewer.put(_api(f"/items/{item_id}/tags"), json={})).status_code == 403
    finally:
        await viewer.aclose()
    missing = await admin.post(_api(f"/items/{uuid.uuid4()}/reprocess"))
    assert missing.status_code == 404


@pytest.mark.parametrize(
    "body",
    [{"add_term_ids": ["00000000-0000-7000-8000-000000000009"]},
     {"add_jurisdiction_codes": ["XX"]}, {"remove_jurisdiction_codes": ["Z" * 17]},
     {"add_jurisdiction_codes": ["DE"], "remove_jurisdiction_codes": ["de"]},
     {"feedback": [{"term_id": "00000000-0000-7000-8000-000000000009", "feedback": "correct"}]},
     {"feedback": [{"term_id": "00000000-0000-7000-8000-000000000009", "feedback": "maybe"}]},
     {"add_jurisdiction_codes": [f"C{n}" for n in range(101)]},
     {"feedback": [{"term_id": "00000000-0000-7000-8000-000000000009"}]},
     {"feedback": [{"feedback": "correct"}]},
     {"remove_term_ids": ["00000000-0000-7000-8000-000000000009"],
      "feedback": [{"term_id": "00000000-0000-7000-8000-000000000009", "feedback": "correct"}]},
     {"feedback": [{"term_id": "00000000-0000-7000-8000-000000000009", "feedback": "correct"},
                   {"term_id": "00000000-0000-7000-8000-000000000009", "feedback": "incorrect"}]},
     {"remove_jurisdiction_codes": ["QQ"]}],
)  # fmt: skip
async def test_tag_changes_that_are_refused(
    admin: httpx.AsyncClient, db: AsyncSession, body: dict[str, Any]
) -> None:
    item_id = await three_versions(admin, db)
    got = await admin.put(_api(f"/items/{item_id}/tags"), json=body)
    assert got.status_code == 422, got.text
    still = (await admin.get(_api(f"/items/{item_id}"))).json()
    assert [j["code"] for j in still["jurisdictions"]] == ["DE"]


async def test_the_audit_records_what_a_tag_change_did(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Routes review finding 2: origins and verdicts before and after; no-op not audited."""
    from sqlalchemy import select

    from regwatch.core.models import AuditLog
    from regwatch.processing.pipeline import reprocess_item
    from tests.integration.test_processing_classify import term

    item_id = await three_versions(admin, db)
    rule = await term(admin, {"keywords": ["Bundesamt"]})
    await reprocess_item(db, uuid.UUID(item_id))
    assert (await admin.put(_api(f"/items/{item_id}/tags"), json={})).status_code == 200
    put = await admin.put(_api(f"/items/{item_id}/tags"), json={"remove_term_ids": [str(rule)]})
    assert put.status_code == 200
    rows = (
        await db.scalars(
            select(AuditLog).where(AuditLog.entity_id == item_id, AuditLog.action == "item.tags")
        )
    ).all()
    assert len(rows) == 1  # the empty request changed nothing
    assert rows[0].before["terms"][str(rule)] == ["rule", None]
    assert rows[0].after["terms"][str(rule)] == ["rule", "incorrect"]


async def test_computed_diffs_are_rate_limited_per_user(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Finding 3: distant versions cost CPU; consecutive ones are stored and never limited."""
    from regwatch.processing import services

    item_id = await three_versions(admin, db)
    for _ in range(services.DIFF_RATE):
        assert (await admin.get(_api(f"/items/{item_id}/diff?from=1&to=3"))).status_code == 200
    refused = await admin.get(_api(f"/items/{item_id}/diff?from=1&to=3"))
    assert refused.status_code == 429 and int(refused.headers["retry-after"]) >= 1
    assert (await admin.get(_api(f"/items/{item_id}/diff?from=2&to=3"))).status_code == 200


async def test_a_failed_queue_leaves_no_audit_and_severity_is_the_highest(
    admin: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Findings 8 and 9."""
    from sqlalchemy import select, update

    from regwatch.core.models import AuditLog
    from regwatch.processing import tasks
    from regwatch.processing.models import ChangeEvent

    item_id = await three_versions(admin, db)

    def down(_: str) -> None:
        raise ConnectionError("broker down")

    monkeypatch.setattr(tasks, "enqueue_reprocess", down)
    assert (await admin.post(_api(f"/items/{item_id}/reprocess"))).status_code == 503
    audited = await db.scalar(
        select(AuditLog.id).where(
            AuditLog.entity_id == item_id, AuditLog.action == "item.reprocess"
        )
    )
    assert audited is None
    first = await db.scalar(
        select(ChangeEvent.id).where(
            ChangeEvent.item_id == uuid.UUID(item_id), ChangeEvent.kind == "new_item"
        )
    )
    await db.execute(update(ChangeEvent).where(ChangeEvent.id == first).values(severity="major"))
    await db.commit()
    assert (await admin.get(_api(f"/items/{item_id}"))).json()["severity"] == "major"


async def test_an_inactive_jurisdiction_cannot_be_added(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Finding 7."""
    from sqlalchemy import update

    from regwatch.taxonomy.models import Jurisdiction

    item_id = await three_versions(admin, db)
    await db.execute(update(Jurisdiction).where(Jurisdiction.code == "FR").values(active=False))
    await db.commit()
    try:
        got = await admin.put(_api(f"/items/{item_id}/tags"),
                              json={"add_jurisdiction_codes": ["fr"]})  # fmt: skip
        assert got.status_code == 422
        assert got.json()["errors"][0]["field"] == "add_jurisdiction_codes"
    finally:
        await db.execute(update(Jurisdiction).where(Jurisdiction.code == "FR").values(active=True))
        await db.commit()


async def test_a_jurisdiction_taken_over_by_a_user_is_audited(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Re-verification 1, finding 2's gap: the origin of each jurisdiction is audited."""
    from sqlalchemy import select

    from regwatch.core.models import AuditLog

    item_id = await three_versions(admin, db)  # DE, from the gazetteer
    assert (
        await admin.put(_api(f"/items/{item_id}/tags"), json={"add_jurisdiction_codes": ["de"]})
    ).status_code == 200
    row = await db.scalar(
        select(AuditLog).where(AuditLog.entity_id == item_id, AuditLog.action == "item.tags")
    )
    assert row is not None
    assert (row.before["jurisdictions"], row.after["jurisdictions"]) == (
        {"DE": "rule"}, {"DE": "user"})  # fmt: skip


async def test_computed_diffs_are_bounded_across_users(
    admin: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-verification N1: past DIFF_PENDING waiting or running, a computed diff is a 503; the
    per-user rate is checked before the database (even an unknown item counts)."""
    from regwatch.processing import services

    item_id = await three_versions(admin, db)
    monkeypatch.setattr(services, "_pending", services.DIFF_PENDING)
    busy = await admin.get(_api(f"/items/{item_id}/diff?from=1&to=3"))
    assert busy.status_code == 503 and busy.headers["retry-after"]
    assert (await admin.get(_api(f"/items/{item_id}/diff?from=2&to=3"))).status_code == 200
    monkeypatch.setattr(services, "_pending", 0)
    for _ in range(services.DIFF_RATE):
        await admin.get(_api(f"/items/{uuid.uuid4()}/diff?from=1&to=3"))
    assert (await admin.get(_api(f"/items/{item_id}/diff?from=1&to=3"))).status_code == 429
    assert services._pending == 0


async def test_two_tag_changes_adding_one_term_do_not_block(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Re-verification N2: the term is locked FOR KEY SHARE, which two changes can share."""
    import asyncio

    from tests.integration.test_processing_classify import term

    first = await three_versions(admin, db)
    second = await three_versions(admin, db, URL + "-2")
    shared = await term(admin, {"keywords": ["nothing-matches-this"]})
    body = {"add_term_ids": [str(shared)]}
    got = await asyncio.wait_for(asyncio.gather(
        admin.put(_api(f"/items/{first}/tags"), json=body),
        admin.put(_api(f"/items/{second}/tags"), json=body)), timeout=20)  # fmt: skip
    assert [r.status_code for r in got] == [200, 200]
