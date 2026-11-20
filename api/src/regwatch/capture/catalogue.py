"""The curated feed catalogue and following (ADR-0012, CP-25, M11.2).

Following is the one way an ``items.read`` user can make the application fetch from outside,
so it is held tight (11.2a review):
- only catalogue sources can be followed, by id; nothing about the source or its job changes;
- an admin's disable wins: a source whose job is off cannot be followed and is not captured;
- a per-user rate and a cap on how many sources one user follows;
- an audit row whenever a follow or unfollow switches a source's capture on or off;
- nobody sees who else follows a source.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture.models import CaptureJob, Source, SourceFollower, capturing, is_capturing
from regwatch.capture.schemas import CatalogueEntry
from regwatch.core.errors import ProblemError
from regwatch.core.services import audit
from regwatch.identity.services import SlidingWindow
from regwatch.taxonomy.models import Jurisdiction

MAX_FOLLOWED = 200  # sources one user may follow
FOLLOW_RATE = 30  # follows and unfollows a minute, per user
follows = SlidingWindow(60.0)


async def list_catalogue(db: AsyncSession, user_id: uuid.UUID) -> list[CatalogueEntry]:
    rows = (await db.execute(
        select(Source, CaptureJob.enabled, capturing())
        .join(CaptureJob, CaptureJob.source_id == Source.id, isouter=True)
        .where(Source.catalogue_key.is_not(None))
        .order_by(Source.name, Source.id))).all()  # fmt: skip
    mine = select(SourceFollower.source_id).where(SourceFollower.user_id == user_id)
    followed = set((await db.scalars(mine)).all())
    ids = {i for source, _, _ in rows for i in source.default_jurisdiction_ids}
    places = select(Jurisdiction.id, Jurisdiction.code).where(Jurisdiction.id.in_(ids))
    codes = dict((await db.execute(places)).tuples().all())
    return [
        CatalogueEntry(
            id=source.id, key=str(source.catalogue_key), name=source.name,
            summary=source.summary or "", kind=source.kind, url=source.url,
            terms_url=source.terms_url, credibility=source.credibility, language=source.language,
            jurisdictions=sorted(codes[i] for i in source.default_jurisdiction_ids if i in codes),
            health=source.health, available=bool(job_on), captured=bool(job_on and on),
            following=source.id in followed,
        )
        for source, job_on, on in rows
    ]  # fmt: skip


def _limited(user_id: uuid.UUID) -> None:
    key = str(user_id)
    if follows.count(key) >= FOLLOW_RATE:
        raise ProblemError(429, "rate-limited", "Too many changes; try again shortly.",
                           headers={"Retry-After": str(follows.retry_after(key))})  # fmt: skip
    follows.hit(key)


async def set_following(db: AsyncSession, source_id: uuid.UUID, user_id: uuid.UUID,
                        follow: bool, ip: str | None) -> None:  # fmt: skip
    """Follow or unfollow a catalogue source; following one already followed changes nothing."""
    _limited(user_id)
    # The row lock orders concurrent follows of one source, so each switch is audited once.
    source = await db.scalar(select(Source).where(Source.id == source_id,
                                                  Source.catalogue_key.is_not(None))
                             .with_for_update())  # fmt: skip
    if source is None:  # an admin's own sources are not in the catalogue: not found
        raise ProblemError(404, "not-found", "No such catalogue source.")
    job_on = await db.scalar(select(CaptureJob.enabled).where(CaptureJob.source_id == source.id))
    mine = (SourceFollower.source_id == source.id, SourceFollower.user_id == user_id)
    already = await db.scalar(select(SourceFollower.source_id).where(*mine)) is not None
    if follow == already:
        await db.rollback()
        return
    if follow:
        if not job_on:
            raise ProblemError(409, "conflict", "An administrator has turned this source off.")
        # One user's follows of different sources lock different rows; this orders them, so
        # concurrent follows cannot both count under the cap (11.2b review).
        await db.execute(select(func.pg_advisory_xact_lock(
            func.hashtextextended(f"source_follower:{user_id}", 0))))  # fmt: skip
        count = await db.scalar(select(func.count()).where(SourceFollower.user_id == user_id))
        if (count or 0) >= MAX_FOLLOWED:
            raise ProblemError(409, "conflict", f"You can follow at most {MAX_FOLLOWED} sources.")
    before = bool(job_on) and await is_capturing(db, source.id)
    if follow:
        await db.execute(insert(SourceFollower).values(source_id=source.id, user_id=user_id)
                         .on_conflict_do_nothing())  # fmt: skip
    else:
        await db.execute(delete(SourceFollower).where(*mine))
    after = bool(job_on) and await is_capturing(db, source.id)
    if before != after:  # who switched outside fetching on or off (11.2a review)
        action = "source.follow" if follow else "source.unfollow"
        audit(db, action, "source", source.id, actor=user_id, ip=ip,
              before={"captured": before}, after={"captured": after})  # fmt: skip
    await db.commit()
