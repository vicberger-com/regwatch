"""Service layer; other modules call this module only through here (ADR-0001).

Facets and terms (M2): CRUD, merge, the rule test, the view-selector dimensions, and the
``taxonomy.version`` setting, bumped in the same transaction as every facet or term change so
workers can drop cached attribute validation (M2 design notes). Reads go to the database each
time, so a new facet is visible in filters and the view selector on the next request (M2
acceptance 1).
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

from anyio import to_thread
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from regwatch.admin.models import Setting
from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.core.schemas import has_control
from regwatch.core.services import audit
from regwatch.taxonomy import rules
from regwatch.taxonomy.models import Facet, ItemTerm, Jurisdiction, Term
from regwatch.taxonomy.rules import PatternError, compile_pattern
from regwatch.taxonomy.schemas import Facet as FacetOut
from regwatch.taxonomy.schemas import FacetWrite, RuleTestResult, ViewDimension
from regwatch.taxonomy.schemas import Jurisdiction as JurisdictionOut
from regwatch.taxonomy.schemas import Region as RegionOut
from regwatch.taxonomy.schemas import Term as TermOut

VERSION_KEY = "taxonomy.version"
KEY_RE = re.compile(r"[a-z][a-z0-9_]{1,40}")  # facet keys (schema.sql); always fullmatch
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


async def current_version(db: AsyncSession) -> int:
    value = await db.scalar(select(Setting.value).where(Setting.key == VERSION_KEY))
    return int(value or 0)


SORT_RANGE = (-1_000_000, 1_000_000)


def check_facet_fields(values: dict[str, Any]) -> None:
    """Types and bounds for facet fields from the API or an import (review findings 2, 8)."""
    if "label" in values:
        label = values["label"]
        if (
            not isinstance(label, str)
            or not label.strip()
            or len(label) > 120
            or has_control(label)
        ):
            raise validation("label", "a label is one line of 1 to 120 characters")
        values["label"] = label.strip()
    for flag in ("multi", "required", "show_in_view_selector", "show_in_filters", "hidden"):
        if flag in values and not isinstance(values[flag], bool):
            raise validation(flag, "must be true or false")
    if "sort_order" in values:
        order = values["sort_order"]
        if (
            isinstance(order, bool)
            or not isinstance(order, int)
            or not (SORT_RANGE[0] <= order <= SORT_RANGE[1])
        ):
            raise validation("sort_order", f"an integer from {SORT_RANGE[0]} to {SORT_RANGE[1]}")


async def lock_facet(db: AsyncSession, facet_id: uuid.UUID) -> None:
    """Serialise hierarchy and delete changes within one facet (review findings 4, 6)."""
    await db.execute(select(Facet.id).where(Facet.id == facet_id).with_for_update())


async def facet_key_in_attributes(db: AsyncSession, facet_key: str) -> int:
    return int(await db.scalar(text(
        "SELECT count(*) FROM item WHERE attributes ? :fk"), {"fk": facet_key}) or 0)  # fmt: skip


async def term_references(db: AsyncSession, facet_key: str, term: Term) -> int:
    """Items and sources that name ``term`` outside ``item_term`` (review finding 3)."""
    in_attributes = await db.scalar(text(
        "SELECT count(*) FROM item WHERE attributes -> :fk ? :key "
        "OR attributes ->> :fk = :key"), {"fk": facet_key, "key": term.key})  # fmt: skip
    in_sources = await db.scalar(text(
        "SELECT count(*) FROM source WHERE CAST(:id AS uuid) = ANY(default_term_ids)"),
        {"id": term.id})  # fmt: skip
    return int(in_attributes or 0) + int(in_sources or 0)


async def rewrite_attribute_key(db: AsyncSession, facet_key: str, old: str, new: str) -> None:
    """Replace term key ``old`` with ``new`` in ``item.attributes`` (lists and single values)."""
    keys = {"fk": facet_key, "src": old, "dst": new}
    await db.execute(text(
        "UPDATE item SET attributes = jsonb_set(attributes, ARRAY[:fk], ("
        "  SELECT to_jsonb(array_agg(DISTINCT CASE WHEN v = :src THEN :dst ELSE v END))"
        "  FROM jsonb_array_elements_text(attributes -> :fk) AS v)) "
        "WHERE jsonb_typeof(attributes -> :fk) = 'array' AND (attributes -> :fk) ? :src"
    ), keys)  # fmt: skip
    await db.execute(text(
        "UPDATE item SET attributes = "
        "  jsonb_set(attributes, ARRAY[:fk], to_jsonb(CAST(:dst AS text))) "
        "WHERE attributes ->> :fk = :src"
    ), keys)  # fmt: skip


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
    check_facet_fields(given)
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
    check_facet_fields(changes)
    if "value_type" in changes and changes["value_type"] != facet.value_type:
        in_use = await db.scalar(select(func.count()).select_from(Term)
                                 .where(Term.facet_id == facet.id))  # fmt: skip
        if facet.system or in_use or await facet_key_in_attributes(db, facet.key):
            raise validation("value_type", "the value type of a system facet, or of one with "
                             "terms or item values, cannot change")  # fmt: skip
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
    # Lock the facet and its terms, so no tag can arrive between the count and the delete.
    await lock_facet(db, facet.id)
    await db.execute(select(Term.id).where(Term.facet_id == facet.id).with_for_update())
    tagged = await db.scalar(
        select(func.count()).select_from(ItemTerm)
        .join(Term, Term.id == ItemTerm.term_id).where(Term.facet_id == facet.id)
    )  # fmt: skip
    tagged = int(tagged or 0) + await facet_key_in_attributes(db, facet.key)
    defaults = await db.scalar(text(
        "SELECT count(*) FROM source s JOIN term t ON t.id = ANY(s.default_term_ids) "
        "WHERE t.facet_id = :fid"), {"fid": facet.id})  # fmt: skip
    if tagged or defaults:
        raise ProblemError(409, "conflict", "Items or source defaults use this facet; hide it "
                           "instead.")  # fmt: skip
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

TERM_KEY = re.compile(r"[a-z0-9][a-z0-9_-]{0,60}")  # fullmatch: "$" would allow a newline
MAX_SYNONYMS, MAX_RULE_ITEMS, MAX_PATTERN = 50, 100, 200


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


RULE_KEYS = {"keywords", "regex", "languages", "min_hits", "weight"}


def check_match_rules(rules: dict[str, Any]) -> dict[str, Any]:
    """Strict shape, so stored rules always read back as ``MatchRules`` (review finding 2)."""
    if not isinstance(rules, dict):
        raise validation("match_rules", "must be an object")
    unknown = sorted(str(k)[:40] for k in set(rules) - RULE_KEYS)
    if unknown:
        raise validation("match_rules", f"unknown keys: {unknown[:5]}")
    for field in ("keywords", "regex", "languages"):
        items = rules.get(field) or []
        if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
            raise validation(f"match_rules.{field}", "must be a list of strings")
        if len(items) > MAX_RULE_ITEMS or any(len(i) > MAX_PATTERN for i in items):
            limit = f"at most {MAX_RULE_ITEMS} entries of up to {MAX_PATTERN} characters"
            raise validation(f"match_rules.{field}", limit)
    for pattern in rules.get("regex") or []:
        try:
            compile_pattern(pattern)  # RE2: linear time (review finding 1, BL-74)
        except PatternError as exc:
            raise validation("match_rules.regex", f"{pattern!r}: {exc}") from exc
    min_hits = rules.get("min_hits", 1)
    if isinstance(min_hits, bool) or not isinstance(min_hits, int) or not 1 <= min_hits <= 100:
        raise validation("match_rules.min_hits", "must be an integer from 1 to 100")
    weight = rules.get("weight", 1.0)
    if isinstance(weight, bool) or not isinstance(weight, int | float) or not 0 < weight <= 10:
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


async def check_parent(db: AsyncSession, term: Term | None, facet: Facet,
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


def apply_term_changes(term: Term, changes: dict[str, Any]) -> None:
    if "label" in changes:
        label = changes["label"].strip() if isinstance(changes["label"], str) else ""
        if not label or len(label) > 120 or has_control(label):
            raise validation("label", "a label is one line of 1 to 120 characters")
        term.label = label
    if "synonyms" in changes:
        synonyms = changes["synonyms"] or []
        if not isinstance(synonyms, list) or not all(isinstance(v, str) for v in synonyms):
            raise validation("synonyms", "must be a list of strings")
        term.synonyms = normalise_synonyms(synonyms)
    if "match_rules" in changes:
        term.match_rules = check_match_rules(
            {k: v for k, v in (changes["match_rules"] or {}).items() if v is not None}
        )
    if "color_token" in changes:
        token = changes["color_token"]
        if token is not None and (not isinstance(token, str)
                                  or not re.fullmatch(r"[a-z][a-z0-9-]{0,40}", token)):  # fmt: skip
            raise validation("color_token", "a design token name such as category-3")
        term.color_token = token
    if "active" in changes:
        if not isinstance(changes["active"], bool):
            raise validation("active", "must be true or false")
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
    if not key or not TERM_KEY.fullmatch(key):
        raise validation("key", "a key of lower-case letters, digits, '-' and '_'")
    if not changes.get("label"):
        raise validation("label", "label is required")
    if await db.scalar(select(Term.id).where(Term.facet_id == facet.id, Term.key == key)):
        raise ProblemError(409, "conflict", "A term with this key exists in the facet.")
    await check_parent(db, None, facet, changes.get("parent_id"))
    term = Term(facet_id=facet.id, key=key, label="", parent_id=changes.get("parent_id"),
                synonyms=[], match_rules={}, active=True)  # fmt: skip
    apply_term_changes(term, changes)
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
        if not key or not TERM_KEY.fullmatch(key):
            raise validation("key", "a key of lower-case letters, digits, '-' and '_'")
        if await db.scalar(select(Term.id).where(Term.facet_id == facet.id, Term.key == key)):
            raise ProblemError(409, "conflict", "A term with this key exists in the facet.")
        await rewrite_attribute_key(db, facet.key, term.key, key)  # review finding 3
        term.key = key
    if "parent_id" in changes and changes["parent_id"] != term.parent_id:
        await lock_facet(db, facet.id)  # concurrent parent changes cannot form a cycle
        await check_parent(db, term, facet, changes["parent_id"])
        term.parent_id = changes["parent_id"]
    apply_term_changes(term, changes)
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
    await lock_facet(db, facet.id)
    # The row lock makes a concurrent tag insert wait, so the count below stays true.
    await db.execute(select(Term.id).where(Term.id == term.id).with_for_update())
    before = term_snapshot(term)
    used = (await _item_counts(db, [term.id])).get(term.id, 0)
    used += await term_references(db, facet.key, term)  # attributes and source defaults
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


# --- Merge and rule test --------------------------------------------------------------------


async def merge_term(db: AsyncSession, term_id: uuid.UUID, into_id: uuid.UUID,
                     actor: uuid.UUID, ip: str | None) -> int:  # fmt: skip
    """Move every reference from ``term_id`` to ``into_id`` and delete ``term_id``.

    References: item tags (keeping the higher confidence when an item has both), term keys in
    ``item.attributes``, ``source.default_term_ids`` and child terms (M2 acceptance 3).
    Returns the number of items that carried the merged term.
    """
    source, facet = await _term_or_404(db, term_id)
    target, target_facet = await _term_or_404(db, into_id)
    if source.id == target.id:
        raise validation("into_term_id", "a term cannot be merged into itself")
    if target_facet.id != facet.id:
        raise validation("into_term_id", "both terms must belong to the same facet")
    if not target.active:
        raise validation("into_term_id", "the target term is inactive")
    # Facet lock, then both term rows in a fixed order: a concurrent delete or merge waits and
    # then sees the moved tags (review finding 4).
    await lock_facet(db, facet.id)
    for locked in sorted((source.id, target.id)):
        await db.execute(select(Term.id).where(Term.id == locked).with_for_update())
    await db.refresh(source)
    await db.refresh(target)
    await check_parent(db, source, facet, target.id)  # the target is not below the source
    ids = {"src": source.id, "dst": target.id}
    moved = int(await db.scalar(
        select(func.count()).select_from(ItemTerm).where(ItemTerm.term_id == source.id)
    ) or 0)  # fmt: skip
    await db.execute(text(
        "UPDATE item_term t SET confidence = GREATEST(t.confidence, s.confidence) "
        "FROM item_term s WHERE s.term_id = :src AND t.term_id = :dst AND t.item_id = s.item_id"
    ), ids)  # fmt: skip
    await db.execute(text(
        "DELETE FROM item_term s USING item_term t "
        "WHERE s.term_id = :src AND t.term_id = :dst AND s.item_id = t.item_id"
    ), ids)  # fmt: skip
    await db.execute(text("UPDATE item_term SET term_id = :dst WHERE term_id = :src"), ids)
    await rewrite_attribute_key(db, facet.key, source.key, target.key)
    await db.execute(text(
        "UPDATE source SET default_term_ids = ARRAY(SELECT DISTINCT unnest("
        "  array_replace(default_term_ids, CAST(:src AS uuid), CAST(:dst AS uuid)))) "
        "WHERE CAST(:src AS uuid) = ANY(default_term_ids)"
    ), ids)  # fmt: skip
    await db.execute(update(Term).where(Term.parent_id == source.id).values(parent_id=target.id))
    before = {"source": term_snapshot(source), "target": term_snapshot(target)}
    target.synonyms = normalise_synonyms(
        [*target.synonyms, source.label, *source.synonyms]
    )  # the merged term's names keep finding the target
    await db.delete(source)
    version = await bump_version(db, actor)
    after = {"target": term_snapshot(target), "items_moved": moved, "taxonomy_version": version}
    audit(db, "term.merge", "term", term_id, actor=actor, ip=ip, before=before, after=after)
    await db.commit()
    return moved


async def run_rule_test(db: AsyncSession, term_id: uuid.UUID, sample: str,
                          language: str | None) -> RuleTestResult:  # fmt: skip
    term, _ = await _term_or_404(db, term_id)
    # Off the event loop: matching is linear but still CPU work (review finding 1).
    result = await to_thread.run_sync(rules.evaluate, term.match_rules or {}, sample, language)
    return RuleTestResult(matched=result.matched, confidence=result.confidence,
                          evidence=result.evidence)  # fmt: skip


# --- Jurisdictions and regions ---------------------------------------------------------------

# UN M49 sub-regions used by the seed (region_code), with their M49 English names.
M49_REGIONS: dict[str, str] = {
    "015": "Northern Africa", "202": "Sub-Saharan Africa",
    "419": "Latin America and the Caribbean", "021": "Northern America",
    "143": "Central Asia", "030": "Eastern Asia", "035": "South-eastern Asia",
    "034": "Southern Asia", "145": "Western Asia", "151": "Eastern Europe",
    "154": "Northern Europe", "039": "Southern Europe", "155": "Western Europe",
    "053": "Australia and New Zealand", "054": "Melanesia", "057": "Micronesia",
    "061": "Polynesia",
}  # fmt: skip
CODE_PATTERNS = {
    "country": re.compile(r"[A-Z]{2}"),  # ISO 3166-1 alpha-2 (XK user-assigned)
    "subdivision": re.compile(r"[A-Z]{2}-[A-Z0-9]{1,3}"),  # ISO 3166-2
    "supranational": re.compile(r"[A-Z][A-Z0-9_]{1,15}"),  # EU, COE, OECD, ...
}
GEOMETRY_REF = re.compile(r"[A-Z0-9_-]{1,20}")  # every pattern here is used with fullmatch
JURISDICTION_FIELDS = ("name", "kind", "region_code", "geometry_ref", "active")


def jurisdiction_out(j: Jurisdiction, parent_code: str | None) -> JurisdictionOut:
    return JurisdictionOut(id=j.id, code=j.code, name=j.name, kind=j.kind,
                           parent_code=parent_code, region_code=j.region_code,
                           geometry_ref=j.geometry_ref, active=j.active)  # fmt: skip


async def list_jurisdictions(db: AsyncSession, kind: str | None,
                             active: bool | None) -> list[JurisdictionOut]:  # fmt: skip
    parent = aliased(Jurisdiction)
    stmt = (select(Jurisdiction, parent.code).outerjoin(parent, parent.id == Jurisdiction.parent_id)
            .order_by(Jurisdiction.name))  # fmt: skip
    if kind:
        stmt = stmt.where(Jurisdiction.kind == kind)
    if active is not None:
        stmt = stmt.where(Jurisdiction.active.is_(active))
    return [jurisdiction_out(j, p) for j, p in (await db.execute(stmt)).tuples().all()]


async def _jurisdiction(db: AsyncSession, code: str) -> tuple[Jurisdiction, str | None]:
    parent = aliased(Jurisdiction)
    row = (await db.execute(
        select(Jurisdiction, parent.code).outerjoin(parent, parent.id == Jurisdiction.parent_id)
        .where(Jurisdiction.code == code.upper())
    )).tuples().first()  # fmt: skip
    if row is None:
        raise not_found("jurisdiction")
    return row[0], row[1]


async def get_jurisdiction(db: AsyncSession, code: str) -> JurisdictionOut:
    j, parent_code = await _jurisdiction(db, code)
    return jurisdiction_out(j, parent_code)


def _check_jurisdiction(values: dict[str, Any]) -> None:
    name = values.get("name")
    if not isinstance(name, str) or not name.strip():
        raise validation("name", "a name is one line of 1 to 120 characters")
    if len(name.strip()) > 120 or has_control(name):
        raise validation("name", "a name is one line of 1 to 120 characters")
    region = values.get("region_code")
    if region is not None and region not in M49_REGIONS:
        raise validation("region_code", "an M49 sub-region code, such as 155")
    geometry = values.get("geometry_ref")
    if geometry is not None and not GEOMETRY_REF.fullmatch(geometry):
        raise validation("geometry_ref", "a Natural Earth feature id, such as DEU")


async def _parent_id(db: AsyncSession, kind: str, parent_code: str | None,
                     code: str) -> uuid.UUID | None:  # fmt: skip
    """Subdivisions need a country parent whose code prefixes theirs; others have none."""
    if kind != "subdivision":
        if parent_code:
            raise validation("parent_code", "only subdivisions have a parent")
        return None
    if not parent_code or not code.startswith(parent_code.upper() + "-"):
        raise validation("parent_code", "the country whose code prefixes the subdivision code")
    row = (await db.execute(select(Jurisdiction.id, Jurisdiction.kind)
                            .where(Jurisdiction.code == parent_code.upper()))).first()  # fmt: skip
    if row is None or row[1] != "country":
        raise validation("parent_code", "the parent must be an existing country")
    parent_id: uuid.UUID = row[0]
    return parent_id


async def create_jurisdiction(db: AsyncSession, values: dict[str, Any], actor: uuid.UUID,
                              ip: str | None) -> JurisdictionOut:  # fmt: skip
    code = (values.get("code") or "").upper()
    kind = values.get("kind")
    if kind not in CODE_PATTERNS:
        raise validation("kind", "country, subdivision or supranational")
    if not CODE_PATTERNS[kind].fullmatch(code):
        raise validation("code", f"not a valid {kind} code")
    _check_jurisdiction(values)
    if await db.scalar(select(Jurisdiction.id).where(Jurisdiction.code == code)) is not None:
        raise ProblemError(409, "conflict", "A jurisdiction with this code exists.")
    parent_id = await _parent_id(db, kind, values.get("parent_code"), code)
    j = Jurisdiction(code=code, name=values["name"].strip(), kind=kind, parent_id=parent_id,
                     region_code=values.get("region_code"), geometry_ref=values.get("geometry_ref"),
                     active=values.get("active", True))  # fmt: skip
    db.add(j)
    await db.flush()
    audit(db, "jurisdiction.create", "jurisdiction", code, actor=actor, ip=ip,
          after={"code": code, **{f: getattr(j, f) for f in JURISDICTION_FIELDS}})  # fmt: skip
    await db.commit()
    return jurisdiction_out(j, values.get("parent_code"))


async def update_jurisdiction(db: AsyncSession, code: str, changes: dict[str, Any],
                              actor: uuid.UUID, ip: str | None) -> JurisdictionOut:  # fmt: skip
    j, parent_code = await _jurisdiction(db, code)
    before = {"parent_code": parent_code, **{f: getattr(j, f) for f in JURISDICTION_FIELDS}}
    if "code" in changes and (changes["code"] or "").upper() != j.code:
        raise validation("code", "a jurisdiction keeps its code")
    if "kind" in changes and changes["kind"] != j.kind:
        raise validation("kind", "a jurisdiction keeps its kind")
    merged = {**before, **changes}
    _check_jurisdiction(merged)
    if "parent_code" in changes:
        j.parent_id = await _parent_id(db, j.kind, changes["parent_code"], j.code)
        parent_code = changes["parent_code"].upper() if changes["parent_code"] else None
    for field in ("name", "region_code", "geometry_ref", "active"):
        if field in changes:
            if field in ("name", "active") and changes[field] is None:
                raise validation(field, f"{field} cannot be null")
            value = changes[field]
            setattr(j, field, value.strip() if field == "name" else value)
    after = {"parent_code": parent_code, **{f: getattr(j, f) for f in JURISDICTION_FIELDS}}
    if after != before:
        audit(db, "jurisdiction.update", "jurisdiction", j.code, actor=actor, ip=ip,
              before=before, after=after)  # fmt: skip
    await db.commit()
    return jurisdiction_out(j, parent_code)


async def list_regions(db: AsyncSession) -> list[RegionOut]:
    rows = await db.execute(
        select(Jurisdiction.region_code, Jurisdiction.code)
        .where(Jurisdiction.region_code.is_not(None), Jurisdiction.active.is_(True))
        .order_by(Jurisdiction.region_code, Jurisdiction.code)
    )
    members: dict[str, list[str]] = {}
    for region, code in rows.tuples().all():
        if region is not None:
            members.setdefault(region, []).append(code)
    ordered = sorted(members.items(), key=lambda kv: M49_REGIONS.get(kv[0], kv[0]))
    return [RegionOut(code=r, name=M49_REGIONS.get(r, r), jurisdiction_codes=codes)
            for r, codes in ordered]  # fmt: skip
