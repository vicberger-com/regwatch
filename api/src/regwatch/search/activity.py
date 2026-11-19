"""``GET /map/activity`` (M5 interfaces; acceptance 2).

Per jurisdiction, for the period (``from`` and ``to``, else the last ``period_days`` days):

- ``count``: the items matching ``filters`` that have a change event in the period there, each
  counted once per jurisdiction; summed over Europe's jurisdictions it equals the search total
  for the same filters, region Europe and ``changed`` in the period, when each item is in one of
  them (acceptance 2);
- ``last_changed_at``: the latest such event; ``max_severity``: the highest, or ``none``;
- ``breakdown``: those items by the severity of their highest event in the period.

``view_by`` is ``country`` (jurisdiction codes) or ``region`` (M49 sub-region codes, and the
codes of bodies with no region such as EU and COE). A row is where the event is; jurisdiction
and region filters, as in search, are about the item's tags. The
filters are ``Query.filters`` as URL-encoded JSON, checked as search checks them (400 past the
limits); ``filters.changed`` is ignored, the period stands for it. One statement with the
search's timeout, and the search's rate per user.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import case, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.processing.models import ChangeEvent, Item
from regwatch.search import services
from regwatch.search.query import check, conditions, resolve_terms
from regwatch.search.schemas import MapActivity, MapRow, Query, QueryFilters
from regwatch.taxonomy.models import Jurisdiction

VIEWS = ("country", "region")
MAX_FILTERS = 16_000  # characters of URL-encoded JSON
_RANK = case((ChangeEvent.severity == "major", 3), (ChangeEvent.severity == "notable", 2),
             else_=1)  # fmt: skip
_NAMES = {0: "none", 1: "info", 2: "notable", 3: "major"}


def _bad(field: str, message: str) -> ProblemError:
    return ProblemError(400, "invalid-query", message,
                        errors=[ProblemFieldError(field=field, message=message)])  # fmt: skip


def parse_filters(raw: str | None) -> QueryFilters | None:
    if not raw:
        return None
    if len(raw) > MAX_FILTERS:
        raise _bad("filters", f"at most {MAX_FILTERS} characters")
    try:
        found = QueryFilters.model_validate(json.loads(raw))
    except (ValueError, ValidationError):
        raise _bad("filters", "filters must be the JSON of Query.filters") from None
    return found.model_copy(update={"changed": None})


async def activity(db: AsyncSession, user_id: uuid.UUID | None, period_days: int,
                   start: datetime | None, end: datetime | None, raw_filters: str | None,
                   view_by: str) -> MapActivity:  # fmt: skip
    if view_by not in VIEWS:
        raise _bad("view_by", "country or region")
    # A time without a zone is UTC (S7).
    end = (end if end.tzinfo else end.replace(tzinfo=UTC)) if end else datetime.now(UTC)
    start = (start if start.tzinfo else start.replace(tzinfo=UTC)) if start else (
        end - timedelta(days=period_days))  # fmt: skip
    if start >= end:
        raise _bad("from", "from must be before to")
    filters = parse_filters(raw_filters)
    check(Query(filters=filters) if filters else Query())
    services.limited(user_id)
    await db.execute(text(f"SET LOCAL statement_timeout = '{services.STATEMENT_TIMEOUT}'"))
    where = conditions(filters, await resolve_terms(db, filters))
    # The region view lists M49 sub-regions, and bodies with no region (EU, COE) by their own
    # code, so no event is dropped (slice 2 S5).
    key = (Jurisdiction.code if view_by == "country"
           else func.coalesce(Jurisdiction.region_code, Jurisdiction.code))  # fmt: skip
    per_item = (
        select(key.label("key"), ChangeEvent.item_id, func.max(_RANK).label("rank"),
               func.max(ChangeEvent.occurred_at).label("last"))
        .join(Jurisdiction, Jurisdiction.id == ChangeEvent.jurisdiction_id)
        .join(Item, Item.id == ChangeEvent.item_id)
        .where(ChangeEvent.occurred_at >= start, ChangeEvent.occurred_at <= end,
               *where)
        .group_by(key, ChangeEvent.item_id)
    ).subquery()  # fmt: skip
    try:
        rows = await db.execute(
        select(per_item.c.key, func.count(), func.max(per_item.c.last), func.max(per_item.c.rank),
               func.count().filter(per_item.c.rank == 1), func.count().filter(per_item.c.rank == 2),
               func.count().filter(per_item.c.rank == 3))
        .group_by(per_item.c.key).order_by(per_item.c.key))  # fmt: skip
    except DBAPIError as exc:  # the statement timeout is a 503, not a 500 (S9)
        if not services.timed_out(exc):
            raise
        await db.rollback()
        raise services.busy() from None
    out = [MapRow(code=code, count=count, last_changed_at=last, max_severity=_NAMES[rank or 0],
                  breakdown={"info": info, "notable": notable, "major": major})
           for code, count, last, rank, info, notable, major in rows.tuples().all()]  # fmt: skip
    return MapActivity(period_start=start, period_end=end, view_by=view_by,
                       generated_at=datetime.now(UTC), stale=False, rows=out)  # fmt: skip
