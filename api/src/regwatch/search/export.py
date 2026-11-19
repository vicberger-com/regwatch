"""``POST /search/export.csv`` (M5 acceptance 4; Q2: metadata plus summary, no full text).

- The search's query, its checks, its rate and its timeout per statement; at most
  ``search.export_row_cap`` rows (50,000), in the search's order.
- Streamed: ids are read ``BATCH`` at a time from one ordered query, their rows written and
  sent, so memory stays flat however many rows (acceptance 4: under 300 MB).
- UTF-8 with a BOM, so spreadsheet programs read it; every cell that starts with ``=``, ``+``,
  ``-``, ``@``, a tab or a carriage return is prefixed with ``'`` (formula injection), and
  control characters are removed.
- ``columns`` picks from ``COLUMNS`` in that order; unknown names are a 400.
- The stream never holds a connection while the client reads (slice 2 review S1): the ids
  (at most the cap, about 4 MB) are read in one statement and that transaction ends; each
  batch then reads its rows in a short transaction of its own. A whole export has
  ``DEADLINE_S``; at most ``PER_USER`` exports run per user and ``AT_ONCE`` in all (429 beyond).
- ``outputs`` rate (8.2, S2): ``OUTPUT_RATE`` exports an hour per user; each is audited as
  ``search.export`` with its query hash and columns.
- Relevance ranks only the first 10,000 matches, so an export asked for by relevance is written
  newest change first (S6), and says so in ``X-Regwatch-Order``.
- A timeout in the middle ends the file with a ``#`` line saying it stopped (S9).
"""

from __future__ import annotations

import csv
import io
import re
import time
import unicodedata
import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from regwatch.admin.services import values
from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.core.services import audit
from regwatch.identity.services import SlidingWindow
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
_FORMULA = ("=", "+", "-", "@", "\t", "\r", "＝", "＋", "－", "＠")
OUTPUT_RATE = 20  # an hour per user (08 security 8.2)
outputs = SlidingWindow(3600.0)
PER_USER = 1
AT_ONCE = 4
DEADLINE_S = 600.0
_running: dict[str, list[float]] = {}  # start times; a never-started stream expires


def _live() -> dict[str, list[float]]:
    cutoff = time.monotonic() - DEADLINE_S - 60
    for key in list(_running):
        _running[key] = [t for t in _running[key] if t > cutoff]
        if not _running[key]:
            del _running[key]
    return _running


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
    """A safe cell: text, no control characters, never read as a formula, even after leading
    spaces or invisible format characters (S8)."""
    if value is None:
        return ""
    out = _CONTROL.sub("", value.isoformat() if hasattr(value, "isoformat") else str(value))
    at = 0
    while at < len(out) and (out[at] in " \u00a0\u3000" or unicodedata.category(out[at]) == "Cf"):
        at += 1
    return "'" + out if out[at:].startswith(_FORMULA) else out


def row(item: ItemSummary, wanted: tuple[str, ...]) -> list[str]:
    fields: dict[str, Any] = {
        "jurisdictions": "; ".join(j.code for j in item.jurisdictions or []),
        "terms": "; ".join(f"{t.facet_key}:{t.key}" for t in item.terms or []),
    }
    return [cell(fields[c] if c in fields else getattr(item, c, None)) for c in wanted]


def ordered(query: Query) -> Query:
    """Relevance ranks only the first matches; an export is written newest change first (S6)."""
    return (
        query.model_copy(update={"sort": "last_changed_desc"})
        if query.sort == "relevance"
        else query
    )


async def prepare(db: AsyncSession, query: Query, user_id: uuid.UUID | None,
                  ip: str | None = None) -> tuple[str, ...]:  # fmt: skip
    """Everything that can refuse, before the stream starts (a 400 or 429, never a broken file)."""
    check(query.model_copy(update={"page": 1, "page_size": 1}))
    wanted = columns(query)
    await resolve_terms(db, query.filters)  # an unknown facet is a 400 here
    key = str(user_id)
    if outputs.count(key) >= OUTPUT_RATE:
        raise ProblemError(429, "rate-limited", "Too many exports; try again later.",
                           headers={"Retry-After": str(outputs.retry_after(key))})  # fmt: skip
    live = _live()
    if len(live.get(key, [])) >= PER_USER or sum(map(len, live.values())) >= AT_ONCE:
        raise ProblemError(429, "rate-limited", "An export is already running; try again soon.",
                           headers={"Retry-After": "30"})  # fmt: skip
    outputs.hit(key)
    audit(db, "search.export", "search", None, actor=user_id, ip=ip,
          after={"query_hash": services.query_hash(query), "columns": list(wanted)})  # fmt: skip
    await db.commit()
    _running.setdefault(key, []).append(time.monotonic())
    return wanted


def release(user_id: uuid.UUID | None) -> None:
    key = str(user_id)
    if _running.get(key):
        _running[key].pop(0)
        if not _running[key]:
            del _running[key]


async def stream(
    factory: async_sessionmaker[AsyncSession],
    query: Query,
    wanted: tuple[str, ...],
    user_id: uuid.UUID | None = None,
) -> AsyncIterator[bytes]:
    """The file, batch by batch; releases the export's slot however it ends."""
    query = ordered(query)
    deadline = time.monotonic() + DEADLINE_S
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    try:
        writer.writerow(wanted)
        yield ("\ufeff" + buffer.getvalue()).encode("utf-8")
        try:
            async with factory() as db:  # one statement for the ids, then the connection goes
                await db.execute(
                    text(f"SET LOCAL statement_timeout = '{services.STATEMENT_TIMEOUT}'")
                )
                cap_value = (await values(db, ["search.export_row_cap"]))["search.export_row_cap"]
                cap = (
                    int(cap_value) if isinstance(cap_value, int) and cap_value > 0 else DEFAULT_CAP
                )
                compiled = compile_query(query, await resolve_terms(db, query.filters))
                ids = list((await db.scalars(compiled.ids.limit(cap))).all())
            start, end = period(query.filters)
            for at in range(0, len(ids), BATCH):
                if time.monotonic() > deadline:
                    raise TimeoutError
                async with factory() as db:  # a short transaction per batch
                    await db.execute(text(f"SET LOCAL statement_timeout = "
                                          f"'{services.STATEMENT_TIMEOUT}'"))  # fmt: skip
                    batch = ids[at : at + BATCH]
                    found = await services.summaries(db, batch, start, end)
                buffer.seek(0)
                buffer.truncate()
                for item_id in batch:
                    if (summary := found.get(item_id)) is not None:
                        writer.writerow(row(summary, wanted))
                yield buffer.getvalue().encode("utf-8")
        except (TimeoutError, DBAPIError) as exc:
            if isinstance(exc, DBAPIError) and getattr(exc.orig, "sqlstate", None) != "57014":
                raise
            yield b"#export stopped: it took too long; narrow the query\r\n"  # S9
    finally:
        release(user_id)
