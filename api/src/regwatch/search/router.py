"""Search, CSV export, map activity and saved view routes; mounted under /api/v1.

``POST /search`` is implemented (M5); the others answer 501 until their slice.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Query

from regwatch.core.db import DbSession
from regwatch.core.routing import not_implemented, spec
from regwatch.identity.permissions import CurrentPrincipal
from regwatch.search import services
from regwatch.search.schemas import MapActivity, SavedView, SavedViewWrite, SearchResult
from regwatch.search.schemas import Query as SearchQuery

router = APIRouter(tags=["search"])
READ = "items.read"


@router.post("/search", **spec(SearchResult, desc="Results", perm=READ, errors=(400,), stub=False))
async def search(body: SearchQuery, principal: CurrentPrincipal, db: DbSession) -> SearchResult:
    return await services.search(db, body, principal.user.id)


@router.post(
    "/search/export.csv",
    **spec(desc="Streaming CSV (UTF-8 with BOM, formula-injection escaped)", perm="outputs.csv",
           content="text/csv"),
)  # fmt: skip
async def export_csv(body: SearchQuery) -> NoReturn:
    not_implemented()


@router.get("/map/activity", **spec(MapActivity, desc="Per-jurisdiction activity", perm=READ))
async def map_activity(
    period_days: Annotated[int, Query(ge=1, le=3660)] = 30,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    filters: Annotated[str | None, Query(description="URL-encoded JSON of Query.filters")] = None,
    view_by: str = "country",
) -> NoReturn:
    not_implemented()


@router.get("/views", **spec(list[SavedView], desc="Own and shared views", perm=READ))
async def list_views() -> NoReturn:
    not_implemented()


@router.post("/views", **spec(SavedView, status=201, desc="Created", perm=READ))
async def create_view(body: SavedViewWrite) -> NoReturn:
    not_implemented()


@router.patch(
    "/views/{id}",
    **spec(SavedView, desc="Updated (shared views need views.manage_shared)", perm=READ),
)
async def update_view(id: UUID, body: SavedViewWrite) -> NoReturn:
    not_implemented()


@router.delete("/views/{id}", **spec(status=204, desc="Deleted", perm=READ))
async def delete_view(id: UUID) -> NoReturn:
    not_implemented()
