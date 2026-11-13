"""Facet, term and jurisdiction routes; mounted under /api/v1.

Facets, terms, merge, the rule test, view dimensions, jurisdictions and regions are implemented
(M2); import and export answer 501 until M2 lands.
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


@router.get(
    "/taxonomy/facets/{key}/terms", **spec(list[Term], desc="Terms", perm=READ, stub=False)
)  # fmt: skip
async def list_terms(
    key: str, db: DbSession, flat: bool = False, include_inactive: bool = False
) -> list[Term]:
    return await services.list_terms(db, key, flat=flat, include_inactive=include_inactive)


@router.post(
    "/taxonomy/facets/{key}/terms",
    **spec(Term, status=201, desc="Created", perm=MANAGE, stub=False),
)  # fmt: skip
async def create_term(
    key: str, body: TermWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Term:
    changes = body.model_dump(exclude_unset=True)
    return await services.create_term(db, key, changes, principal.user.id, client_ip(request))


@router.patch("/taxonomy/terms/{id}", **spec(Term, desc="Updated", perm=MANAGE, stub=False))
async def update_term(
    id: UUID, body: TermWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Term:
    changes = body.model_dump(exclude_unset=True)
    return await services.update_term(db, id, changes, principal.user.id, client_ip(request))


@router.delete(
    "/taxonomy/terms/{id}",
    **spec(status=204, desc="Deleted or deactivated when referenced", perm=MANAGE, stub=False),
)
async def delete_term(
    id: UUID, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Response:
    await services.delete_term(db, id, principal.user.id, client_ip(request))
    return Response(status_code=204)


@router.post(
    "/taxonomy/terms/{id}/merge",
    **spec(MergeResult, desc="Items re-tagged", perm=MANAGE, stub=False),
)  # fmt: skip
async def merge_term(
    id: UUID, body: TermMerge, principal: CurrentPrincipal, request: Request, db: DbSession
) -> MergeResult:
    moved = await services.merge_term(
        db, id, body.into_term_id, principal.user.id, client_ip(request)
    )
    return MergeResult(items_moved=moved)


@router.post(
    "/taxonomy/terms/{id}/test-rules",
    **spec(RuleTestResult, desc="Rule evaluation", perm=MANAGE, stub=False),
)
async def test_rules(id: UUID, body: RuleTest, db: DbSession) -> RuleTestResult:
    return await services.run_rule_test(db, id, body.text, body.language)


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


@router.get(
    "/jurisdictions", **spec(list[Jurisdiction], desc="Jurisdictions", perm=READ, stub=False)
)  # fmt: skip
async def list_jurisdictions(
    db: DbSession,
    kind: Literal["country", "subdivision", "supranational"] | None = None,
    active: bool | None = None,
) -> list[Jurisdiction]:
    return await services.list_jurisdictions(db, kind, active)


@router.post(
    "/jurisdictions", **spec(Jurisdiction, status=201, desc="Created", perm=MANAGE, stub=False)
)  # fmt: skip
async def create_jurisdiction(
    body: JurisdictionWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Jurisdiction:
    values = body.model_dump(exclude_unset=True)
    return await services.create_jurisdiction(db, values, principal.user.id, client_ip(request))


# Registered before /jurisdictions/{code} so the literal path wins.
@router.get(
    "/jurisdictions/regions",
    **spec(list[Region], desc="UN M49 regions with member codes", perm=READ, stub=False),
)
async def list_regions(db: DbSession) -> list[Region]:
    return await services.list_regions(db)


@router.get(
    "/jurisdictions/{code}",
    **spec(Jurisdiction, desc="Jurisdiction", perm=READ, errors=(404,), stub=False),
)
async def get_jurisdiction(code: str, db: DbSession) -> Jurisdiction:
    return await services.get_jurisdiction(db, code)


@router.patch(
    "/jurisdictions/{code}", **spec(Jurisdiction, desc="Updated", perm=MANAGE, stub=False)
)  # fmt: skip
async def update_jurisdiction(
    code: str, body: JurisdictionWrite, principal: CurrentPrincipal, request: Request,
    db: DbSession,
) -> Jurisdiction:  # fmt: skip
    changes = body.model_dump(exclude_unset=True)
    return await services.update_jurisdiction(
        db, code, changes, principal.user.id, client_ip(request)
    )
