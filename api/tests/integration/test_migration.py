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
    assert postgres.psql(empty_db, "SELECT version_num FROM alembic_version;").strip() == "0001"


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
