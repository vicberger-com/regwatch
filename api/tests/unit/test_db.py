"""Unit: the database URL from env.example maps to SQLAlchemy's asyncpg dialect (#28)."""

from __future__ import annotations

import asyncio

import pytest

from regwatch.core import db


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@h:5432/d",
        "postgresql+psycopg://u:p@h:5432/d",
        "postgresql+asyncpg://u:p@h:5432/d",
        "postgres://u:p@h:5432/d",
    ],
)
def test_async_url_uses_asyncpg(url: str) -> None:
    assert db.async_url(url) == "postgresql+asyncpg://u:p@h:5432/d"


def test_async_url_rejects_other_databases() -> None:
    with pytest.raises(ValueError, match="postgresql"):
        db.async_url("mysql://u:p@h/d")


def test_create_engine_does_not_connect() -> None:
    engine = db.create_engine("postgresql://u:p@127.0.0.1:1/d", poolclass_null=True)
    assert engine.url.drivername == "postgresql+asyncpg"
    asyncio.run(engine.dispose())
    assert db.create_engine("postgresql://u:p@127.0.0.1:1/d").url.database == "d"
