"""Search, CSV export, map activity and saved view routes; mounted under /api/v1.

Every route is implemented (M5).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse

from regwatch.core.db import DbSession
from regwatch.core.routing import spec
from regwatch.identity.permissions import CurrentPrincipal
from regwatch.identity.services import client_ip
from regwatch.search import activity, export, services, views
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
           content="text/csv", stub=False),
)  # fmt: skip
async def export_csv(
    body: SearchQuery, principal: CurrentPrincipal, request: Request, db: DbSession
) -> StreamingResponse:
    wanted, slot = await export.prepare(db, body, principal.user.id, client_ip(request))
    return StreamingResponse(
        export.stream(request.app.state.db, body, wanted, principal.user.id, slot),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="regwatch-export.csv"',
                 "X-Content-Type-Options": "nosniff",
                 "X-Regwatch-Order": export.ordered(body).sort},
    )  # fmt: skip


@router.get(
    "/map/activity",
    **spec(MapActivity, desc="Per-jurisdiction activity", perm=READ, stub=False),
)
async def map_activity(
    principal: CurrentPrincipal,
    db: DbSession,
    period_days: Annotated[int, Query(ge=1, le=3660)] = 30,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    filters: Annotated[str | None, Query(description="URL-encoded JSON of Query.filters")] = None,
    view_by: str = "country",
) -> MapActivity:
    return await activity.activity(db, principal.user.id, period_days, from_, to, filters,
                                   view_by)  # fmt: skip


@router.get("/views", **spec(list[SavedView], desc="Own and shared views", perm=READ, stub=False))
async def list_views(principal: CurrentPrincipal, db: DbSession) -> list[SavedView]:
    return await views.list_views(db, principal)


@router.post("/views", **spec(SavedView, status=201, desc="Created", perm=READ, stub=False))
async def create_view(
    body: SavedViewWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> SavedView:
    return await views.create_view(db, body, principal, client_ip(request))


@router.patch(
    "/views/{id}",
    **spec(SavedView, desc="Updated (shared views need views.manage_shared)", perm=READ,
           stub=False),
)  # fmt: skip
async def update_view(
    id: UUID, body: SavedViewWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> SavedView:
    return await views.update_view(db, id, body, principal, client_ip(request))


@router.delete("/views/{id}", **spec(status=204, desc="Deleted", perm=READ, stub=False))
async def delete_view(
    id: UUID, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Response:
    await views.delete_view(db, id, principal, client_ip(request))
    return Response(status_code=204)
