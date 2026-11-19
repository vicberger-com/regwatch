"""POST /search/export.csv (M5 acceptance 4; Q2: metadata and summary; formula injection)."""

from __future__ import annotations

import csv
import io
import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.processing.pipeline import process_manifest
from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import clear_limits, db_url
from tests.integration.test_capture_runs import db
from tests.integration.test_processing_pipeline import BSI, loader, made_source, manifest
from tests.integration.test_search import clear_search_rate
from tests.integration.test_sources import fixed_dns

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "clear_search_rate", "db", "db_url", "fixed_dns"]


def rows(body: bytes) -> list[list[str]]:
    assert body.startswith("﻿".encode())  # UTF-8 BOM
    return list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))


async def test_an_export_is_metadata_escaped_and_in_search_order(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    sid = await made_source(admin)
    tag = uuid.uuid4().hex[:8]
    docs = [{"url": f"https://example.org/{tag}/{n}", "text": f"{n}. " + BSI,
             "title": title, "summary": "=HYPERLINK(\"https://evil.example\")"}
            for n, title in enumerate([f"=cmd|' /C calc'!A0 {tag}", f"{tag} plain",
                                       f"@SUM(1) {tag}"])]  # fmt: skip
    key, objects = manifest(sid, uuid.uuid4(), docs)
    await process_manifest(db, key, loader(objects))
    got = await admin.post(
        _api("/search/export.csv"),
        json={"q": tag, "sort": "title_asc", "columns": ["title", "summary", "jurisdictions"]},
    )
    assert got.status_code == 200, got.text
    assert got.headers["content-type"].startswith("text/csv")
    assert "attachment" in got.headers["content-disposition"]
    table = rows(got.content)
    assert table[0] == ["title", "summary", "jurisdictions"] and len(table) == 4
    for line in table[1:]:
        assert line[0].startswith(("'=", "'@", tag)) and line[1].startswith("'=")
        assert line[2] == "DE"
    assert {line[0] for line in table[1:]} == {f"'=cmd|' /C calc'!A0 {tag}", f"{tag} plain",
                                              f"'@SUM(1) {tag}"}  # fmt: skip


async def test_the_default_columns_carry_no_full_text(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Q2: metadata plus summary."""
    got = await admin.post(_api("/search/export.csv"), json={"q": "nothing-matches-this"})
    header = rows(got.content)[0]
    assert "summary" in header and "content_text" not in header and len(rows(got.content)) == 1


@pytest.mark.parametrize("body", [{"columns": ["content_text"]}, {"columns": ["title", "title"]},
                                  {"filters": {"terms": {"no-such-facet": ["x"]}}},
                                  {"filters": {"languages": ["en"] * 51}}])  # fmt: skip
async def test_bad_exports_are_400s_before_any_byte(
    admin: httpx.AsyncClient, body: dict[str, object]
) -> None:
    got = await admin.post(_api("/search/export.csv"), json=body)
    assert got.status_code == 400 and got.headers["content-type"].startswith(
        "application/problem+json")  # fmt: skip


async def test_a_viewer_cannot_export(admin: httpx.AsyncClient) -> None:
    viewer = await _as_new_user(admin, f"viewer-{uuid.uuid4().hex[:8]}@example.org", ["viewer"])
    try:
        assert (await viewer.post(_api("/search/export.csv"), json={})).status_code == 403
    finally:
        await viewer.aclose()


async def test_exports_are_rate_limited_audited_and_one_at_a_time(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Slice 2 S2 (8.2: outputs 20 an hour per user, audited) and S1 (one running per user)."""
    from sqlalchemy import func, select

    from regwatch.core.models import AuditLog
    from regwatch.search import export

    export.outputs._hits.clear()
    export._running.clear()
    before = await db.scalar(select(func.count()).select_from(AuditLog)
                             .where(AuditLog.action == "search.export"))  # fmt: skip
    got = await admin.post(_api("/search/export.csv"), json={"q": "x"})
    assert got.status_code == 200 and got.headers["x-regwatch-order"] == "last_changed_desc"
    after = await db.scalar(select(func.count()).select_from(AuditLog)
                            .where(AuditLog.action == "search.export"))  # fmt: skip
    assert after == (before or 0) + 1 and export._running == {}
    export._running["held"] = []
    me = next(iter(export.outputs._hits))
    export._running[me] = [__import__("time").monotonic()]
    busy = await admin.post(_api("/search/export.csv"), json={"q": "x"})
    assert busy.status_code == 429  # one at a time per user
    export._running.clear()
    for _ in range(export.OUTPUT_RATE - 1):
        assert (await admin.post(_api("/search/export.csv"), json={})).status_code == 200
    assert (await admin.post(_api("/search/export.csv"), json={})).status_code == 429
    export.outputs._hits.clear()


async def test_no_connection_is_held_while_the_client_reads(
    admin: httpx.AsyncClient, db: AsyncSession, db_url: str
) -> None:
    """S1: between batches the export holds no transaction."""
    from sqlalchemy import func, select, text

    from regwatch.core.db import create_engine, session_factory
    from regwatch.search import export
    from regwatch.search.schemas import Query

    sid = await made_source(admin)
    docs = [{"url": f"https://example.org/hold/{n}", "text": f"{n}. " + BSI, "title": f"T {n}"}
            for n in range(3)]  # fmt: skip
    key, objects = manifest(sid, uuid.uuid4(), docs)
    await process_manifest(db, key, loader(objects))
    engine = create_engine(db_url, poolclass_null=True)
    monkey = export.BATCH
    export.BATCH = 1
    try:
        stream = export.stream(session_factory(engine), Query.model_validate(
            {"filters": {"sources": [sid]}}), ("title",))  # fmt: skip
        assert (await anext(stream)).startswith("﻿".encode())
        await anext(stream)  # the first batch; the client now pauses
        idle = await db.scalar(select(func.count()).select_from(text("pg_stat_activity")).where(
            text("state = 'idle in transaction' AND pid <> pg_backend_pid()")))  # fmt: skip
        assert idle == 0
        rest = [chunk async for chunk in stream]
        assert len(rest) == 2
    finally:
        export.BATCH = monkey
        await engine.dispose()


def test_formula_starts_hidden_behind_spaces_or_marks_are_escaped() -> None:
    """S8."""
    from regwatch.search.export import cell

    for value in (" =1+1", "​=1", "﻿=1", "＝1+1", " @SUM(1)", "plain"):
        assert cell(value).startswith("'") == (value != "plain"), value
