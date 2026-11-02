"""Item detail, version, diff and tagging routes; mounted under /api/v1. Stubs until M4."""

from __future__ import annotations

from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Query

from regwatch.core.routing import not_implemented, spec
from regwatch.processing.schemas import ItemDetail, ItemDiff, ItemVersion, TagsUpdate

router = APIRouter(tags=["items"])
READ = "items.read"


@router.get("/items/{id}", **spec(ItemDetail, desc="Item", perm=READ, errors=(404,)))
async def get_item(id: UUID) -> NoReturn:
    not_implemented()


@router.get(
    "/items/{id}/versions", **spec(list[ItemVersion], desc="Versions newest first", perm=READ)
)
async def list_item_versions(id: UUID) -> NoReturn:
    not_implemented()


@router.get("/items/{id}/diff", **spec(ItemDiff, desc="Unified diff of plain text", perm=READ))
async def item_diff(
    id: UUID, from_: Annotated[int, Query(alias="from")], to: Annotated[int, Query()]
) -> NoReturn:
    not_implemented()


@router.post("/items/{id}/reprocess", **spec(status=202, desc="Queued", perm="items.reprocess"))
async def reprocess_item(id: UUID) -> NoReturn:
    not_implemented()


@router.put("/items/{id}/tags", **spec(ItemDetail, desc="Updated item", perm="items.tag"))
async def update_item_tags(id: UUID, body: TagsUpdate) -> NoReturn:
    not_implemented()
