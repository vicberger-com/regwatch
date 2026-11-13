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


async def test_start_up_check_tolerates_an_unreachable_database(
    valid_env: dict[str, str],
) -> None:
    engine = create_engine("postgresql://nobody:x@127.0.0.1:1/none", poolclass_null=True)
    await check_database_login(engine, Settings(env="production"))  # /health reports it
    await engine.dispose()


def test_seed_runs_as_the_api_login(postgres: Postgres, migrated: str) -> None:
    """``make seed`` uses REGWATCH_DATABASE_URL, so regwatch_app's grants must cover it."""
    import asyncio
    from pathlib import Path

    from regwatch.core import seed

    seed_dir = Path(__file__).resolve().parents[2] / "seed"
    counts = asyncio.run(seed.run(seed_dir, postgres.app_url(migrated)))
    assert counts["permission"] == 23 and counts["role"] == 4
