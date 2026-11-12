"""Integration: taxonomy.version bumps reach a second process's cache (#34, REQ-03).

Two ``TaxonomyCache`` instances on separate engines stand for the api and a worker.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from regwatch.core import seed
from regwatch.core.db import create_engine
from regwatch.taxonomy import services
from regwatch.taxonomy.attribute_validator import AttributeValidationError
from regwatch.taxonomy.cache import TaxonomyCache, bump_version, read_version
from tests.integration.conftest import Postgres, upgrade

pytestmark = pytest.mark.integration
SEED_DIR = Path(__file__).resolve().parents[2] / "seed"


def test_version_bump_reaches_the_worker_cache(postgres: Postgres, empty_db: str) -> None:
    url = postgres.url(empty_db)
    upgrade(url)
    asyncio.run(seed.run(SEED_DIR, url))

    async def scenario() -> None:
        api_engine, worker_engine = create_engine(url), create_engine(url)
        api, worker = async_sessionmaker(api_engine), async_sessionmaker(worker_engine)
        now = [0.0]
        worker_cache = TaxonomyCache(5.0, clock=lambda: now[0])
        try:
            async with worker() as s:
                assert await read_version(s) == 0
                before = await worker_cache.validator(s)
                assert before.validate({"topic": "privacy"}) == {"topic": ["privacy"]}
                assert "control_framework" in before.snapshot.facets
            async with api() as s:
                await s.execute(text("UPDATE term SET active = false WHERE key = 'privacy'"))
                assert await services.commit_change(s) == 1
                assert await services.commit_change(s) == 2
                with pytest.raises(AttributeValidationError, match=r"attributes\.topic\[0\]"):
                    await services.validate_attributes(s, {"topic": "privacy"})
            async with worker() as s:
                now[0] = 4.0  # within the interval the worker still has version 0
                assert (await worker_cache.get(s)).version == 0
                now[0] = 5.0
                after = await worker_cache.validator(s)
                assert after.snapshot.version == 2
                with pytest.raises(AttributeValidationError):
                    after.validate({"topic": "privacy"})
                assert await bump_version(s) == 3
                await s.rollback()
                assert await read_version(s) == 2
        finally:
            await api_engine.dispose()
            await worker_engine.dispose()

    asyncio.run(scenario())
