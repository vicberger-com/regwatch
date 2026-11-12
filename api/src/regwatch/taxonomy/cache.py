"""Taxonomy snapshot cache with explicit invalidation, shared by the api and (later) workers.

Every taxonomy write bumps the ``taxonomy.version`` setting in the same transaction
(:func:`bump_version`). A process keeps one :class:`TaxonomyCache`; ``get`` re-reads the
version at most every ``check_interval`` seconds and reloads the snapshot when it moved, so
another process sees a change within that interval. ``invalidate`` drops the snapshot at
once; the writing process calls it after commit.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.admin.models import Setting
from regwatch.taxonomy.attribute_validator import AttributeValidator, FacetSpec, TaxonomySnapshot
from regwatch.taxonomy.models import Facet, Term

VERSION_KEY = "taxonomy.version"
_BUMP = text(
    "INSERT INTO setting (key, value) VALUES (:key, '1'::jsonb) ON CONFLICT (key) DO UPDATE"
    " SET value = to_jsonb((setting.value)::bigint + 1), updated_at = now() RETURNING value"
)


async def read_version(session: AsyncSession) -> int:
    value = await session.scalar(select(Setting.value).where(Setting.key == VERSION_KEY))
    return value if isinstance(value, int) else 0


async def bump_version(session: AsyncSession) -> int:
    """Increment the version inside the caller's transaction; return the new value."""
    return int((await session.execute(_BUMP, {"key": VERSION_KEY})).scalar_one())


async def load_snapshot(session: AsyncSession) -> TaxonomySnapshot:
    version = await read_version(session)
    rows = await session.execute(
        select(Term.facet_id, Term.key, Term.synonyms).where(Term.active.is_(True))
    )
    terms: dict[object, dict[str, list[str]]] = defaultdict(dict)
    for facet_id, key, synonyms in rows:
        terms[facet_id][key] = list(synonyms)
    facets = {
        f.key: FacetSpec.with_terms(
            f.key, f.value_type, terms[f.id], multi=f.multi, required=f.required
        )
        for f in (await session.scalars(select(Facet))).all()
    }
    return TaxonomySnapshot(version, facets)


class TaxonomyCache:
    def __init__(
        self,
        check_interval: float = 5.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        version: Callable[[AsyncSession], Awaitable[int]] = read_version,
        loader: Callable[[AsyncSession], Awaitable[TaxonomySnapshot]] = load_snapshot,
    ) -> None:
        self.check_interval = check_interval
        self._clock, self._version, self._loader = clock, version, loader
        self._snapshot: TaxonomySnapshot | None = None
        self._checked = -math.inf

    def invalidate(self) -> None:
        self._snapshot = None

    async def get(self, session: AsyncSession) -> TaxonomySnapshot:
        now = self._clock()
        if self._snapshot is not None and now - self._checked < self.check_interval:
            return self._snapshot
        if self._snapshot is None or self._snapshot.version != await self._version(session):
            self._snapshot = await self._loader(session)
        self._checked = now
        return self._snapshot

    async def validator(self, session: AsyncSession) -> AttributeValidator:
        return AttributeValidator(await self.get(session))
