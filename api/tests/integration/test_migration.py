"""Integration: revision 0001 against an empty PostgreSQL 16 (#28 acceptance 1, 2 and 4)."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import asyncpg
import pytest

from tests.integration.conftest import Postgres, downgrade, upgrade

pytestmark = pytest.mark.integration

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "contracts" / "schema.sql"


def expanded_contract() -> str:
    """schema.sql plus what its comments prescribe, derived from the contract text itself.

    * ``CREATE EXTENSION citext`` (comment on ``"user".email``);
    * a ``set_updated_at`` trigger for every table marked ``-- std``;
    * the application role: INSERT and SELECT only on ``audit_log``, full DML elsewhere.
    """
    sql = CONTRACT.read_text(encoding="utf-8")
    std = re.findall(r'^CREATE TABLE ("?\w+"?) \( -- std', sql, flags=re.M)
    tables = re.findall(r'^CREATE TABLE ("?\w+"?)', sql, flags=re.M)
    triggers = "".join(
        f"CREATE TRIGGER trg_{t.strip(chr(34))}_updated BEFORE UPDATE ON {t} "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();\n"
        for t in std
    )
    dml = ", ".join(t for t in tables if t != "audit_log")
    grants = (
        "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'regwatch_app') "
        "THEN CREATE ROLE regwatch_app NOLOGIN; END IF; END $$;\n"
        "GRANT USAGE ON SCHEMA public TO regwatch_app;\n"
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {dml} TO regwatch_app;\n"
        "GRANT SELECT, INSERT ON audit_log TO regwatch_app;\n"
        "GRANT SELECT ON jurisdiction_activity TO regwatch_app;\n"
    )
    return "CREATE EXTENSION IF NOT EXISTS citext;\n" + sql + triggers + grants


def test_upgrade_downgrade_upgrade_on_empty_database(postgres: Postgres, empty_db: str) -> None:
    url = postgres.url(empty_db)
    before = postgres.schema_dump(empty_db)
    upgrade(url)
    tables = postgres.psql(empty_db, "SELECT count(*) FROM pg_tables WHERE schemaname='public';")
    assert int(tables) == 28  # 27 contract tables and alembic_version
    downgrade(url)
    assert postgres.schema_dump(empty_db) == before
    upgrade(url)
    assert postgres.psql(empty_db, "SELECT version_num FROM alembic_version;").strip() == "0006"


def test_schema_matches_contract(postgres: Postgres, empty_db: str) -> None:
    upgrade(postgres.url(empty_db))
    reference = f"{empty_db}_ref"
    postgres.psql("postgres", f"CREATE DATABASE {reference};")
    postgres.psql(reference, expanded_contract())
    migrated, expected = postgres.schema_dump(empty_db), postgres.schema_dump(reference)
    assert len(expected) > 300
    assert migrated == expected


def test_std_tables_get_updated_at_trigger(postgres: Postgres, empty_db: str) -> None:
    upgrade(postgres.url(empty_db))
    out = postgres.psql(
        empty_db,
        "INSERT INTO role (key, label) VALUES ('t', 'T');"
        "UPDATE role SET label = 'U', updated_at = '2000-01-01' WHERE key = 't';"
        "SELECT updated_at > '2020-01-01' FROM role WHERE key = 't';",
    )
    assert out.strip() == "t"


async def _audit_checks(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        await conn.execute("SET ROLE regwatch_app")
        await conn.execute("INSERT INTO audit_log (action, entity_type) VALUES ('t.x', 'test')")
        assert await conn.fetchval("SELECT count(*) FROM audit_log") == 1
        await conn.execute("INSERT INTO setting (key, value) VALUES ('t', '1')")
        await conn.execute("UPDATE setting SET value = '2' WHERE key = 't'")
        for stmt in (
            "UPDATE audit_log SET action = 'tampered'",
            "DELETE FROM audit_log",
            "TRUNCATE audit_log",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute(stmt)
    finally:
        await conn.close()


def test_application_role_cannot_update_or_delete_audit_log(
    postgres: Postgres, empty_db: str
) -> None:
    url = postgres.url(empty_db)
    upgrade(url)
    asyncio.run(_audit_checks(url))


def test_capture_models_match_the_tables(postgres: Postgres, empty_db: str) -> None:
    """M3: every column the ORM maps for source, capture_job and capture_run exists in the
    migrated database with the same nullability."""
    from regwatch.capture import models
    from regwatch.core.db import Base

    upgrade(postgres.url(empty_db))
    for table in (
        models.Source.__table__,
        models.CaptureJob.__table__,
        models.CaptureRun.__table__,
    ):
        sql = (
            "SELECT column_name || ':' || is_nullable FROM information_schema.columns "
            f"WHERE table_name = '{table.name}';"
        )
        rows = postgres.psql(empty_db, sql)
        db = dict(line.split(":") for line in rows.split() if ":" in line)
        for column in table.columns:
            assert column.name in db, f"{table.name}.{column.name} is not in the database"
            assert (db[column.name] == "YES") == column.nullable, f"{table.name}.{column.name}"
    assert "source" in Base.metadata.tables


def test_cp11_one_unfinished_run_per_job_and_one_job_per_source(
    postgres: Postgres, empty_db: str
) -> None:
    """CP-11: the database refuses a second unfinished run of a job, and a second job for a
    source; finished runs are not limited."""
    upgrade(postgres.url(empty_db))
    setup = (
        "INSERT INTO source (id, name, kind) VALUES ('01930000-0000-7000-8000-000000000001',"
        " 's', 'manual');"
        "INSERT INTO capture_job (id, source_id, interval_seconds) VALUES"
        " ('01930000-0000-7000-8000-000000000002', '01930000-0000-7000-8000-000000000001',"
        " 3600);"
        "INSERT INTO capture_run (job_id, finished_at) VALUES"
        " ('01930000-0000-7000-8000-000000000002', now()),"
        " ('01930000-0000-7000-8000-000000000002', now());"
        "INSERT INTO capture_run (job_id) VALUES ('01930000-0000-7000-8000-000000000002');"
    )
    postgres.psql(empty_db, setup)
    for sql in (
        "INSERT INTO capture_run (job_id) VALUES ('01930000-0000-7000-8000-000000000002');",
        "INSERT INTO capture_job (source_id, interval_seconds) VALUES"
        " ('01930000-0000-7000-8000-000000000001', 3600);",
    ):
        with pytest.raises(RuntimeError, match="duplicate key"):
            postgres.psql(empty_db, sql)


def test_0005_treats_existing_items_as_fetched_from_their_host(
    postgres: Postgres, empty_db: str
) -> None:
    """CP-19 backfill (re-verification 3): an unchanged item from before 0005 is not claimable."""
    upgrade(postgres.url(empty_db), "0004")
    sid = "'00000000-0000-7000-8000-000000000001'"
    postgres.psql(empty_db, """
        INSERT INTO source (id, name, kind) VALUES
          ('00000000-0000-7000-8000-000000000001', 's', 'rss');
        INSERT INTO item (source_id, canonical_url, url_hash, title, content_hash) VALUES
          (S, 'https://WWW.Reg.example./act?x=1', 'a', 't', 'h'),
          (S, 'http://u:p@agency.example:8443/r', 'b', 't', 'h'),
          (S, 'urn:sha256:00', 'c', 't', 'h');
    """.replace("S,", sid + ","))  # fmt: skip
    upgrade(postgres.url(empty_db))
    got = postgres.psql(empty_db, "SELECT url_hash || '=' || coalesce(fetched_host, '-') "
                                  "FROM item ORDER BY url_hash;")  # fmt: skip
    assert got.split() == ["a=reg.example", "b=agency.example", "c=-"]
