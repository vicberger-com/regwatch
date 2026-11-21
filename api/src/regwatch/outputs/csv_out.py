"""CSV outputs (M8.4; REQ-15): a query or saved view exported as a file in the output history.

The file is the one ``POST /search/export.csv`` streams (M5 acceptance 4): the same query
checks, columns, row cap, order, UTF-8 with a BOM, and cells escaped against formula
injection. What differs:
- It runs in the outputs worker, under the requester's *current* rights on each run
  (``outputs.csv`` and ``items.read``; a saved view only while they can still see it).
- A file stops before ``outputs.attachment_max_bytes`` (20 MB by default), between whole
  batches of rows, with a ``#`` line saying so, as the stream ends one that takes too long;
  the job records that it was cut short.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.db import session_factory
from regwatch.core.errors import ProblemError
from regwatch.identity.services import Principal
from regwatch.search.schemas import Query

MAX_BYTES = 20 * 1024 * 1024  # the setting's default; held in the worker's memory, then stored
NEEDS = ("outputs.csv", "items.read")


@dataclass(frozen=True)
class QuerySource:
    """What a CSV job exports, as ``check_source`` hands it on (a layout has a version)."""

    query: Query
    columns: tuple[str, ...]
    name: str = "regwatch export"
    version: int | None = None


async def source(db: AsyncSession, job: Any, principal: Principal) -> QuerySource:  # noqa: ANN401
    """The query a CSV job exports, checked against the principal as they are now."""
    from regwatch.reports.render import data_source_query
    from regwatch.reports.schemas import ReportDataSource
    from regwatch.search import export
    from regwatch.search.query import check, resolve_terms

    if missing := [p for p in NEEDS if p not in principal.permissions]:
        raise ProblemError(403, "forbidden", f"CSV exports need {' and '.join(missing)}.")
    if job.saved_view_id is not None:  # 409 once the view is no longer visible to them
        query = await data_source_query(
            db, ReportDataSource(saved_view_id=job.saved_view_id), principal
        )
    elif job.query is not None and "deleted_source" not in job.query:
        query = Query.model_validate(job.query)
    else:
        raise ProblemError(404, "not-found", "The exported saved view was deleted.")
    check(query.model_copy(update={"page": 1, "page_size": 1}))  # a 400 for a bad query
    wanted = export.columns(query)
    await resolve_terms(db, query.filters)  # an unknown facet is a 400
    return QuerySource(query=query, columns=wanted)


async def build(db: AsyncSession, src: QuerySource,
                max_bytes: int = MAX_BYTES) -> tuple[bytes, bool]:  # fmt: skip
    """The file, and whether it was cut short at ``max_bytes``."""
    from regwatch.search import export

    if db.bind is None:
        raise RuntimeError("a CSV export needs a session bound to an engine")
    chunks: list[bytes] = []
    size = 0
    truncated = False
    stream = export.stream(session_factory(db.bind), src.query, src.columns)  # type: ignore[arg-type]
    try:
        async for chunk in stream:
            if chunks and size + len(chunk) > max_bytes:
                # Cut between the stream's batches, which end at a row: never inside a quoted
                # cell, which may hold a line break.
                truncated = True
                break
            chunks.append(chunk)
            size += len(chunk)
    finally:
        await stream.aclose()
    data = b"".join(chunks)
    if truncated:
        data += f"#export stopped at {max_bytes // (1024 * 1024)} MB; narrow the query\r\n".encode()
    return data, truncated
