"""Item detail, version, diff and tagging routes; mounted under /api/v1.

The reads are implemented (M4); reprocessing and tagging are stubs until their slice.
"""

from __future__ import annotations

from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Query

from regwatch.core.db import DbSession
from regwatch.core.routing import not_implemented, spec
from regwatch.processing import services
from regwatch.processing.schemas import ItemDetail, ItemDiff, ItemVersion, TagsUpdate

router = APIRouter(tags=["items"])
READ = "items.read"


@router.get("/items/{id}", **spec(ItemDetail, desc="Item", perm=READ, errors=(404,), stub=False))
async def get_item(id: UUID, db: DbSession) -> ItemDetail:
    return await services.item_detail(db, id)


@router.get(
    "/items/{id}/versions",
    **spec(list[ItemVersion], desc="Versions newest first", perm=READ, stub=False),
)
async def list_item_versions(id: UUID, db: DbSession) -> list[ItemVersion]:
    return await services.item_versions(db, id)


@router.get(
    "/items/{id}/diff", **spec(ItemDiff, desc="Unified diff of plain text", perm=READ, stub=False)
)
async def item_diff(
    id: UUID,
    from_: Annotated[int, Query(alias="from")],
    to: Annotated[int, Query()],
    db: DbSession,
) -> ItemDiff:
    return await services.item_diff(db, id, from_, to)


@router.post("/items/{id}/reprocess", **spec(status=202, desc="Queued", perm="items.reprocess"))
async def reprocess_item(id: UUID) -> NoReturn:
    not_implemented()


@router.put("/items/{id}/tags", **spec(ItemDetail, desc="Updated item", perm="items.tag"))
async def update_item_tags(id: UUID, body: TagsUpdate) -> NoReturn:
    not_implemented()
