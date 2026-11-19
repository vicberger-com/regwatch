"""``POST /search/export.csv`` (M5 acceptance 4; Q2: metadata plus summary, no full text).

- The search's query, its checks, its rate and its timeout per statement; at most
  ``search.export_row_cap`` rows (50,000), in the search's order.
- Streamed: ids are read ``BATCH`` at a time from one ordered query, their rows written and
  sent, so memory stays flat however many rows (acceptance 4: under 300 MB).
- UTF-8 with a BOM, so spreadsheet programs read it; every cell that starts with ``=``, ``+``,
  ``-``, ``@``, a tab or a carriage return is prefixed with ``'`` (formula injection), and
  control characters are removed.
- ``columns`` picks from ``COLUMNS`` in that order; unknown names are a 400.
- The stream opens its own database session from the app's factory, since the request's
  session closes before a streamed body is sent.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from regwatch.admin.services import values
from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.processing.schemas import ItemSummary
from regwatch.search import services
from regwatch.search.query import check, compile_query, period, resolve_terms
from regwatch.search.schemas import Query

BATCH = 500
DEFAULT_CAP = 50_000
COLUMNS = ("id", "title", "title_en", "summary", "canonical_url", "source_name", "language",
           "published_at", "last_changed_at", "status", "severity", "jurisdictions",
           "terms")  # fmt: skip
DEFAULT_COLUMNS = ("title", "canonical_url", "source_name", "published_at", "last_changed_at",
                   "status", "severity", "jurisdictions", "terms", "summary")  # fmt: skip
_FORMULA = ("=", "+", "-", "@", "\t", "\r")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _bad(message: str) -> ProblemError:
    return ProblemError(400, "invalid-query", message,
                        errors=[ProblemFieldError(field="columns", message=message)])  # fmt: skip


def columns(query: Query) -> tuple[str, ...]:
    wanted = tuple(query.columns or DEFAULT_COLUMNS)
    if unknown := [c for c in wanted if c not in COLUMNS]:
        raise _bad(f"unknown column {unknown[0][:40]!r}")
    if len(wanted) > len(COLUMNS) or len(set(wanted)) != len(wanted):
        raise _bad("each column at most once")
    return wanted


def cell(value: Any) -> str:  # noqa: ANN401 - any field
    """A safe cell: text, no control characters, never read as a formula."""
    if value is None:
        return ""
    out = _CONTROL.sub("", value.isoformat() if hasattr(value, "isoformat") else str(value))
    return "'" + out if out.startswith(_FORMULA) else out


def row(item: ItemSummary, wanted: tuple[str, ...]) -> list[str]:
    fields: dict[str, Any] = {
        "jurisdictions": "; ".join(j.code for j in item.jurisdictions or []),
        "terms": "; ".join(f"{t.facet_key}:{t.key}" for t in item.terms or []),
    }
    return [cell(fields[c] if c in fields else getattr(item, c, None)) for c in wanted]


async def prepare(db: AsyncSession, query: Query, user_id: uuid.UUID | None) -> tuple[str, ...]:
    """Everything that can refuse, before the stream starts (a 400 or 429, never a broken file)."""
    check(query.model_copy(update={"page": 1, "page_size": 1}))
    wanted = columns(query)
    services.limited(user_id)
    await resolve_terms(db, query.filters)  # an unknown facet is a 400 here
    return wanted


async def stream(factory: async_sessionmaker[AsyncSession], query: Query,
                 wanted: tuple[str, ...]) -> AsyncIterator[bytes]:  # fmt: skip
    async with factory() as db:
        await db.execute(text(f"SET LOCAL statement_timeout = '{services.STATEMENT_TIMEOUT}'"))
        cap_value = (await values(db, ["search.export_row_cap"]))["search.export_row_cap"]
        cap = int(cap_value) if isinstance(cap_value, int) and cap_value > 0 else DEFAULT_CAP
        compiled = compile_query(query, await resolve_terms(db, query.filters))
        start, end = period(query.filters)
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(wanted)
        yield ("﻿" + buffer.getvalue()).encode("utf-8")
        # One ordered query read through a server-side cursor, BATCH ids at a time: no OFFSET
        # rescans, and memory stays flat (acceptance 4).
        result = await db.stream_scalars(compiled.ids.limit(cap))
        async for ids in result.partitions(BATCH):
            batch = list(ids)
            found = await services.summaries(db, batch, start, end)
            buffer.seek(0)
            buffer.truncate()
            for item_id in batch:
                if (summary := found.get(item_id)) is not None:
                    writer.writerow(row(summary, wanted))
            yield buffer.getvalue().encode("utf-8")
            db.expunge_all()
