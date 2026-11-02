"""Facet, term and jurisdiction routes; mounted under /api/v1. Stubs answer 501 until M2."""

from __future__ import annotations

from typing import Literal, NoReturn
from uuid import UUID

from fastapi import APIRouter

from regwatch.core.routing import not_implemented, raw_body, spec
from regwatch.taxonomy.schemas import (
    Facet,
    FacetWrite,
    ImportSummary,
    Jurisdiction,
    JurisdictionWrite,
    MergeResult,
    Region,
    RuleTest,
    RuleTestResult,
    Term,
    TermMerge,
    TermWrite,
    ViewDimension,
)

router = APIRouter(tags=["taxonomy"])
READ, MANAGE = "taxonomy.read", "taxonomy.manage"
YAML = "application/yaml"


@router.get("/taxonomy/facets", **spec(list[Facet], desc="Facets with terms as a tree", perm=READ))
async def list_facets() -> NoReturn:
    not_implemented()


@router.post("/taxonomy/facets", **spec(Facet, status=201, desc="Created", perm=MANAGE))
async def create_facet(body: FacetWrite) -> NoReturn:
    not_implemented()


@router.patch("/taxonomy/facets/{key}", **spec(Facet, desc="Updated", perm=MANAGE))
async def update_facet(key: str, body: FacetWrite) -> NoReturn:
    not_implemented()


@router.delete(
    "/taxonomy/facets/{key}",
    **spec(status=204, desc="Deleted", perm=MANAGE, errors=(409,),
           error_desc={409: "System facet or in use; hide instead"}),
)  # fmt: skip
async def delete_facet(key: str) -> NoReturn:
    not_implemented()


@router.get("/taxonomy/facets/{key}/terms", **spec(list[Term], desc="Terms", perm=READ))
async def list_terms(key: str, flat: bool = False, include_inactive: bool = False) -> NoReturn:
    not_implemented()


@router.post("/taxonomy/facets/{key}/terms", **spec(Term, status=201, desc="Created", perm=MANAGE))
async def create_term(key: str, body: TermWrite) -> NoReturn:
    not_implemented()


@router.patch("/taxonomy/terms/{id}", **spec(Term, desc="Updated", perm=MANAGE))
async def update_term(id: UUID, body: TermWrite) -> NoReturn:
    not_implemented()


@router.delete(
    "/taxonomy/terms/{id}",
    **spec(status=204, desc="Deleted or deactivated when referenced", perm=MANAGE),
)
async def delete_term(id: UUID) -> NoReturn:
    not_implemented()


@router.post("/taxonomy/terms/{id}/merge", **spec(MergeResult, desc="Items re-tagged", perm=MANAGE))
async def merge_term(id: UUID, body: TermMerge) -> NoReturn:
    not_implemented()


@router.post(
    "/taxonomy/terms/{id}/test-rules", **spec(RuleTestResult, desc="Rule evaluation", perm=MANAGE)
)
async def test_rules(id: UUID, body: RuleTest) -> NoReturn:
    not_implemented()


@router.get(
    "/taxonomy/view-dimensions",
    **spec(list[ViewDimension], desc="Dimensions for the view selector", perm=READ),
)
async def list_view_dimensions() -> NoReturn:
    not_implemented()


@router.post(
    "/taxonomy/import",
    **spec(ImportSummary, desc="Import summary", perm=MANAGE,
           body=raw_body(YAML, {"type": "string"})),
)  # fmt: skip
async def import_taxonomy() -> NoReturn:
    not_implemented()


@router.get("/taxonomy/export", **spec(desc="YAML export", perm=READ, content=YAML))
async def export_taxonomy() -> NoReturn:
    not_implemented()


@router.get("/jurisdictions", **spec(list[Jurisdiction], desc="Jurisdictions", perm=READ))
async def list_jurisdictions(
    kind: Literal["country", "subdivision", "supranational"] | None = None,
    active: bool | None = None,
) -> NoReturn:
    not_implemented()


@router.post("/jurisdictions", **spec(Jurisdiction, status=201, desc="Created", perm=MANAGE))
async def create_jurisdiction(body: JurisdictionWrite) -> NoReturn:
    not_implemented()


# Registered before /jurisdictions/{code} so the literal path wins.
@router.get(
    "/jurisdictions/regions",
    **spec(list[Region], desc="UN M49 regions with member codes", perm=READ),
)
async def list_regions() -> NoReturn:
    not_implemented()


@router.get(
    "/jurisdictions/{code}", **spec(Jurisdiction, desc="Jurisdiction", perm=READ, errors=(404,))
)
async def get_jurisdiction(code: str) -> NoReturn:
    not_implemented()


@router.patch("/jurisdictions/{code}", **spec(Jurisdiction, desc="Updated", perm=MANAGE))
async def update_jurisdiction(code: str, body: JurisdictionWrite) -> NoReturn:
    not_implemented()
