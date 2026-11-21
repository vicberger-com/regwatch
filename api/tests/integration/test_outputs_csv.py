"""Integration: CSV outputs (M8.4; REQ-15): a query or saved view exported into the history."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.outputs import csv_out, tasks
from regwatch.processing.pipeline import process_manifest
from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import clear_limits, db_url
from tests.integration.test_capture_runs import db
from tests.integration.test_outputs import WEEKLY, Gotenberg, gotenberg
from tests.integration.test_processing_pipeline import BSI, loader, made_source, manifest
from tests.integration.test_search import clear_search_rate
from tests.integration.test_search_export import rows
from tests.integration.test_sources import fixed_dns

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "clear_search_rate", "db", "db_url", "fixed_dns",
           "gotenberg"]  # fmt: skip


async def _items(admin: httpx.AsyncClient, db: AsyncSession, count: int = 3) -> str:
    """``count`` items whose titles hold a tag; two start like formulas."""
    sid = await made_source(admin)
    tag = uuid.uuid4().hex[:8]
    titles = [f"=cmd|' /C calc'!A0 {tag}", f"{tag} plain", f"@SUM(1) {tag}"]
    docs = [{"url": f"https://example.org/{tag}/{n}", "text": f"{n}. " + BSI,
             "title": titles[n % 3] + f" {n}", "summary": "=HYPERLINK(\"https://evil.example\")"}
            for n in range(count)]  # fmt: skip
    key, objects = manifest(sid, uuid.uuid4(), docs)
    await process_manifest(db, key, loader(objects))
    return tag


async def _csv(client: httpx.AsyncClient, source: dict[str, Any], **extra: Any) -> httpx.Response:
    return await client.post(_api("/outputs"), json={"kind": "csv", "source": source, **extra})


async def _file(client: httpx.AsyncClient, job_id: str) -> httpx.Response:
    link = urlsplit((await client.get(_api(f"/outputs/{job_id}/artifact"))).headers["location"])
    return await client.get(link.path + "?" + link.query)


async def test_a_query_is_exported_escaped_into_the_history(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg
) -> None:
    tag = await _items(admin, db)
    query = {"q": tag, "sort": "title_asc", "columns": ["title", "summary", "jurisdictions"]}
    made = await _csv(admin, {"query": query})
    assert made.status_code == 202, made.text
    assert made.json()["source_summary"] == "search"
    assert await tasks.run_csv(db, uuid.UUID(made.json()["id"])) == "sent"
    got = await _file(admin, made.json()["id"])
    assert got.status_code == 200 and got.headers["content-type"].startswith("text/csv")
    table = rows(got.content)
    assert table[0] == ["title", "summary", "jurisdictions"] and len(table) == 4
    for line in table[1:]:  # formula injection escaped, as the search export
        assert line[0].startswith(("'=", "'@", tag)) and line[1].startswith("'=")
        assert line[2] == "DE"
    assert gotenberg.seen == []  # no PDF involved


async def test_a_saved_view_is_exported_while_its_owner_can_see_it(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg
) -> None:
    await _items(admin, db)
    view = await admin.post(_api("/views"), json={"name": "Recent", "period_days": 30,
                                                  "filters": {}})  # fmt: skip
    assert view.status_code == 201, view.text
    vid = view.json()["id"]
    made = await _csv(admin, {"saved_view_id": vid})
    assert made.status_code == 202, made.text
    assert await tasks.run_csv(db, uuid.UUID(made.json()["id"])) == "sent"
    table = rows((await _file(admin, made.json()["id"])).content)
    assert table[0][0] == "title" and len(table) >= 4  # the default columns, every item
    sid = (await _csv(admin, {"saved_view_id": vid}, schedule=WEEKLY)).json()["id"]
    assert (await admin.delete(_api(f"/views/{vid}"))).status_code == 204  # detached (5dec58d)
    kept = (await admin.get(_api(f"/outputs/{made.json()['id']}"))).json()
    assert (kept["status"], kept["source_summary"]) == ("sent", "Recent (deleted saved view)")
    stopped = (await admin.get(_api(f"/outputs/{sid}"))).json()
    assert (stopped["status"], stopped["error_class"]) == ("cancelled", "source-deleted")


async def test_csv_needs_its_rights_now_and_a_query_source(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg
) -> None:
    viewer = await _as_new_user(admin, "csvv@example.org", ["viewer"])  # no outputs.csv
    assert (await _csv(viewer, {"query": {}})).status_code == 403
    await viewer.aclose()
    assert (await _csv(admin, {"report_template_key": "source-health"})).status_code == 422
    bad = await _csv(admin, {"query": {"columns": ["password"]}})
    assert bad.status_code == 400 and "unknown column" in bad.text
    other = await _as_new_user(admin, "csvo@example.org", ["analyst"])
    private = (await other.post(_api("/views"), json={"name": "Mine", "filters": {}})).json()
    hidden = await _csv(admin, {"saved_view_id": private["id"]})
    assert hidden.status_code == 409  # not shared with the admin
    await other.aclose()
    # Rights are those at run time: an analyst who loses outputs.csv gets a failed job.
    ana = await _as_new_user(admin, "csva@example.org", ["analyst"])
    aid = (await ana.get(_api("/auth/me"))).json()["id"]
    job = (await _csv(ana, {"query": {}})).json()["id"]
    assert (await admin.patch(_api(f"/admin/users/{aid}"), json={"roles": ["viewer"]})
            ).status_code == 200  # fmt: skip
    assert await tasks.run_csv(db, uuid.UUID(job)) == "failed"
    assert (await admin.get(_api(f"/outputs/{job}"))).json()["error_class"] == "forbidden"
    await ana.aclose()


async def test_a_large_export_stops_between_rows_and_says_so(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    from regwatch.search import export

    tag = await _items(admin, db, count=6)
    monkeypatch.setattr(export, "BATCH", 2)  # three batches of two rows
    made = (await _csv(admin, {"query": {"q": tag, "columns": ["title"]}})).json()["id"]
    real_build = csv_out.build

    async def small(db: AsyncSession, src: csv_out.QuerySource, _: int) -> tuple[bytes, bool]:
        return await real_build(db, src, max_bytes=100)  # the header and one batch

    monkeypatch.setattr(csv_out, "build", small)
    assert await tasks.run_csv(db, uuid.UUID(made)) == "sent"
    table = rows((await _file(admin, made)).content)
    assert table[-1][0].startswith("#export stopped at")
    assert len(table) == 4  # the header, one batch of two whole rows, the note


async def test_a_scheduled_csv_runs_from_the_tick(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg
) -> None:
    tag = await _items(admin, db)
    sid = (await _csv(admin, {"query": {"q": tag}}, schedule=WEEKLY)).json()["id"]
    assert await tasks.tick_once(db, now=datetime.now(UTC) + timedelta(days=8)) == 1
    run = next(j for j in (await admin.get(_api("/outputs"))).json()["items"] if j["id"] != sid)
    assert run["kind"] == "csv"
    assert await tasks.run_csv(db, uuid.UUID(run["id"])) == "sent"
    assert len(rows((await _file(admin, run["id"])).content)) == 4
