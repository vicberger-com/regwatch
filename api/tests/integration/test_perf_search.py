"""M5 acceptance 3 and 4 on a 1 million item synthetic dataset (roadmap 5.6).

Not part of ``make test-api``: it takes minutes and needs a few GB of disk in the throwaway
PostgreSQL. Run with
``REGWATCH_PERF=1 uv run pytest -m perf -s tests/integration/test_perf_search.py``.

- Acceptance 3: p95 under 300 ms for search and 150 ms for map activity.
- Acceptance 4: a 50,000 row CSV export streams with memory well under 300 MB.

The data: ``ITEMS`` items with titles and summaries drawn from a fixed vocabulary, seven
languages, one or two jurisdictions and two events each, and term tags.
"""

from __future__ import annotations

import os
import statistics
import time
import tracemalloc
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.db import create_engine, session_factory
from regwatch.search import export, services
from regwatch.search.activity import activity
from regwatch.search.schemas import Query
from tests.integration.test_admin import admin
from tests.integration.test_auth import clear_limits, db_url
from tests.integration.test_capture_runs import db
from tests.integration.test_processing_pipeline import made_source
from tests.integration.test_sources import fixed_dns

pytestmark = [
    pytest.mark.integration,
    pytest.mark.perf,
    pytest.mark.skipif(not os.environ.get("REGWATCH_PERF"), reason="set REGWATCH_PERF=1"),
]
__all__ = ["admin", "clear_limits", "db", "db_url", "fixed_dns"]

ITEMS = int(os.environ.get("REGWATCH_PERF_ITEMS", "1000000"))
EXPLAIN = bool(os.environ.get("REGWATCH_PERF_EXPLAIN"))  # read at import: fixtures reset the env
WORDS = ("regulation directive incident reporting cybersecurity data protection privacy "
         "operator provider authority network security critical infrastructure cloud supply "
         "chain software identity encryption telecoms energy finance health transport guidance "
         "consultation enforcement penalty notice amendment repeal adoption entry force article "
         "annex member state commission council parliament agency risk management obligation "
         "audit certification standard framework control vulnerability disclosure breach "
         "notification deadline review assessment report register sanction fine compliance "
         "Regeln Pflichten Betreiber Anlagen Behörde données règlement autorité protección "
         "datos seguridad proteção dados segurança").split()  # fmt: skip
LANGUAGES = ("en", "en", "en", "de", "fr", "es", "pt", "ja", "zh")


async def populate(db: AsyncSession, source_id: str) -> None:
    vocabulary = "ARRAY[" + ",".join(f"'{w}'" for w in WORDS) + "]"
    languages = "ARRAY[" + ",".join(f"'{lang}'" for lang in LANGUAGES) + "]"
    started = time.monotonic()
    await db.execute(text(f"""
        INSERT INTO item (source_id, canonical_url, url_hash, title, summary, language,
                          published_at, last_changed_at, discovered_at, content_hash, status)
        SELECT :sid, 'https://perf.example/' || g, md5('perf' || g),
               (SELECT string_agg(({vocabulary})[1 + floor(random() * {len(WORDS)})::int], ' ')
                  FROM generate_series(1, 8 + (g % 3))),
               (SELECT string_agg(({vocabulary})[1 + floor(random() * {len(WORDS)})::int], ' ')
                  FROM generate_series(1, 40 + (g % 20))),
               ({languages})[1 + (g % {len(LANGUAGES)})],
               now() - (g % 3650) * interval '1 day', now() - (g % 365) * interval '1 day',
               now() - (g % 365) * interval '1 day', md5('c' || g), 'new'
          FROM generate_series(1, :n) AS g"""), {"sid": source_id, "n": ITEMS})  # fmt: skip
    await db.execute(text("""
        WITH j AS (SELECT array_agg(id ORDER BY code) AS ids, count(*) AS n FROM jurisdiction
                   WHERE kind = 'country' AND active)
        INSERT INTO item_jurisdiction (item_id, jurisdiction_id, assigned_by, confidence)
        SELECT i.id, j.ids[1 + (abs(hashtext(i.id::text)::bigint) % j.n)::int], 'rule', 0.8
          FROM item i, j WHERE i.source_id = :sid"""), {"sid": source_id})  # fmt: skip
    await db.execute(text("""
        INSERT INTO change_event (item_id, jurisdiction_id, kind, severity, occurred_at, summary)
        SELECT ij.item_id, ij.jurisdiction_id, 'new_item',
               (ARRAY['info','info','info','notable','major'])
                 [1 + (abs(hashtext(ij.item_id::text)) % 5)],
               i.last_changed_at, i.title
          FROM item_jurisdiction ij JOIN item i ON i.id = ij.item_id WHERE i.source_id = :sid
        UNION ALL
        SELECT ij.item_id, ij.jurisdiction_id, 'content_changed', 'info',
               i.last_changed_at - interval '30 days', i.title
          FROM item_jurisdiction ij JOIN item i ON i.id = ij.item_id WHERE i.source_id = :sid"""),
        {"sid": source_id})  # fmt: skip
    await db.execute(text("""
        WITH t AS (SELECT array_agg(t.id ORDER BY t.key) AS ids, count(*) AS n FROM term t
                   JOIN facet f ON f.id = t.facet_id WHERE f.key = 'topic')
        INSERT INTO item_term (item_id, term_id, assigned_by, confidence)
        SELECT i.id, t.ids[1 + (abs(hashtext(i.id::text)::bigint) % t.n)::int], 'rule', 0.8
          FROM item i, t WHERE i.source_id = :sid"""), {"sid": source_id})  # fmt: skip
    await db.commit()
    await db.execute(text("ANALYZE"))
    print(f"\npopulated {ITEMS} items in {time.monotonic() - started:.0f} s")


def p95(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=20)[18]


QUERIES: list[dict[str, Any]] = [
    {"q": "incident reporting"}, {"q": "cybersecurity"}, {"q": "data protection authority"},
    {"q": '"critical infrastructure" -cloud'}, {"q": "Anlagen"}, {"q": "fine"},
    {"filters": {"jurisdictions": ["DE", "FR"]}}, {"filters": {"regions": ["150"]}},
    {"q": "regulation", "filters": {"severity": ["major"]}},
    {"filters": {"terms": {"topic": ["cybersecurity"]}}, "sort": "published_desc"},
    {"q": "audit certification standard", "filters": {"languages": ["en"]}},
]  # fmt: skip


async def test_search_map_and_export_at_scale(
    admin: httpx.AsyncClient, db: AsyncSession, db_url: str
) -> None:
    sid = await made_source(admin)
    await populate(db, sid)
    if EXPLAIN:
        from sqlalchemy import func, select
        from sqlalchemy.dialects import postgresql

        from regwatch.search.query import compile_query

        for body in [QUERIES[i] for i in (0, 7, 8, 10)]:
            made = compile_query(Query.model_validate(body))
            assert made.matches is not None
            for name, stmt in (
                ("page", made.ids.limit(50)),
                ("count", select(func.count()).select_from(made.matches.limit(10_001).subquery())),
            ):
                sql = str(stmt.compile(dialect=postgresql.dialect(),
                                       compile_kwargs={"literal_binds": True}))  # fmt: skip
                await db.execute(text("SET statement_timeout = '60s'"))
                plan = (await db.execute(text("EXPLAIN (ANALYZE) " + sql))).scalars().all()
                print(f"\n== {name} {body}\n" + "\n".join(plan[:30]))
            await db.rollback()
    timings: list[float] = []
    for _round in range(5):
        for body in QUERIES:
            services.searches._hits.clear()
            services._facet_cache.clear()
            started = time.monotonic()
            await services.search(db, Query.model_validate(body), uuid.uuid4())
            await db.commit()
            timings.append((time.monotonic() - started) * 1000)
            if _round == 0:
                bare = Query.model_validate({**body, "facet_counts": False, "highlight": False})
                services.searches._hits.clear()
                again = time.monotonic()
                await services.search(db, bare, uuid.uuid4())
                await db.commit()
                print(f"  {timings[-1]:7.0f} ms ({(time.monotonic() - again) * 1000:5.0f} ms"
                      f" without facets) {body}")  # fmt: skip
    print(f"search: p50 {statistics.median(timings):.0f} ms, p95 {p95(timings):.0f} ms")
    maps: list[float] = []
    for days in (7, 30, 90, 365) * 10:
        services.searches._hits.clear()
        started = time.monotonic()
        await activity(db, uuid.uuid4(), days, None, None, None, "country")
        await db.commit()
        maps.append((time.monotonic() - started) * 1000)
    print(f"map: p50 {statistics.median(maps):.0f} ms, p95 {p95(maps):.0f} ms")
    engine = create_engine(db_url, poolclass_null=True)
    try:
        query = Query.model_validate({"filters": {"sources": [sid]}, "sort": "last_changed_desc"})
        tracemalloc.start()
        started, size, lines = time.monotonic(), 0, 0
        async for chunk in export.stream(session_factory(engine), query, export.DEFAULT_COLUMNS):
            size += len(chunk)
            lines += chunk.count(b"\r\n")
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    finally:
        await engine.dispose()
    print(f"export: {lines - 1} rows, {size / 1e6:.1f} MB in {time.monotonic() - started:.0f} s, "
          f"peak Python memory {peak / 1e6:.0f} MB")  # fmt: skip
    assert lines - 1 == min(ITEMS, export.DEFAULT_CAP)
    assert peak < 300e6
    assert p95(timings) < 300, "acceptance 3: search p95"
    assert p95(maps) < 150, "acceptance 3: map activity p95"
