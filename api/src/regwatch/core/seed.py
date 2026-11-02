"""Idempotent seed loader (``regwatch-seed``, docs/04-data-model.md 4.5 and 4.6 rule 5).

Every ``*.yaml`` file in the seed directory (default ``./seed``, which is ``api/seed`` in a
checkout and ``/app/seed`` in the image) may hold any of these top-level keys:
``permissions``, ``roles``, ``settings``, ``feature_flags`` (the shape of
docs/contracts/registries.yaml), ``jurisdictions`` and ``facets``.

Rows are matched on their natural key and only inserted when missing, so a second run changes
nothing and edits that administrators make later survive a re-run. Permission descriptions
are the one exception: they follow the registry, which owns that vocabulary.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml
from sqlalchemy import Table, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from regwatch.admin.models import FeatureFlag, Setting
from regwatch.core.db import Base, create_engine
from regwatch.identity.models import Permission, Role, RolePermission
from regwatch.taxonomy.models import Facet, Jurisdiction, Term

# Registry sections that describe code, not data; the seed loader ignores them.
_IGNORED_KEYS = frozenset({"celery_tasks", "events"})
_FACET_DEFAULTS: dict[str, Any] = {
    "value_type": "term",
    "multi": True,
    "required": False,
    "show_in_view_selector": False,
    "show_in_filters": True,
    "sort_order": 100,
    "system": False,
}


def _table(model: type[Base]) -> Table:
    return cast(Table, model.__table__)


class SeedError(ValueError):
    """The seed files are inconsistent; nothing was written."""


@dataclass
class SeedData:
    permissions: dict[str, dict[str, str]] = field(default_factory=dict)
    roles: dict[str, list[str]] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    feature_flags: dict[str, dict[str, Any]] = field(default_factory=dict)
    jurisdictions: dict[str, dict[str, Any]] = field(default_factory=dict)
    facets: dict[str, dict[str, Any]] = field(default_factory=dict)
    terms: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def _merge(target: dict[str, Any], items: dict[str, Any], what: str, source: str) -> None:
    for key, value in items.items():
        if key in target:
            raise SeedError(f"{source}: duplicate {what} {key!r}")
        target[key] = value


def _add_facets(data: SeedData, facets: list[dict[str, Any]], source: str) -> None:
    for raw in facets:
        facet = {**_FACET_DEFAULTS, **{k: v for k, v in raw.items() if k != "terms"}}
        _merge(data.facets, {facet["key"]: facet}, "facet", source)
        terms: list[dict[str, Any]] = []
        seen: set[str] = set()
        for term in raw.get("terms", []):
            if term["key"] in seen:
                raise SeedError(f"{source}: duplicate term {facet['key']}/{term['key']}")
            if term.get("parent") is not None and term["parent"] not in seen:
                raise SeedError(f"{source}: term {term['key']!r} names an unknown or later parent")
            seen.add(term["key"])
            terms.append(term)
        data.terms[facet["key"]] = terms


def load(seed_dir: Path) -> SeedData:
    """Read and check every seed file; raise :class:`SeedError` on any inconsistency."""
    files = sorted(seed_dir.glob("*.yaml"))
    if not files:
        raise SeedError(f"no seed files in {seed_dir}")
    data = SeedData()
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        unknown = set(doc) - _IGNORED_KEYS - {
            "permissions", "roles", "settings", "feature_flags", "jurisdictions", "facets",
        }  # fmt: skip
        if unknown:
            raise SeedError(f"{path.name}: unknown top-level keys {sorted(unknown)}")
        permissions = {
            k: {"description": _text(v), "module": v["module"]}
            for k, v in doc.get("permissions", {}).items()
        }
        _merge(data.permissions, permissions, "permission", path.name)
        _merge(data.roles, doc.get("roles", {}), "role", path.name)
        settings = {k: v["default"] for k, v in doc.get("settings", {}).items()}
        _merge(data.settings, settings, "setting", path.name)
        flags = {
            k: {"description": _text(v), "enabled": _flag_default(v)}
            for k, v in doc.get("feature_flags", {}).items()
        }
        _merge(data.feature_flags, flags, "feature flag", path.name)
        jurisdictions = {j["code"]: j for j in doc.get("jurisdictions", [])}
        if len(jurisdictions) != len(doc.get("jurisdictions", [])):
            raise SeedError(f"{path.name}: duplicate jurisdiction code")
        _merge(data.jurisdictions, jurisdictions, "jurisdiction", path.name)
        _add_facets(data, doc.get("facets", []), path.name)
    for role, perms in data.roles.items():
        missing = [p for p in perms if p != "*" and p not in data.permissions]
        if missing:
            raise SeedError(f"role {role!r} names unknown permissions {missing}")
    return data


def _text(entry: dict[str, Any]) -> str:
    """The ``description`` of a registry entry, rejoined where YAML split it at commas.

    registries.yaml writes unquoted text in flow mappings, so
    ``{ module: M5, description: Read items, versions, diffs and search }`` parses as
    ``description: "Read items"`` plus the keys ``versions`` and ``diffs and search`` with null
    values. Those null-valued keys are the rest of the sentence, in order.
    """
    fragments = [str(k) for k, v in entry.items() if v is None]
    return ", ".join([str(entry["description"]), *fragments])


def _flag_default(entry: dict[str, Any]) -> bool:
    """Flags default to false; the registry marks the exceptions with ", default true"."""
    if "enabled" in entry:
        return bool(entry["enabled"])
    return _text(entry).endswith(", default true")


async def _insert_missing(
    conn: AsyncConnection, table: Table, rows: Sequence[dict[str, Any]], conflict: list[str]
) -> int:
    if not rows:
        return 0
    stmt = insert(table).values(list(rows)).on_conflict_do_nothing(index_elements=conflict)
    result = await conn.execute(stmt.returning(table.c[conflict[0]]))
    return len(result.all())


async def _ids(conn: AsyncConnection, table: Table, key: str, **where: Any) -> dict[str, Any]:
    stmt = select(table.c[key], table.c.id).where(*(table.c[k] == v for k, v in where.items()))
    return {row[0]: row[1] for row in (await conn.execute(stmt)).all()}


async def apply(conn: AsyncConnection, data: SeedData) -> dict[str, int]:
    """Write ``data``; return the number of rows inserted or changed per table."""
    counts: dict[str, int] = {}
    perm_table = _table(Permission)
    stmt = insert(perm_table).values(
        [{"key": k, "description": v["description"], "module": v["module"]}
         for k, v in data.permissions.items()]
    )  # fmt: skip
    changed = (perm_table.c.description != stmt.excluded.description) | (
        perm_table.c.module != stmt.excluded.module
    )
    upsert = stmt.on_conflict_do_update(
        index_elements=["key"],
        set_={"description": stmt.excluded.description, "module": stmt.excluded.module},
        where=changed,
    )
    counts["permission"] = len((await conn.execute(upsert.returning(perm_table.c.key))).all())

    role_rows = [{"key": k, "label": k.capitalize(), "system": True} for k in data.roles]
    counts["role"] = await _insert_missing(conn, _table(Role), role_rows, ["key"])
    role_ids = await _ids(conn, _table(Role), "key")
    pairs = [
        {"role_id": role_ids[role], "permission_key": perm}
        for role, perms in data.roles.items()
        for perm in (list(data.permissions) if "*" in perms else perms)
    ]
    counts["role_permission"] = await _insert_missing(
        conn, _table(RolePermission), pairs, ["role_id", "permission_key"]
    )
    setting_rows = [{"key": k, "value": v} for k, v in data.settings.items()]
    counts["setting"] = await _insert_missing(conn, _table(Setting), setting_rows, ["key"])
    flag_rows = [{"key": k, **v} for k, v in data.feature_flags.items()]
    counts["feature_flag"] = await _insert_missing(conn, _table(FeatureFlag), flag_rows, ["key"])

    jur_rows = [
        {"code": j["code"], "name": j["name"], "kind": j["kind"],
         "region_code": j.get("region_code"), "geometry_ref": j.get("geometry_ref")}
        for j in data.jurisdictions.values()
    ]  # fmt: skip
    counts["jurisdiction"] = await _insert_missing(conn, _table(Jurisdiction), jur_rows, ["code"])

    counts["facet"] = await _insert_missing(
        conn, _table(Facet), list(data.facets.values()), ["key"]
    )
    facet_ids = await _ids(conn, _table(Facet), "key")
    counts["term"] = 0
    for facet_key, terms in data.terms.items():
        counts["term"] += await _apply_terms(conn, facet_ids[facet_key], terms)
    return counts


async def _apply_terms(conn: AsyncConnection, facet_id: Any, terms: list[dict[str, Any]]) -> int:
    """Insert terms level by level, so each parent exists before its children."""
    inserted, pending = 0, list(terms)
    while pending:
        term_ids = await _ids(conn, _table(Term), "key", facet_id=facet_id)
        ready = [t for t in pending if t.get("parent") is None or t["parent"] in term_ids]
        if not ready:
            raise SeedError(f"terms with unresolvable parents: {[t['key'] for t in pending]}")
        rows = [
            {"facet_id": facet_id, "key": t["key"], "label": t["label"],
             "parent_id": term_ids.get(t["parent"]) if t.get("parent") else None,
             "synonyms": t.get("synonyms", []), "match_rules": t.get("match_rules", {})}
            for t in ready
        ]  # fmt: skip
        inserted += await _insert_missing(conn, _table(Term), rows, ["facet_id", "key"])
        pending = [t for t in pending if t not in ready]
    return inserted


async def run(seed_dir: Path, database_url: str) -> dict[str, int]:
    """Load ``seed_dir`` and apply it in one transaction."""
    data = load(seed_dir)
    engine = create_engine(database_url, poolclass_null=True)
    try:
        async with engine.begin() as conn:
            return await apply(conn, data)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="regwatch-seed", description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=Path("seed"), help="seed directory")
    args = parser.parse_args(argv)
    from regwatch.core.settings import get_settings

    url = get_settings().database_url.get_secret_value()
    try:
        counts = asyncio.run(run(args.dir, url))
    except SeedError as exc:
        print(f"regwatch-seed: {exc}", file=sys.stderr)
        return 1
    print("regwatch-seed: " + ", ".join(f"{t} +{n}" for t, n in counts.items()))
    return 0
