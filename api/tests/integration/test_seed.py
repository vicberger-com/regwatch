"""Integration: ``regwatch-seed`` loads api/seed and is idempotent (#28 acceptance 3)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from regwatch.core import seed
from tests.integration.conftest import Postgres, upgrade

pytestmark = pytest.mark.integration

SEED_DIR = Path(__file__).resolve().parents[2] / "seed"
TABLES = (
    "permission", "role", "role_permission", "setting", "feature_flag", "jurisdiction", "facet",
    "term", "source", "capture_job",
)  # fmt: skip
EXPECTED = {
    "permission": 23,
    "role": 4,
    "role_permission": 23 + 15 + 10 + 4,
    "setting": 40,
    "feature_flag": 8,
    "jurisdiction": 250 + 5,
    "facet": 6,
    "term": 14 + 10 + 9 + 9 + 6 + 22,
    "catalogue_source": 4,
}


def snapshot(pg: Postgres, db: str) -> dict[str, str]:
    """Every row of every seeded table, all columns, in a stable order."""
    query = "SELECT json_agg(x ORDER BY x::text) FROM {} x;"
    return {t: pg.psql(db, query.format(t)) for t in TABLES}


def test_seed_twice_changes_nothing(postgres: Postgres, empty_db: str) -> None:
    url = postgres.url(empty_db)
    upgrade(url)
    assert asyncio.run(seed.run(SEED_DIR, url)) == EXPECTED
    first = snapshot(postgres, empty_db)
    assert asyncio.run(seed.run(SEED_DIR, url)) == dict.fromkeys(EXPECTED, 0)
    assert snapshot(postgres, empty_db) == first


def test_seed_keeps_administrator_edits(postgres: Postgres, empty_db: str) -> None:
    url = postgres.url(empty_db)
    upgrade(url)
    asyncio.run(seed.run(SEED_DIR, url))
    postgres.psql(
        empty_db,
        "UPDATE setting SET value = '\"Acme monitor\"' WHERE key = 'general.site_title';"
        "UPDATE feature_flag SET enabled = true WHERE key = 'auth.oidc';"
        "UPDATE permission SET description = 'stale' WHERE key = 'items.read';"
        "UPDATE source SET name = 'Renamed' WHERE catalogue_key = 'gb-legislation-it';",
    )
    counts = asyncio.run(seed.run(SEED_DIR, url))
    assert counts["permission"] == 1  # the registry owns permission text
    assert counts["catalogue_source"] == 0
    assert (
        postgres.psql(
            empty_db, "SELECT name FROM source WHERE catalogue_key = 'gb-legislation-it';"
        )
        == "Renamed\n"
    )
    out = postgres.psql(
        empty_db,
        "SELECT value #>> '{}' FROM setting WHERE key = 'general.site_title';"
        "SELECT enabled FROM feature_flag WHERE key = 'auth.oidc';"
        "SELECT description FROM permission WHERE key = 'items.read';",
    )
    assert out.split("\n")[:3] == ["Acme monitor", "t", "Read items, versions, diffs and search"]


def test_seeded_rows_follow_the_sources(postgres: Postgres, empty_db: str) -> None:
    url = postgres.url(empty_db)
    upgrade(url)
    asyncio.run(seed.run(SEED_DIR, url))
    q = postgres.psql
    assert q(empty_db, "SELECT geometry_ref, region_code FROM jurisdiction WHERE code='CN';") == (
        "CHN|030\n"
    )
    assert q(empty_db, "SELECT count(*) FROM jurisdiction WHERE kind='supranational';") == "5\n"
    admin = "SELECT count(*) FROM role_permission rp JOIN role r ON r.id = rp.role_id"
    assert q(empty_db, f"{admin} WHERE r.key = 'admin';") == "23\n"
    children = (
        "SELECT count(*) FROM term t JOIN facet f ON f.id = t.facet_id "
        "WHERE f.key = 'control_framework' AND t.parent_id IS NOT NULL;"
    )
    assert q(empty_db, children) == "22\n"
    enabled = "SELECT string_agg(key, ',' ORDER BY key) FROM feature_flag WHERE enabled;"
    assert q(empty_db, enabled) == "capture.js_rendering,outputs.email,reports.builder\n"


def test_catalogue_sources_wait_for_a_follower(postgres: Postgres, empty_db: str) -> None:
    """CP-25: catalogue sources are disabled, respect robots.txt, carry their jurisdictions
    and have a scheduled job, so following one is all it takes to capture it."""
    url = postgres.url(empty_db)
    upgrade(url)
    asyncio.run(seed.run(SEED_DIR, url))
    rows = postgres.psql(
        empty_db,
        "SELECT s.catalogue_key, s.enabled, s.robots_policy, j.code, cj.enabled,"
        " cj.next_run_at IS NOT NULL, s.summary IS NOT NULL, s.terms_url IS NOT NULL"
        " FROM source s JOIN capture_job cj ON cj.source_id = s.id"
        " JOIN jurisdiction j ON j.id = ANY(s.default_jurisdiction_ids)"
        " ORDER BY s.catalogue_key;",
    )
    assert rows.split("\n")[:4] == [
        "eu-eurlex-cellar-it|f|respect|EU|t|t|t|t",
        "eu-eurlex-rss-ep-council|f|respect|EU|t|t|t|t",
        "gb-legislation-it|f|respect|GB|t|t|t|t",
        "us-federal-register-it|f|respect|US|t|t|t|t",
    ]


def test_the_seed_refuses_admin_permissions_on_group_roles(
    postgres: Postgres, empty_db: str
) -> None:
    """CP-27 (11.4a review): no role a group holds may carry users.manage or roles.manage."""
    url = postgres.url(empty_db)
    upgrade(url)
    asyncio.run(seed.run(SEED_DIR, url))
    postgres.psql(
        empty_db,
        "INSERT INTO user_group (key, name) VALUES ('team', 'Team');"
        "INSERT INTO group_role SELECT g.id, r.id FROM user_group g, role r WHERE r.key = 'editor';"
        "INSERT INTO role_permission (role_id, permission_key)"
        " SELECT id, 'roles.manage' FROM role WHERE key = 'editor';",
    )
    with pytest.raises(seed.SeedError, match="editor has roles.manage"):
        asyncio.run(seed.run(SEED_DIR, url))
