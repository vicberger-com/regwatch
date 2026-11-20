"""Feed requests (ADR-0012, CP-26, M11.3).

A user who reads items asks for a feed with an https URL and a reason. The URL is checked for
its form only and never fetched here: fetching it would let any user make the server probe
hosts. An editor checks it by creating the source in the source editor, where every check
applies (DNS included), and then approves the request with that source; or declines it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture.models import FeedRequest, Source, SourceFollower
from regwatch.capture.schemas import FeedRequestDecision, FeedRequestOut, FeedRequestWrite
from regwatch.capture.services import _web_link, invalid
from regwatch.core.errors import ProblemError
from regwatch.core.schemas import has_control
from regwatch.core.services import audit
from regwatch.identity.models import User
from regwatch.identity.services import Principal, SlidingWindow

MANAGE = "sources.manage"
MAX_PENDING = 10  # pending requests per user
REQUEST_RATE = 10  # requests an hour, per user
LISTED = 200  # newest requests listed
requests_made = SlidingWindow(3600.0)


def _plain(field: str, value: str | None, *, required: bool) -> str | None:
    text = (value or "").strip()
    if required and not text:
        raise invalid(field, f"{field} is required")
    if has_control(text):
        raise invalid(field, "control and direction-changing characters are not allowed")
    return text or None


def _out(row: FeedRequest, name: str | None) -> FeedRequestOut:
    return FeedRequestOut.model_validate(
        {**{c.key: getattr(row, c.key) for c in FeedRequest.__table__.columns},
         "requested_by": name})  # fmt: skip


async def create(db: AsyncSession, body: FeedRequestWrite, principal: Principal,
                 ip: str | None) -> FeedRequestOut:  # fmt: skip
    url = body.url.strip()
    if not (_web_link(url) and url.lower().startswith("https://")):
        raise invalid("url", "an https URL of at most 2048 characters")
    reason = _plain("reason", body.reason, required=True)
    me = principal.user.id
    key = str(me)
    if requests_made.count(key) >= REQUEST_RATE:
        wait = str(requests_made.retry_after(key))
        raise ProblemError(429, "rate-limited", "Too many requests; try again later.",
                           headers={"Retry-After": wait})  # fmt: skip
    mine = (FeedRequest.requested_by == me, FeedRequest.status == "pending")
    if (await db.scalar(select(func.count()).where(*mine)) or 0) >= MAX_PENDING:
        raise ProblemError(409, "conflict", f"You can have at most {MAX_PENDING} requests "
                           "waiting; withdraw one or wait for a decision.")  # fmt: skip
    if await db.scalar(select(FeedRequest.id).where(*mine, FeedRequest.url == url)):
        raise ProblemError(409, "conflict", "You have already asked for this feed.")
    requests_made.hit(key)
    row = FeedRequest(requested_by=me, url=url, reason=reason)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    audit(db, "feed_request.create", "feed_request", row.id, actor=me, ip=ip,
          after={"url": url, "reason": reason})  # fmt: skip
    out = _out(row, principal.user.display_name if MANAGE in principal.permissions else None)
    await db.commit()
    return out


async def listed(
    db: AsyncSession, principal: Principal, status: str | None
) -> list[FeedRequestOut]:
    """Editors see every request with the requester's name; others see their own."""
    editor = MANAGE in principal.permissions
    query = select(FeedRequest, User.display_name).join(User, User.id == FeedRequest.requested_by)
    if not editor:
        query = query.where(FeedRequest.requested_by == principal.user.id)
    if status is not None:
        query = query.where(FeedRequest.status == status)
    rows = (await db.execute(query.order_by(FeedRequest.created_at.desc(), FeedRequest.id)
                             .limit(LISTED))).tuples().all()  # fmt: skip
    return [_out(row, name if editor else None) for row, name in rows]


async def _pending(db: AsyncSession, request_id: uuid.UUID) -> FeedRequest:
    row = await db.scalar(select(FeedRequest).where(FeedRequest.id == request_id)
                          .with_for_update())  # fmt: skip
    if row is None:
        raise ProblemError(404, "not-found", "No such feed request.")
    if row.status != "pending":
        raise ProblemError(409, "conflict", f"The request is already {row.status}.")
    return row


async def withdraw(db: AsyncSession, request_id: uuid.UUID, principal: Principal,
                   ip: str | None) -> None:  # fmt: skip
    row = await db.scalar(select(FeedRequest.requested_by).where(FeedRequest.id == request_id))
    if row != principal.user.id:  # someone else's request is not found, not forbidden
        raise ProblemError(404, "not-found", "No such feed request.")
    request = await _pending(db, request_id)
    request.status = "withdrawn"
    audit(db, "feed_request.withdraw", "feed_request", request.id, actor=principal.user.id,
          ip=ip, before={"status": "pending"}, after={"status": "withdrawn"})  # fmt: skip
    await db.commit()


async def decide(db: AsyncSession, request_id: uuid.UUID, body: FeedRequestDecision,
                 principal: Principal, ip: str | None) -> FeedRequestOut:  # fmt: skip
    """Approve with the source the editor created (it joins the catalogue, and the requester
    follows it), or decline."""
    note = _plain("note", body.note, required=False)
    request = await _pending(db, request_id)
    after: dict[str, object] = {"status": body.decision}
    if body.decision == "approved":
        if body.source_id is None:
            raise invalid("source_id", "approving needs the source created for the request")
        summary = _plain("summary", body.summary, required=False)
        source = await db.scalar(select(Source).where(Source.id == body.source_id)
                                 .with_for_update())  # fmt: skip
        if source is None:
            raise invalid("source_id", "no such source")
        if source.catalogue_key is None:  # it joins the catalogue as added, not curated
            if summary is None:
                raise invalid("summary", "a one-line summary for the catalogue is required")
            source.catalogue_key = f"added-{source.id.hex[:12]}"
            source.summary = summary
            after["catalogue_key"] = source.catalogue_key
        request.source_id = source.id
        after["source_id"] = str(source.id)
        follow = insert(SourceFollower).values(source_id=source.id, user_id=request.requested_by)
        await db.execute(follow.on_conflict_do_nothing())
    request.status = body.decision
    request.decided_by = principal.user.id
    request.decided_at = datetime.now(UTC)
    request.decision_note = note
    audit(db, f"feed_request.{'approve' if body.decision == 'approved' else 'decline'}",
          "feed_request", request.id, actor=principal.user.id, ip=ip,
          before={"status": "pending"}, after={**after, "note": note})  # fmt: skip
    await db.flush()
    await db.refresh(request)
    name = await db.scalar(select(User.display_name).where(User.id == request.requested_by))
    out = _out(request, name)
    await db.commit()
    return out
