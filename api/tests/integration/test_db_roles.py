"""Integration: the API's login cannot alter the audit log (BL-61, 8.1, M1 design notes)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from regwatch.api.app import check_database_login
from regwatch.core.db import audit_log_is_append_only, create_engine
from regwatch.core.settings import Settings
from tests.integration.conftest import Postgres, upgrade

pytestmark = pytest.mark.integration

ROW = "INSERT INTO audit_log (action, entity_type) VALUES ('test.row', 'test')"


@pytest.fixture
def migrated(postgres: Postgres, empty_db: str) -> str:
    upgrade(postgres.url(empty_db))
    return empty_db


async def test_api_login_inserts_but_cannot_change_audit_rows(
    postgres: Postgres, migrated: str
) -> None:
    engine = create_engine(postgres.app_url(migrated), poolclass_null=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(ROW))
        for statement in ("UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log",
                          "TRUNCATE audit_log"):  # fmt: skip
            with pytest.raises(DBAPIError, match="permission denied"):
                async with engine.begin() as conn:
                    await conn.execute(text(statement))
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT count(*) FROM audit_log")) == 1
        assert await audit_log_is_append_only(engine)
    finally:
        await engine.dispose()


async def test_start_up_refuses_an_owner_login_in_production(
    postgres: Postgres, migrated: str, valid_env: dict[str, str]
) -> None:
    owner = create_engine(postgres.url(migrated), poolclass_null=True)
    app = create_engine(postgres.app_url(migrated), poolclass_null=True)
    try:
        assert not await audit_log_is_append_only(owner)
        with pytest.raises(RuntimeError, match="BL-61"):
            await check_database_login(owner, Settings(env="production"))
        await check_database_login(owner, Settings(env="development"))  # warns only
        await check_database_login(app, Settings(env="production"))
    finally:
        await owner.dispose()
        await app.dispose()


async def test_start_up_fails_closed_in_production_and_warns_elsewhere(
    postgres: Postgres, empty_db: str, valid_env: dict[str, str]
) -> None:
    """Re-review 6b: an unreachable or unmigrated database stops a production start."""
    unreachable = create_engine("postgresql://nobody:x@127.0.0.1:1/none", poolclass_null=True)
    unmigrated = create_engine(postgres.app_url(empty_db), poolclass_null=True)
    try:
        for engine in (unreachable, unmigrated):
            with pytest.raises(RuntimeError, match="cannot verify"):
                await check_database_login(engine, Settings(env="production"))
            await check_database_login(engine, Settings(env="development"))  # warns only
    finally:
        await unreachable.dispose()
        await unmigrated.dispose()


async def test_owner_url_in_the_api_environment_stops_production(
    postgres: Postgres, migrated: str, valid_env: dict[str, str]
) -> None:
    """Re-review 6a: the owner URL belongs to the migrate container only."""
    engine = create_engine(postgres.app_url(migrated), poolclass_null=True)
    owner_url = postgres.url(migrated)
    try:
        with pytest.raises(RuntimeError, match="MIGRATION_DATABASE_URL"):
            await check_database_login(
                engine, Settings(env="production", migration_database_url=owner_url)
            )
        await check_database_login(engine, Settings(env="test", migration_database_url=owner_url))
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    ("name", "grants"),
    [
        ("rw_noinherit", ["CREATE ROLE rw_writer NOLOGIN",
                          "GRANT UPDATE ON audit_log TO rw_writer",
                          "CREATE ROLE rw_noinherit LOGIN NOINHERIT PASSWORD 'p' "
                          "IN ROLE rw_writer"]),
        ("rw_column", ["CREATE ROLE rw_column LOGIN PASSWORD 'p' IN ROLE regwatch_app",
                       "GRANT UPDATE (action) ON audit_log TO rw_column"]),
    ],
)  # fmt: skip
async def test_check_sees_noinherit_members_and_column_grants(
    postgres: Postgres, migrated: str, name: str, grants: list[str]
) -> None:
    """Re-review 6c: privileges reachable through SET ROLE or on a column also count."""
    postgres.psql(migrated, ";\n".join(grants) + ";")
    url = f"postgresql://{name}:p@127.0.0.1:{postgres.port}/{migrated}"
    engine = create_engine(url, poolclass_null=True)
    try:
        assert not await audit_log_is_append_only(engine)
    finally:
        await engine.dispose()
        cleanup = [f"DROP OWNED BY {name}", f"DROP ROLE {name}"]
        if name == "rw_noinherit":
            cleanup += ["DROP OWNED BY rw_writer", "DROP ROLE rw_writer"]
        postgres.psql(migrated, ";\n".join(cleanup) + ";")


def test_seed_runs_as_the_api_login(postgres: Postgres, migrated: str) -> None:
    """``make seed`` uses REGWATCH_DATABASE_URL, so regwatch_app's grants must cover it."""
    import asyncio
    from pathlib import Path

    from regwatch.core import seed

    seed_dir = Path(__file__).resolve().parents[2] / "seed"
    counts = asyncio.run(seed.run(seed_dir, postgres.app_url(migrated)))
    assert counts["permission"] == 23 and counts["role"] == 4
