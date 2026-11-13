"""Facet, term and jurisdiction routes; mounted under /api/v1.

Facets and view dimensions are implemented (M2); the other stubs answer 501 until M2 lands.
"""

from __future__ import annotations

from typing import Literal, NoReturn
from uuid import UUID

from fastapi import APIRouter, Request, Response

from regwatch.core.db import DbSession
from regwatch.core.routing import not_implemented, raw_body, spec
from regwatch.identity.permissions import CurrentPrincipal
from regwatch.identity.services import client_ip
from regwatch.taxonomy import services
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


@router.get(
    "/taxonomy/facets",
    **spec(list[Facet], desc="Facets with terms as a tree", perm=READ, stub=False),
)  # fmt: skip
async def list_facets(db: DbSession) -> list[Facet]:
    return await services.list_facets(db)


@router.post(
    "/taxonomy/facets", **spec(Facet, status=201, desc="Created", perm=MANAGE, stub=False)
)  # fmt: skip
async def create_facet(
    body: FacetWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Facet:
    return await services.create_facet(db, body, principal.user.id, client_ip(request))


@router.patch("/taxonomy/facets/{key}", **spec(Facet, desc="Updated", perm=MANAGE, stub=False))
async def update_facet(
    key: str, body: FacetWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Facet:
    return await services.update_facet(db, key, body, principal.user.id, client_ip(request))


@router.delete(
    "/taxonomy/facets/{key}",
    **spec(status=204, desc="Deleted", perm=MANAGE, errors=(409,),
           error_desc={409: "System facet or in use; hide instead"}, stub=False),
)  # fmt: skip
async def delete_facet(
    key: str, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Response:
    await services.delete_facet(db, key, principal.user.id, client_ip(request))
    return Response(status_code=204)


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
    **spec(list[ViewDimension], desc="Dimensions for the view selector", perm=READ, stub=False),
)
async def list_view_dimensions(db: DbSession) -> list[ViewDimension]:
    return await services.view_dimensions(db)


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
