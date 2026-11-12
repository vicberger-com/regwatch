"""Facet, term and jurisdiction persistence behind the M2 routes (REQ-03, REQ-11).

Business rules raise :class:`ProblemError`: 404 for unknown keys, 409 for duplicates and
for deleting a system or referenced facet, 422 naming the field otherwise. Every write ends
in ``services.commit_change`` so attribute-validation caches follow (cache.py).
"""

from __future__ import annotations

import math
import re
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.taxonomy import models as m
from regwatch.taxonomy import schemas as s
from regwatch.taxonomy.services import commit_change

TERM_KEY = re.compile(r"[a-z0-9][a-z0-9_-]{0,60}")
CODE = re.compile(r"[A-Z0-9]{2,4}(-[A-Z0-9]{1,3})?")
GEOMETRY_REF = re.compile(r"[A-Z]{3}")
INT32 = 2**31 - 1
BUILTIN_DIMENSIONS = [("country", "Country"), ("region", "Region"), ("regulation", "Regulation")]
# UN M49 sub-regions used by the jurisdiction seed (UNSD M49 overview, read 2026-11-02).
M49 = {"015": "Northern Africa", "021": "Northern America", "030": "Eastern Asia",
       "034": "Southern Asia", "035": "South-eastern Asia", "039": "Southern Europe",
       "053": "Australia and New Zealand", "054": "Melanesia", "057": "Micronesia",
       "061": "Polynesia", "143": "Central Asia", "145": "Western Asia",
       "151": "Eastern Europe", "154": "Northern Europe", "155": "Western Europe",
       "202": "Sub-Saharan Africa", "419": "Latin America and the Caribbean"}  # fmt: skip
_FACET_IN_USE = text(
    "SELECT EXISTS (SELECT 1 FROM item_term it JOIN term t ON t.id = it.term_id"
    " WHERE t.facet_id = :fid) OR EXISTS (SELECT 1 FROM item WHERE attributes ? :key)"
    " OR EXISTS (SELECT 1 FROM source s JOIN term t ON t.id = ANY (s.default_term_ids)"
    " WHERE t.facet_id = :fid)"
)


def invalid(field: str, message: str) -> ProblemError:
    errors = [ProblemFieldError(field=field, message=message)]
    return ProblemError(422, "validation", "The request failed validation.", errors=errors)


def _not_found(what: str) -> ProblemError:
    return ProblemError(404, "not-found", f"No such {what}.")


def _clean(body: dict[str, Any], path: str = "") -> None:
    """PostgreSQL text and jsonb cannot hold NUL; numbers must fit their columns."""
    for key, value in body.items():
        where = f"{path}{key}"
        if isinstance(value, str) and "\x00" in value:
            raise invalid(where, "must not contain NUL")
        if isinstance(value, list):
            _clean({f"[{i}]": v for i, v in enumerate(value)}, where)
        if isinstance(value, dict):
            _clean(value, where + ".")
        if isinstance(value, float) and not math.isfinite(value):
            raise invalid(where, "must be finite")
        if isinstance(value, int) and not isinstance(value, bool) and abs(value) > INT32:
            raise invalid(where, "is out of range")


def _required(body: dict[str, Any], *names: str) -> None:
    for name in names:
        if body.get(name) is None:
            raise invalid(name, "is required")


async def _commit(session: AsyncSession, conflict: str) -> None:
    try:
        await commit_change(session)
    except IntegrityError as exc:
        raise ProblemError(409, "conflict", conflict) from exc


# --- facets -------------------------------------------------------------------------------


def facet_out(f: m.Facet, terms: list[s.Term] | None = None) -> s.Facet:
    fields = ("id", "key", "label", "value_type", "multi", "required", "show_in_view_selector",
              "show_in_filters", "sort_order", "system", "hidden")  # fmt: skip
    out = s.Facet(**{k: getattr(f, k) for k in fields})
    if terms is not None:
        out.terms = terms
    return out


async def get_facet(session: AsyncSession, key: str) -> m.Facet:
    facet = await session.scalar(select(m.Facet).where(m.Facet.key == key))
    if facet is None:
        raise _not_found("facet")
    return facet


async def list_facets(session: AsyncSession) -> list[s.Facet]:
    facets = (
        await session.scalars(select(m.Facet).order_by(m.Facet.sort_order, m.Facet.key))
    ).all()
    terms = await list_terms(session, None, tree=True, include_inactive=False)
    by_facet: dict[str, list[s.Term]] = {}
    for t in terms:
        by_facet.setdefault(t.facet_key, []).append(t)
    return [facet_out(f, by_facet.get(f.key, [])) for f in facets]


async def create_facet(session: AsyncSession, body: s.FacetWrite) -> s.Facet:
    data = body.model_dump(exclude_unset=True)
    _clean(data)
    _required(data, "key", "label", "value_type")
    if await session.scalar(select(m.Facet.id).where(m.Facet.key == data["key"])):
        raise ProblemError(409, "conflict", "A facet with this key exists.")
    defaults = {"multi": True, "required": False, "show_in_view_selector": False,
                "show_in_filters": True, "sort_order": 100, "hidden": False}  # fmt: skip
    facet = m.Facet(**{**defaults, **data, "system": False})
    session.add(facet)
    await _commit(session, "A facet with this key exists.")
    return facet_out(facet)


async def update_facet(session: AsyncSession, key: str, body: s.FacetWrite) -> s.Facet:
    facet = await get_facet(session, key)
    data = body.model_dump(exclude_unset=True)
    _clean(data)
    if data.get("key", key) != key:
        raise invalid("key", "cannot change; create a new facet instead")
    value_type = data.get("value_type", facet.value_type)
    if value_type != facet.value_type and (
        facet.system or await session.scalar(select(m.Term.id).where(m.Term.facet_id == facet.id))
    ):
        raise invalid("value_type", "cannot change on a system facet or one with terms")
    for name, value in data.items():
        setattr(facet, name, value)
    await _commit(session, "The facet changed concurrently.")
    return facet_out(facet)


async def delete_facet(session: AsyncSession, key: str) -> None:
    facet = await get_facet(session, key)
    if facet.system:
        raise ProblemError(409, "conflict", "System facets cannot be deleted; hide them instead.")
    if await session.scalar(_FACET_IN_USE, {"fid": facet.id, "key": key}):
        raise ProblemError(409, "conflict", "The facet is in use; hide it instead.")
    await session.delete(facet)
    await _commit(session, "The facet is in use; hide it instead.")


async def view_dimensions(session: AsyncSession) -> list[s.ViewDimension]:
    rows = await session.execute(
        select(m.Facet.key, m.Facet.label)
        .where(m.Facet.show_in_view_selector.is_(True), m.Facet.hidden.is_(False))
        .order_by(m.Facet.sort_order, m.Facet.key)
    )
    builtin = [
        s.ViewDimension(key=k, label=label, kind="builtin") for k, label in BUILTIN_DIMENSIONS
    ]
    return builtin + [s.ViewDimension(key=k, label=label, kind="facet") for k, label in rows]


# --- terms --------------------------------------------------------------------------------


def build_tree(terms: list[s.Term]) -> list[s.Term]:
    """Nest terms under their parents; a term whose parent is absent becomes a root."""
    by_id = {t.id: t for t in terms}
    for t in terms:
        t.children = []
    roots: list[s.Term] = []
    for t in terms:
        parent = by_id.get(t.parent_id) if t.parent_id else None
        (parent.children if parent is not None else roots).append(t)
    return roots


def creates_cycle(
    term_id: UUID, parent_id: UUID | None, parent_of: dict[UUID, UUID | None]
) -> bool:
    """Would making ``parent_id`` the parent of ``term_id`` close a loop?"""
    seen: set[UUID] = set()
    while parent_id is not None and parent_id not in seen:
        if parent_id == term_id:
            return True
        seen.add(parent_id)
        parent_id = parent_of.get(parent_id)
    return parent_id is not None  # an existing loop is a cycle too


def term_out(t: m.Term, facet_key: str, item_count: int | None = None) -> s.Term:
    out = s.Term(id=t.id, facet_key=facet_key, key=t.key, label=t.label, parent_id=t.parent_id,
                 synonyms=list(t.synonyms), match_rules=s.MatchRules(**t.match_rules),
                 color_token=t.color_token, active=t.active)  # fmt: skip
    if item_count is not None:
        out.item_count = item_count
    return out


async def list_terms(
    session: AsyncSession, facet_key: str | None, *, tree: bool, include_inactive: bool
) -> list[s.Term]:
    """Terms of one facet (or all, for ``facet_key=None``) ordered by label."""
    counts = select(m.ItemTerm.term_id, func.count().label("n")).group_by(m.ItemTerm.term_id)
    sub = counts.subquery()
    stmt = (
        select(m.Term, m.Facet.key, func.coalesce(sub.c.n, 0))
        .join(m.Facet, m.Facet.id == m.Term.facet_id)
        .outerjoin(sub, sub.c.term_id == m.Term.id)
        .order_by(m.Term.label, m.Term.key)
    )
    if facet_key is not None:
        await get_facet(session, facet_key)
        stmt = stmt.where(m.Facet.key == facet_key)
    if not include_inactive:
        stmt = stmt.where(m.Term.active.is_(True))
    terms = [term_out(t, fk, n) for t, fk, n in (await session.execute(stmt)).all()]
    return build_tree(terms) if tree else terms


async def _term_rules(session: AsyncSession, facet: m.Facet, data: dict[str, Any]) -> None:
    _clean(data)
    if "key" in data and not TERM_KEY.fullmatch(data["key"]):
        raise invalid("key", "must match ^[a-z0-9][a-z0-9_-]{0,60}$")
    rules = data.get("match_rules") or {}
    for i, pattern in enumerate(rules.get("regex") or []):
        try:
            re.compile(pattern)
        except (re.error, RecursionError, OverflowError):
            raise invalid(f"match_rules.regex[{i}]", "is not a valid regular expression") from None
    if rules.get("min_hits", 1) < 1 or rules.get("weight", 1.0) < 0:
        raise invalid("match_rules", "min_hits must be at least 1 and weight not negative")
    if data.get("parent_id") is not None:
        parent = await session.get(m.Term, data["parent_id"])
        if parent is None or parent.facet_id != facet.id:
            raise invalid("parent_id", "must be a term of the same facet")


async def create_term(session: AsyncSession, facet_key: str, body: s.TermWrite) -> s.Term:
    facet = await get_facet(session, facet_key)
    data = body.model_dump(exclude_unset=True)
    _required(data, "key", "label")
    if facet.value_type != "term":
        raise invalid("key", f"facet {facet_key} holds {facet.value_type} values, not terms")
    await _term_rules(session, facet, data)
    if await session.scalar(
        select(m.Term.id).where(m.Term.facet_id == facet.id, m.Term.key == data["key"])
    ):
        raise ProblemError(409, "conflict", "A term with this key exists in the facet.")
    data.setdefault("synonyms", [])
    data["match_rules"] = data.get("match_rules") or {}
    term = m.Term(facet_id=facet.id, active=data.pop("active", True), **data)
    session.add(term)
    await _commit(session, "A term with this key exists in the facet.")
    return term_out(term, facet_key, 0)


async def update_term(session: AsyncSession, term_id: UUID, body: s.TermWrite) -> s.Term:
    term = await session.get(m.Term, term_id)
    if term is None:
        raise _not_found("term")
    facet = await session.get_one(m.Facet, term.facet_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("key", term.key) != term.key:
        raise invalid("key", "cannot change; merge into a new term instead")
    await _term_rules(session, facet, data)
    if data.get("parent_id") is not None:
        rows = await session.execute(
            select(m.Term.id, m.Term.parent_id).where(m.Term.facet_id == facet.id)
        )
        if creates_cycle(term.id, data["parent_id"], dict(rows.tuples().all())):
            raise invalid("parent_id", "would make the term its own ancestor")
    for name, value in data.items():
        setattr(term, name, {} if name == "match_rules" and value is None else value)
    await _commit(session, "The term changed concurrently.")
    return term_out(term, facet.key)


# --- jurisdictions ------------------------------------------------------------------------


async def jurisdiction_out(session: AsyncSession, j: m.Jurisdiction) -> s.Jurisdiction:
    parent = await session.get(m.Jurisdiction, j.parent_id) if j.parent_id else None
    return s.Jurisdiction(id=j.id, code=j.code, name=j.name, kind=j.kind,
                          parent_code=parent.code if parent else None, region_code=j.region_code,
                          geometry_ref=j.geometry_ref, active=j.active)  # fmt: skip


async def get_jurisdiction(session: AsyncSession, code: str) -> m.Jurisdiction:
    j = await session.scalar(select(m.Jurisdiction).where(m.Jurisdiction.code == code))
    if j is None:
        raise _not_found("jurisdiction")
    return j


async def list_jurisdictions(
    session: AsyncSession, kind: str | None, active: bool | None
) -> list[s.Jurisdiction]:
    parent = aliased(m.Jurisdiction)
    stmt = (
        select(m.Jurisdiction, parent.code)
        .outerjoin(parent, parent.id == m.Jurisdiction.parent_id)
        .order_by(m.Jurisdiction.code)
    )
    if kind is not None:
        stmt = stmt.where(m.Jurisdiction.kind == kind)
    if active is not None:
        stmt = stmt.where(m.Jurisdiction.active.is_(active))
    return [
        s.Jurisdiction(id=j.id, code=j.code, name=j.name, kind=j.kind, parent_code=pc,
                       region_code=j.region_code, geometry_ref=j.geometry_ref, active=j.active)
        for j, pc in (await session.execute(stmt)).all()
    ]  # fmt: skip


async def _jurisdiction_rules(session: AsyncSession, data: dict[str, Any]) -> None:
    _clean(data)
    if "code" in data and not CODE.fullmatch(data["code"]):
        raise invalid("code", "must be ISO 3166-1 alpha-2, ISO 3166-2 or a custom code like EU")
    if data.get("geometry_ref") is not None and not GEOMETRY_REF.fullmatch(data["geometry_ref"]):
        raise invalid("geometry_ref", "must be a Natural Earth ADM0_A3 id (ADR-0004)")
    if data.get("region_code") is not None and not re.fullmatch(r"\d{3}", data["region_code"]):
        raise invalid("region_code", "must be a three-digit UN M49 code")
    if "parent_code" in data:
        code = data.pop("parent_code")
        data["parent_id"] = None if code is None else (await _parent(session, code)).id


async def _parent(session: AsyncSession, code: str) -> m.Jurisdiction:
    j = await session.scalar(select(m.Jurisdiction).where(m.Jurisdiction.code == code))
    if j is None:
        raise invalid("parent_code", "is not a known jurisdiction")
    return j


async def create_jurisdiction(session: AsyncSession, body: s.JurisdictionWrite) -> s.Jurisdiction:
    data = body.model_dump(exclude_unset=True)
    _required(data, "code", "name", "kind")
    await _jurisdiction_rules(session, data)
    if await session.scalar(select(m.Jurisdiction.id).where(m.Jurisdiction.code == data["code"])):
        raise ProblemError(409, "conflict", "A jurisdiction with this code exists.")
    j = m.Jurisdiction(**{"active": True, **data})
    session.add(j)
    await _commit(session, "A jurisdiction with this code exists.")
    return await jurisdiction_out(session, j)


async def update_jurisdiction(
    session: AsyncSession, code: str, body: s.JurisdictionWrite
) -> s.Jurisdiction:
    j = await get_jurisdiction(session, code)
    data = body.model_dump(exclude_unset=True)
    if data.get("code", code) != code:
        raise invalid("code", "cannot change; the code keys items and the map")
    await _jurisdiction_rules(session, data)
    if data.get("parent_id") == j.id:
        raise invalid("parent_code", "cannot be the jurisdiction itself")
    for name, value in data.items():
        setattr(j, name, value)
    await _commit(session, "The jurisdiction changed concurrently.")
    return await jurisdiction_out(session, j)


async def regions(session: AsyncSession) -> list[s.Region]:
    rows = await session.execute(
        select(m.Jurisdiction.region_code, func.array_agg(m.Jurisdiction.code))
        .where(m.Jurisdiction.region_code.is_not(None), m.Jurisdiction.active.is_(True))
        .group_by(m.Jurisdiction.region_code)
        .order_by(m.Jurisdiction.region_code)
    )
    return [
        s.Region(code=rc, name=M49.get(rc, rc), jurisdiction_codes=sorted(codes))
        for rc, codes in rows.all()
    ]
