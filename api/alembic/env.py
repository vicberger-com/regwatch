"""Alembic environment: online migrations over asyncpg.

The URL comes from ``config.attributes["database_url"]`` when a caller (tests) sets it, else
from ``REGWATCH_DATABASE_URL``. Offline (``--sql``) mode is not supported: revision 0001 runs a
multi-statement script through the driver's simple-query protocol.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from regwatch.core.db import create_engine

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)


def _database_url() -> str:
    url = config.attributes.get("database_url")
    if url:
        return str(url)
    from regwatch.core.settings import get_settings

    return get_settings().database_url.get_secret_value()


def _migrate(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_engine(_database_url(), poolclass_null=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_migrate)
            await connection.commit()
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("offline (--sql) migrations are not supported; run against a database")
asyncio.run(_run_online())
