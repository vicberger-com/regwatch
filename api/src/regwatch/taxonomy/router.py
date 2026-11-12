"""Facet, term and jurisdiction routes; mounted under /api/v1 (M2, #34).

Routes still answering 501 land in the next M2 pull request. 404 and 409 are documented on
top of the contract until CP-04 (#51) settles them (tests/openapi_semantic.py ACCEPTED).
"""

from __future__ import annotations

from typing import Literal, NoReturn
from uuid import UUID

from fastapi import APIRouter, Response

from regwatch.core.db import Session
from regwatch.core.routing import not_implemented, raw_body, spec
from regwatch.taxonomy import store
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
)
async def list_facets(session: Session) -> list[Facet]:
    return await store.list_facets(session)


@router.post(
    "/taxonomy/facets",
    **spec(Facet, status=201, desc="Created", perm=MANAGE, errors=(409,), stub=False),
)
async def create_facet(body: FacetWrite, session: Session) -> Facet:
    return await store.create_facet(session, body)


@router.patch(
    "/taxonomy/facets/{key}", **spec(Facet, desc="Updated", perm=MANAGE, errors=(404,), stub=False)
)
async def update_facet(key: str, body: FacetWrite, session: Session) -> Facet:
    return await store.update_facet(session, key, body)


@router.delete(
    "/taxonomy/facets/{key}",
    **spec(status=204, desc="Deleted", perm=MANAGE, errors=(404, 409),
           error_desc={409: "System facet or in use; hide instead"}, stub=False),
)  # fmt: skip
async def delete_facet(key: str, session: Session) -> Response:
    await store.delete_facet(session, key)
    return Response(status_code=204)


@router.get(
    "/taxonomy/facets/{key}/terms",
    **spec(list[Term], desc="Terms", perm=READ, errors=(404,), stub=False),
)
async def list_terms(
    key: str, session: Session, flat: bool = False, include_inactive: bool = False
) -> list[Term]:
    return await store.list_terms(session, key, tree=not flat, include_inactive=include_inactive)


@router.post(
    "/taxonomy/facets/{key}/terms",
    **spec(Term, status=201, desc="Created", perm=MANAGE, errors=(404, 409), stub=False),
)
async def create_term(key: str, body: TermWrite, session: Session) -> Term:
    return await store.create_term(session, key, body)


@router.patch(
    "/taxonomy/terms/{id}", **spec(Term, desc="Updated", perm=MANAGE, errors=(404,), stub=False)
)
async def update_term(id: UUID, body: TermWrite, session: Session) -> Term:
    return await store.update_term(session, id, body)


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
async def list_view_dimensions(session: Session) -> list[ViewDimension]:
    return await store.view_dimensions(session)


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


@router.get(
    "/jurisdictions", **spec(list[Jurisdiction], desc="Jurisdictions", perm=READ, stub=False)
)
async def list_jurisdictions(
    session: Session,
    kind: Literal["country", "subdivision", "supranational"] | None = None,
    active: bool | None = None,
) -> list[Jurisdiction]:
    return await store.list_jurisdictions(session, kind, active)


@router.post(
    "/jurisdictions",
    **spec(Jurisdiction, status=201, desc="Created", perm=MANAGE, errors=(409,), stub=False),
)
async def create_jurisdiction(body: JurisdictionWrite, session: Session) -> Jurisdiction:
    return await store.create_jurisdiction(session, body)


# Registered before /jurisdictions/{code} so the literal path wins.
@router.get(
    "/jurisdictions/regions",
    **spec(list[Region], desc="UN M49 regions with member codes", perm=READ, stub=False),
)
async def list_regions(session: Session) -> list[Region]:
    return await store.regions(session)


@router.get(
    "/jurisdictions/{code}",
    **spec(Jurisdiction, desc="Jurisdiction", perm=READ, errors=(404,), stub=False),
)
async def get_jurisdiction(code: str, session: Session) -> Jurisdiction:
    return await store.jurisdiction_out(session, await store.get_jurisdiction(session, code))


@router.patch(
    "/jurisdictions/{code}",
    **spec(Jurisdiction, desc="Updated", perm=MANAGE, errors=(404,), stub=False),
)
async def update_jurisdiction(code: str, body: JurisdictionWrite, session: Session) -> Jurisdiction:
    return await store.update_jurisdiction(session, code, body)
