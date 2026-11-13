"""Service layer; other modules call this module only through here (ADR-0001).

Facets and terms (M2): CRUD, the view-selector dimensions, and the ``taxonomy.version`` setting,
bumped in the same transaction as every facet or term change so workers can drop cached
attribute validation (M2 design notes). Reads go to the database each time, so a new facet is
visible in filters and the view selector on the next request (M2 acceptance 1).
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.admin.models import Setting
from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.core.schemas import has_control
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


# --- Terms ---------------------------------------------------------------------------------

TERM_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,60}$")
MAX_SYNONYMS, MAX_RULE_ITEMS, MAX_PATTERN = 50, 100, 200
# A quantified group that contains a quantifier or an alternation, such as (a+)+, (\w*)* or
# (a|aa){2,}: the shapes behind catastrophic backtracking. Patterns are entered by
# administrators and run by M4 over captured text, so they are refused here (M2 design notes;
# BL-74 for a linear-time engine, which would make this check unnecessary).
_NESTED_QUANTIFIER = re.compile(r"\((?:[^()\\]|\\.)*[+*}|](?:[^()\\]|\\.)*\)\s*[+*{]")


def normalise_synonyms(values: list[str]) -> list[str]:
    """NFC, trimmed, inner whitespace collapsed, case-insensitive duplicates and blanks dropped."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        value = " ".join(unicodedata.normalize("NFC", raw).split())
        if value and value.casefold() not in seen:
            if len(value) > 200 or has_control(value):
                raise validation("synonyms", "each synonym is one line of up to 200 characters")
            seen.add(value.casefold())
            out.append(value)
    if len(out) > MAX_SYNONYMS:
        raise validation("synonyms", f"at most {MAX_SYNONYMS} synonyms")
    return out


def check_match_rules(rules: dict[str, Any]) -> dict[str, Any]:
    for field in ("keywords", "regex", "languages"):
        items = rules.get(field) or []
        if len(items) > MAX_RULE_ITEMS or any(len(i) > MAX_PATTERN for i in items):
            limit = f"at most {MAX_RULE_ITEMS} entries of up to {MAX_PATTERN} characters"
            raise validation(f"match_rules.{field}", limit)
    for pattern in rules.get("regex") or []:
        if _NESTED_QUANTIFIER.search(pattern):
            raise validation(
                "match_rules.regex", f"nested quantifier in {pattern!r} (backtracking)"
            )
        try:
            re.compile(pattern)
        except re.error as exc:
            raise validation("match_rules.regex", f"invalid pattern {pattern!r}: {exc}") from exc
    if rules.get("min_hits", 1) < 1:
        raise validation("match_rules.min_hits", "must be at least 1")
    weight = rules.get("weight", 1.0)
    if not 0 < weight <= 10:
        raise validation("match_rules.weight", "must be greater than 0 and at most 10")
    return rules


def term_snapshot(term: Term) -> dict[str, Any]:
    return {"key": term.key, "label": term.label,
            "parent_id": str(term.parent_id) if term.parent_id else None,
            "synonyms": list(term.synonyms or []), "match_rules": term.match_rules,
            "color_token": term.color_token, "active": term.active}  # fmt: skip


async def _term_or_404(db: AsyncSession, term_id: uuid.UUID) -> tuple[Term, Facet]:
    found = (await db.execute(
        select(Term, Facet).join(Facet, Facet.id == Term.facet_id).where(Term.id == term_id)
    )).first()  # fmt: skip
    if found is None:
        raise not_found("term")
    return found[0], found[1]


async def _check_parent(db: AsyncSession, term: Term | None, facet: Facet,
                        parent_id: uuid.UUID | None) -> None:  # fmt: skip
    """The parent must be in the same facet and not the term itself or one of its descendants."""
    seen: set[uuid.UUID] = set()
    current = parent_id
    while current is not None:
        if term is not None and current == term.id:
            raise validation("parent_id", "a term cannot be its own ancestor")
        if current in seen:  # pragma: no cover - existing data already cyclic
            raise validation("parent_id", "the hierarchy has a cycle")
        seen.add(current)
        row = (await db.execute(select(Term.facet_id, Term.parent_id)
                                .where(Term.id == current))).first()  # fmt: skip
        if row is None or row[0] != facet.id:
            raise validation("parent_id", "the parent must be a term of the same facet")
        current = row[1]


def _apply(term: Term, changes: dict[str, Any]) -> None:
    if "label" in changes:
        label = (changes["label"] or "").strip()
        if not label or len(label) > 120 or has_control(label):
            raise validation("label", "a label is one line of 1 to 120 characters")
        term.label = label
    if "synonyms" in changes:
        term.synonyms = normalise_synonyms(changes["synonyms"] or [])
    if "match_rules" in changes:
        term.match_rules = check_match_rules(
            {k: v for k, v in (changes["match_rules"] or {}).items() if v is not None}
        )
    if "color_token" in changes:
        token = changes["color_token"]
        if token is not None and not re.fullmatch(r"[a-z][a-z0-9-]{0,40}", token):
            raise validation("color_token", "a design token name such as category-3")
        term.color_token = token
    if "active" in changes:
        if changes["active"] is None:
            raise validation("active", "active cannot be null")
        term.active = changes["active"]


async def _item_counts(db: AsyncSession, term_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    rows = await db.execute(select(ItemTerm.term_id, func.count()).where(
        ItemTerm.term_id.in_(term_ids)).group_by(ItemTerm.term_id))  # fmt: skip
    return {tid: int(n) for tid, n in rows.tuples().all()}


async def list_terms(db: AsyncSession, facet_key: str, *, flat: bool,
                     include_inactive: bool) -> list[TermOut]:  # fmt: skip
    facet = await facet_by_key(db, facet_key)
    stmt = select(Term).where(Term.facet_id == facet.id).order_by(Term.label, Term.key)
    if not include_inactive:
        stmt = stmt.where(Term.active.is_(True))
    terms = list((await db.scalars(stmt)).all())
    counts = await _item_counts(db, [t.id for t in terms])
    if flat:
        outs = [term_out(t, facet.key) for t in terms]
        for out, t in zip(outs, terms, strict=True):
            out.item_count = counts.get(t.id, 0)
        return outs
    roots = term_tree(terms, facet.key)
    stack = list(roots)
    while stack:
        node = stack.pop()
        node.item_count = counts.get(node.id, 0)
        stack.extend(node.children or [])
    return roots


async def create_term(db: AsyncSession, facet_key: str, changes: dict[str, Any],
                      actor: uuid.UUID, ip: str | None) -> TermOut:  # fmt: skip
    facet = await facet_by_key(db, facet_key)
    if facet.value_type != "term":
        raise validation("facet", f"facet {facet.key!r} holds {facet.value_type} values, not terms")
    key = changes.get("key")
    if not key or not TERM_KEY.match(key):
        raise validation("key", "a key of lower-case letters, digits, '-' and '_'")
    if not changes.get("label"):
        raise validation("label", "label is required")
    if await db.scalar(select(Term.id).where(Term.facet_id == facet.id, Term.key == key)):
        raise ProblemError(409, "conflict", "A term with this key exists in the facet.")
    await _check_parent(db, None, facet, changes.get("parent_id"))
    term = Term(facet_id=facet.id, key=key, label="", parent_id=changes.get("parent_id"),
                synonyms=[], match_rules={}, active=True)  # fmt: skip
    _apply(term, changes)
    db.add(term)
    await db.flush()
    version = await bump_version(db, actor)
    after = {**term_snapshot(term), "facet": facet.key, "taxonomy_version": version}
    audit(db, "term.create", "term", term.id, actor=actor, ip=ip, after=after)
    await db.commit()
    return term_out(term, facet.key)


async def update_term(db: AsyncSession, term_id: uuid.UUID, changes: dict[str, Any],
                      actor: uuid.UUID, ip: str | None) -> TermOut:  # fmt: skip
    term, facet = await _term_or_404(db, term_id)
    before = term_snapshot(term)
    if "key" in changes and changes["key"] != term.key:
        key = changes["key"]
        if not key or not TERM_KEY.match(key):
            raise validation("key", "a key of lower-case letters, digits, '-' and '_'")
        if await db.scalar(select(Term.id).where(Term.facet_id == facet.id, Term.key == key)):
            raise ProblemError(409, "conflict", "A term with this key exists in the facet.")
        term.key = key
    if "parent_id" in changes and changes["parent_id"] != term.parent_id:
        await _check_parent(db, term, facet, changes["parent_id"])
        term.parent_id = changes["parent_id"]
    _apply(term, changes)
    after = term_snapshot(term)
    if after != before:
        version = await bump_version(db, actor)
        audit(db, "term.update", "term", term.id, actor=actor, ip=ip, before=before,
              after={**after, "taxonomy_version": version})  # fmt: skip
    await db.commit()
    return term_out(term, facet.key)


async def delete_term(db: AsyncSession, term_id: uuid.UUID, actor: uuid.UUID,
                      ip: str | None) -> None:  # fmt: skip
    """Delete a term no item uses; deactivate one that items use (M2 design notes)."""
    term, facet = await _term_or_404(db, term_id)
    before = term_snapshot(term)
    used = (await _item_counts(db, [term.id])).get(term.id, 0)
    if used:
        term.active = False
        action = "term.deactivate"
    else:
        # Children move up to the deleted term's parent.
        await db.execute(update(Term).where(Term.parent_id == term.id)
                         .values(parent_id=term.parent_id))  # fmt: skip
        await db.delete(term)
        action = "term.delete"
    version = await bump_version(db, actor)
    after = {"facet": facet.key, "items_tagged": used, "taxonomy_version": version}
    audit(db, action, "term", term_id, actor=actor, ip=ip, before=before, after=after)
    await db.commit()
