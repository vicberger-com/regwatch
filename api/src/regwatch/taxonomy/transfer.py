"""Taxonomy import and export as YAML (M2; ``POST /taxonomy/import``, ``GET /taxonomy/export``).

The document has the shape of the seed files (``api/seed/taxonomy.yaml``)::

    schema_version: 1          # optional; seed files have none
    facets:
      - key: topic
        label: Topic
        value_type: term       # optional fields keep their defaults or current values
        terms:
          - { key: privacy, label: Privacy, parent: data-protection, synonyms: [..],
              match_rules: {..}, color_token: .., active: true }

Import creates missing facets and terms and updates only the fields the file gives, so
importing the same file twice changes nothing the second time (M2 acceptance 2). Every facet
and term an import creates or changes gets its own audit row with before and after values,
beside one summary row (M2 review finding 11). ``system``
is ignored: imports cannot create or alter system facets' status. Parents are term keys of the
same facet, defined earlier in the file or already present. The whole import is one
transaction. YAML aliases are refused, so a small document cannot expand into a large one.
"""

from __future__ import annotations

import uuid
from typing import Any

import yaml
from anyio import to_thread
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.errors import ProblemError
from regwatch.core.services import audit
from regwatch.taxonomy import services
from regwatch.taxonomy.models import Facet, Term
from regwatch.taxonomy.schemas import ImportSummary

SCHEMA_VERSION = 1
MAX_FACETS, MAX_TERMS, MAX_TOTAL_TERMS = 200, 5000, 10_000
FACET_KEYS = {"key", "label", "value_type", "multi", "required", "show_in_view_selector",
              "show_in_filters", "sort_order", "system", "hidden", "terms"}  # fmt: skip
TERM_KEYS = {"key", "label", "parent", "synonyms", "match_rules", "color_token", "active"}
FACET_TYPES = {"label": str, "value_type": str, "multi": bool, "required": bool,
               "show_in_view_selector": bool, "show_in_filters": bool, "sort_order": int,
               "hidden": bool}  # fmt: skip


class _NoAliasLoader(yaml.SafeLoader):
    def compose_node(self, parent: Any, index: Any) -> Any:  # noqa: ANN401 - PyYAML API
        if self.check_event(yaml.AliasEvent):
            raise yaml.YAMLError("aliases are not allowed in taxonomy imports")
        return super().compose_node(parent, index)


def _bad(where: str, message: str) -> ProblemError:
    return services.validation(where, message)


def parse(document: bytes) -> list[dict[str, Any]]:
    try:
        doc = yaml.load(document.decode("utf-8"), Loader=_NoAliasLoader)  # noqa: S506  # nosec B506 - SafeLoader subclass
    except (UnicodeDecodeError, yaml.YAMLError, RecursionError) as exc:
        raise _bad("body", f"not a valid YAML document: {type(exc).__name__}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("facets"), list):
        raise _bad("facets", "the document needs a 'facets' list")
    unknown = set(doc) - {"schema_version", "taxonomy_version", "facets"}
    if unknown:
        raise _bad("body", f"unknown top-level keys: {sorted(unknown)}")
    if doc.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise _bad("schema_version", f"only schema_version {SCHEMA_VERSION} is supported")
    facets = doc["facets"]
    if len(facets) > MAX_FACETS:
        raise _bad("facets", f"at most {MAX_FACETS} facets")
    for i, f in enumerate(facets):
        if not isinstance(f, dict) or not isinstance(f.get("key"), str):
            raise _bad(f"facets[{i}]", "each facet is a mapping with a key")
        extra = set(f) - FACET_KEYS
        if extra:
            raise _bad(f"facets[{i}]", f"unknown keys: {sorted(extra)}")
        for field, kind in FACET_TYPES.items():
            if field in f and (not isinstance(f[field], kind) or
                               (kind is int and isinstance(f[field], bool))):  # fmt: skip
                raise _bad(f"facets[{i}].{field}", f"must be {kind.__name__}")
        terms = f.get("terms", [])
        if not isinstance(terms, list) or len(terms) > MAX_TERMS:
            raise _bad(f"facets[{i}].terms", f"a list of at most {MAX_TERMS} terms")
        for j, t in enumerate(terms):
            if not isinstance(t, dict) or not isinstance(t.get("key"), str):
                raise _bad(f"facets[{i}].terms[{j}]", "each term is a mapping with a key")
            extra = set(t) - TERM_KEYS
            if extra:
                raise _bad(f"facets[{i}].terms[{j}]", f"unknown keys: {sorted(extra)}")
            synonyms = t.get("synonyms", [])
            if not isinstance(synonyms, list) or not all(isinstance(s, str) for s in synonyms):
                raise _bad(f"facets[{i}].terms[{j}].synonyms", "a list of strings")
            if "match_rules" in t and not isinstance(t["match_rules"], dict):
                raise _bad(f"facets[{i}].terms[{j}].match_rules", "a mapping")
    total = sum(len(f.get("terms", [])) for f in facets)
    if total > MAX_TOTAL_TERMS:
        raise _bad("facets", f"at most {MAX_TOTAL_TERMS} terms in one import")
    checked: list[dict[str, Any]] = facets
    return checked


async def import_taxonomy(db: AsyncSession, document: bytes, actor: uuid.UUID,
                          ip: str | None) -> ImportSummary:  # fmt: skip
    # PyYAML is pure Python: parsing up to 2 MB takes seconds, so not on the event loop
    # (M2 review finding 5).
    facets = await to_thread.run_sync(parse, document)
    counts = {"facets_created": 0, "facets_updated": 0, "terms_created": 0, "terms_updated": 0}
    # Lock every existing facet the file names, in key order, before any write, so two imports
    # wait for each other instead of deadlocking (M2 re-verification N5).
    keys = sorted({f["key"] for f in facets})
    await db.execute(select(Facet.id).where(Facet.key.in_(keys)).order_by(Facet.key)
                     .with_for_update())  # fmt: skip
    for i, raw in enumerate(facets):
        where = f"facets[{i}] ({raw['key']})"
        try:
            facet = await _import_facet(db, raw, counts, actor, ip)
            for j, term in enumerate(raw.get("terms", [])):
                where = f"facets[{i}].terms[{j}] ({raw['key']}/{term['key']})"
                await _import_term(db, facet, term, counts, actor, ip)
        except ProblemError as exc:
            await db.rollback()
            field = exc.errors[0].field if exc.errors else ""
            raise _bad(where, f"{field}: {exc.detail}".strip(": ")) from exc
    if any(counts.values()):
        version = await services.bump_version(db, actor)
        audit(db, "taxonomy.import", "taxonomy", None, actor=actor, ip=ip,
              after={**counts, "taxonomy_version": version})  # fmt: skip
    await db.commit()
    return ImportSummary(**counts)


async def _import_facet(db: AsyncSession, raw: dict[str, Any], counts: dict[str, int],
                        actor: uuid.UUID, ip: str | None) -> Facet:  # fmt: skip
    facet = await db.scalar(select(Facet).where(Facet.key == raw["key"]))
    given = {k: raw[k] for k in FACET_TYPES if k in raw}
    services.check_facet_fields(given)
    if facet is None:
        if raw["key"] in services.RESERVED_KEYS or not services.KEY_RE.fullmatch(raw["key"]):
            raise _bad("key", "not a valid facet key")
        defaults = {"label": raw["key"].replace("_", " ").capitalize(), "value_type": "term",
                    "multi": True, "required": False, "show_in_view_selector": False,
                    "show_in_filters": True, "sort_order": 100, "hidden": False}  # fmt: skip
        values = {**defaults, **given}
        if values["value_type"] not in ("term", "text", "number", "date", "boolean"):
            raise _bad("value_type", "term, text, number, date or boolean")
        facet = Facet(key=raw["key"], system=False, **values)
        db.add(facet)
        await db.flush()
        counts["facets_created"] += 1
        audit(db, "taxonomy.import.facet_create", "facet", facet.key, actor=actor, ip=ip,
              after=services.facet_snapshot(facet))  # fmt: skip
        return facet
    if "value_type" in given and given["value_type"] != facet.value_type:
        raise _bad("value_type", "an import cannot change a facet's value type")
    before = services.facet_snapshot(facet)
    for field, value in given.items():
        if getattr(facet, field) != value:
            setattr(facet, field, value)
    after = services.facet_snapshot(facet)
    if after != before:
        counts["facets_updated"] += 1
        audit(db, "taxonomy.import.facet_update", "facet", facet.key, actor=actor, ip=ip,
              before=before, after=after)  # fmt: skip
    return facet


async def _import_term(
    db: AsyncSession, facet: Facet, raw: dict[str, Any], counts: dict[str, int],
    actor: uuid.UUID, ip: str | None,
) -> None:  # fmt: skip
    await services.lock_facet(db, facet.id)  # hierarchy changes are serialised per facet
    if facet.value_type != "term":
        raise _bad("terms", f"facet {facet.key!r} holds {facet.value_type} values, not terms")
    parent_id = None
    if "parent" in raw and raw["parent"] is not None and not isinstance(raw["parent"], str):
        raise _bad("parent", "must be the key of a term in the same facet")
    if raw.get("parent"):
        parent_id = await db.scalar(select(Term.id).where(Term.facet_id == facet.id,
                                                          Term.key == raw["parent"]))  # fmt: skip
        if parent_id is None:
            raise _bad("parent", f"no term {raw['parent']!r} earlier in this facet")
        await services.check_parent(db, None, facet, parent_id)  # depth cap
    term = await db.scalar(select(Term).where(Term.facet_id == facet.id, Term.key == raw["key"]))
    fields = ("label", "synonyms", "match_rules", "color_token", "active")
    changes: dict[str, Any] = {k: raw[k] for k in fields if k in raw}
    if term is None:
        if not services.TERM_KEY.fullmatch(raw["key"]):
            raise _bad("key", "a key of lower-case letters, digits, '-' and '_'")
        term = Term(facet_id=facet.id, key=raw["key"], label=raw["key"], parent_id=parent_id,
                    synonyms=[], match_rules={}, active=True)  # fmt: skip
        services.apply_term_changes(term, changes)
        db.add(term)
        await db.flush()
        counts["terms_created"] += 1
        audit(db, "taxonomy.import.term_create", "term", term.id, actor=actor, ip=ip,
              after={**services.term_snapshot(term), "facet": facet.key})  # fmt: skip
        return
    before = services.term_snapshot(term)
    if "parent" in raw and parent_id != term.parent_id:
        await services.check_parent(db, term, facet, parent_id)
        term.parent_id = parent_id
    services.apply_term_changes(term, changes)
    after = services.term_snapshot(term)
    if after != before:
        counts["terms_updated"] += 1
        # Only the changed fields: imports can touch thousands of terms (N5).
        changed = [k for k in after if after[k] != before.get(k)]
        old = {k: before[k] for k in changed}
        new = {**{k: after[k] for k in changed}, "key": term.key, "facet": facet.key}
        audit(db, "taxonomy.import.term_update", "term", term.id, actor=actor, ip=ip,
              before=old, after=new)  # fmt: skip


async def export_taxonomy(db: AsyncSession) -> str:
    facets = (await db.scalars(select(Facet).order_by(Facet.sort_order, Facet.key))).all()
    terms = (await db.scalars(select(Term).order_by(Term.key))).all()
    by_facet: dict[uuid.UUID, list[Term]] = {}
    for t in terms:
        by_facet.setdefault(t.facet_id, []).append(t)
    version = await services.current_version(db)
    out: list[dict[str, Any]] = []
    for f in facets:
        keys = {t.id: t.key for t in by_facet.get(f.id, [])}
        entry: dict[str, Any] = services.facet_snapshot(f)
        entry["system"] = f.system
        entry["terms"] = [_term_entry(t, keys) for t in _parents_first(by_facet.get(f.id, []))]
        out.append(entry)
    header = "# regwatch taxonomy export; import with POST /taxonomy/import\n"
    body = {"schema_version": SCHEMA_VERSION, "taxonomy_version": version, "facets": out}
    return header + yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=100)


def _parents_first(terms: list[Term]) -> list[Term]:
    ids = {t.id for t in terms}
    done: set[uuid.UUID] = set()
    ordered: list[Term] = []
    pending = list(terms)
    while pending:
        ready = [t for t in pending if t.parent_id is None or t.parent_id not in ids
                 or t.parent_id in done]  # fmt: skip
        if not ready:  # pragma: no cover - cycles are refused on write
            ready = pending
        ordered += ready
        done |= {t.id for t in ready}
        pending = [t for t in pending if t.id not in done]
    return ordered


def _term_entry(t: Term, keys: dict[uuid.UUID, str]) -> dict[str, Any]:
    entry: dict[str, Any] = {"key": t.key, "label": t.label}
    if t.parent_id and t.parent_id in keys:
        entry["parent"] = keys[t.parent_id]
    if t.synonyms:
        entry["synonyms"] = list(t.synonyms)
    if t.match_rules:
        entry["match_rules"] = t.match_rules
    if t.color_token:
        entry["color_token"] = t.color_token
    if not t.active:
        entry["active"] = False
    return entry
