"""TaxonomyCache: version polling and explicit invalidation (#34); the database side is in
tests/integration/test_taxonomy_cache.py."""

from __future__ import annotations

from typing import Any

from regwatch.taxonomy.attribute_validator import FacetSpec, TaxonomySnapshot
from regwatch.taxonomy.cache import TaxonomyCache


class Store:
    def __init__(self) -> None:
        self.version, self.loads, self.reads, self.now = 1, 0, 0, 0.0

    async def read(self, _: Any) -> int:
        self.reads += 1
        return self.version

    async def load(self, _: Any) -> TaxonomySnapshot:
        self.loads += 1
        return TaxonomySnapshot(self.version, {"topic": FacetSpec("topic", "text")})


def cache(store: Store) -> TaxonomyCache:
    return TaxonomyCache(5.0, clock=lambda: store.now, version=store.read, loader=store.load)


async def test_snapshot_is_reused_within_the_interval_then_rechecked() -> None:
    store = Store()
    c = cache(store)
    first = await c.get(None)  # type: ignore[arg-type]
    store.version, store.now = 2, 4.9
    assert await c.get(None) is first  # type: ignore[arg-type]
    store.now = 5.0
    assert (await c.get(None)).version == 2  # type: ignore[arg-type]
    assert (store.loads, store.reads) == (2, 1)


async def test_unchanged_version_keeps_the_snapshot() -> None:
    store = Store()
    c = cache(store)
    first = await c.get(None)  # type: ignore[arg-type]
    store.now = 10.0
    assert await c.get(None) is first  # type: ignore[arg-type]
    assert (store.loads, store.reads) == (1, 1)


async def test_invalidate_reloads_at_once() -> None:
    store = Store()
    c = cache(store)
    await c.get(None)  # type: ignore[arg-type]
    c.invalidate()
    validator = await c.validator(None)  # type: ignore[arg-type]
    assert store.loads == 2
    assert validator.validate({"topic": "x"}) == {"topic": ["x"]}
