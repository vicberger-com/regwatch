"""Service layer; other modules call this module only through here (ADR-0001).

Facets (M2): CRUD, the view-selector dimensions, and the ``taxonomy.version`` setting,
bumped in the same transaction as every facet or term change so workers can drop cached
attribute validation (M2 design notes). Reads go to the database each time, so a new facet is
visible in filters and the view selector on the next request (M2 acceptance 1).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.admin.models import Setting
from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.core.services import audit
from regwatch.taxonomy.models import Facet, ItemTerm, Term
from regwatch.taxonomy.schemas import Facet as FacetOut
from regwatch.taxonomy.schemas import FacetWrite, ViewDimension
from regwatch.taxonomy.schemas import Term as TermOut

VERSION_KEY = "taxonomy.version"
# The view selector's own dimensions (screens.md, M6); facet keys may not reuse them.
BUILTIN_DIMENSIONS = (("country", "Country"), ("region", "Region"), ("regulation", "Regulation"))
RESERVED_KEYS = frozenset(k for k, _ in BUILTIN_DIMENSIONS)
FACET_FIELDS = ("label", "value_type", "multi", "required", "show_in_view_selector",
                "show_in_filters", "sort_order", "hidden")  # fmt: skip


def validation(field: str, message: str) -> ProblemError:
    return ProblemError(422, "validation", message,
                        errors=[ProblemFieldError(field=field, message=message)])  # fmt: skip


def not_found(what: str) -> ProblemError:
    return ProblemError(404, "not-found", f"No such {what}.")


async def bump_version(db: AsyncSession, actor: uuid.UUID | None) -> int:
    """Increment ``taxonomy.version`` atomically and return the new value."""
    stmt = insert(Setting).values(key=VERSION_KEY, value=1, updated_by=actor)
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"],
        set_={"value": text("to_jsonb(COALESCE((setting.value #>> '{}')::integer, 0) + 1)"),
              "updated_by": actor, "updated_at": func.now()},
    )  # fmt: skip
    result = await db.execute(stmt.returning(Setting.value))
    return int(result.scalar_one())


def facet_snapshot(facet: Facet) -> dict[str, Any]:
    return {"key": facet.key, **{f: getattr(facet, f) for f in FACET_FIELDS}}


def facet_out(facet: Facet, terms: list[TermOut] | None = None) -> FacetOut:
    out = FacetOut(id=facet.id, key=facet.key, label=facet.label, value_type=facet.value_type,
                   multi=facet.multi, required=facet.required,
                   show_in_view_selector=facet.show_in_view_selector,
                   show_in_filters=facet.show_in_filters, sort_order=facet.sort_order,
                   system=facet.system, hidden=facet.hidden)  # fmt: skip
    if terms is not None:
        out.terms = terms
    return out


def term_out(term: Term, facet_key: str) -> TermOut:
    out = TermOut(id=term.id, facet_key=facet_key, key=term.key, label=term.label,
                  parent_id=term.parent_id, synonyms=list(term.synonyms or []),
                  match_rules=term.match_rules or {}, color_token=term.color_token,
                  active=term.active)  # fmt: skip
    return out


def term_tree(terms: list[Term], facet_key: str) -> list[TermOut]:
    """Terms nested under their parents; terms whose parent is absent become roots."""
    nodes = {t.id: term_out(t, facet_key) for t in terms}
    for node in nodes.values():
        node.children = []
    roots: list[TermOut] = []
    for t in terms:
        node = nodes[t.id]
        parent = nodes.get(t.parent_id) if t.parent_id else None
        (parent.children if parent is not None else roots).append(node)
    return roots


async def facet_by_key(db: AsyncSession, key: str) -> Facet:
    facet = await db.scalar(select(Facet).where(Facet.key == key))
    if facet is None:
        raise not_found("facet")
    return facet


async def list_facets(db: AsyncSession) -> list[FacetOut]:
    facets = (await db.scalars(select(Facet).order_by(Facet.sort_order, Facet.key))).all()
    terms = (await db.scalars(
        select(Term).where(Term.active.is_(True)).order_by(Term.label, Term.key)
    )).all()  # fmt: skip
    by_facet: dict[uuid.UUID, list[Term]] = {}
    for t in terms:
        by_facet.setdefault(t.facet_id, []).append(t)
    return [facet_out(f, term_tree(by_facet.get(f.id, []), f.key)) for f in facets]


async def create_facet(
    db: AsyncSession, body: FacetWrite, actor: uuid.UUID, ip: str | None
) -> FacetOut:
    given = body.model_dump(exclude_unset=True)
    for required in ("key", "label", "value_type"):
        if given.get(required) in (None, ""):
            raise validation(required, f"{required} is required")
    if given["key"] in RESERVED_KEYS:
        raise validation("key", "this key is reserved for a built-in view dimension")
    if await db.scalar(select(Facet.id).where(Facet.key == given["key"])) is not None:
        raise ProblemError(409, "conflict", "A facet with this key exists.")
    defaults = {"multi": True, "required": False, "show_in_view_selector": False,
                "show_in_filters": True, "sort_order": 100, "hidden": False}  # fmt: skip
    facet = Facet(system=False, **{**defaults, **given})
    db.add(facet)
    await db.flush()
    version = await bump_version(db, actor)
    audit(db, "facet.create", "facet", facet.key, actor=actor, ip=ip,
          after={**facet_snapshot(facet), "taxonomy_version": version})  # fmt: skip
    await db.commit()
    return facet_out(facet, [])


async def update_facet(
    db: AsyncSession, key: str, body: FacetWrite, actor: uuid.UUID, ip: str | None
) -> FacetOut:
    facet = await facet_by_key(db, key)
    before = facet_snapshot(facet)
    changes = body.model_dump(exclude_unset=True)
    if "key" in changes and changes["key"] != facet.key:
        raise validation("key", "a facet keeps its key; create a new facet instead")
    if "value_type" in changes and changes["value_type"] != facet.value_type:
        in_use = await db.scalar(select(func.count()).select_from(Term)
                                 .where(Term.facet_id == facet.id))  # fmt: skip
        if facet.system or in_use:
            raise validation("value_type", "the value type of a system facet or one with terms "
                             "cannot change")  # fmt: skip
    for field in FACET_FIELDS:
        if field in changes:
            if changes[field] is None:
                raise validation(field, f"{field} cannot be null")
            setattr(facet, field, changes[field])
    after = facet_snapshot(facet)
    if after != before:
        version = await bump_version(db, actor)
        audit(db, "facet.update", "facet", facet.key, actor=actor, ip=ip, before=before,
              after={**after, "taxonomy_version": version})  # fmt: skip
    await db.commit()
    terms = (await db.scalars(select(Term).where(Term.facet_id == facet.id,
                                                 Term.active.is_(True)))).all()  # fmt: skip
    return facet_out(facet, term_tree(list(terms), facet.key))


async def delete_facet(db: AsyncSession, key: str, actor: uuid.UUID, ip: str | None) -> None:
    facet = await facet_by_key(db, key)
    if facet.system:
        raise ProblemError(409, "conflict", "System facets cannot be deleted; hide them instead.")
    tagged = await db.scalar(
        select(func.count()).select_from(ItemTerm)
        .join(Term, Term.id == ItemTerm.term_id).where(Term.facet_id == facet.id)
    )  # fmt: skip
    if tagged:
        raise ProblemError(409, "conflict",
                           f"{tagged} item tag(s) use this facet; hide it instead.")  # fmt: skip
    before = facet_snapshot(facet)
    # Terms go with the facet (ON DELETE CASCADE); child-first order is not needed for that,
    # but parent links inside the facet must not block it.
    await db.execute(update(Term).where(Term.facet_id == facet.id).values(parent_id=None))
    await db.delete(facet)
    version = await bump_version(db, actor)
    audit(db, "facet.delete", "facet", key, actor=actor, ip=ip, before=before,
          after={"taxonomy_version": version})  # fmt: skip
    await db.commit()


async def view_dimensions(db: AsyncSession) -> list[ViewDimension]:
    facets = (await db.scalars(
        select(Facet).where(Facet.show_in_view_selector.is_(True), Facet.hidden.is_(False))
        .order_by(Facet.sort_order, Facet.key)
    )).all()  # fmt: skip
    builtin = [ViewDimension(key=k, label=label, kind="builtin") for k, label in BUILTIN_DIMENSIONS]
    return builtin + [ViewDimension(key=f.key, label=f.label, kind="facet") for f in facets]
