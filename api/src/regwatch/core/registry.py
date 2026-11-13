"""The registries contract (docs/contracts/registries.yaml) at run time.

A byte-identical copy ships inside the package (``regwatch/core/registries.yaml``; a unit
test holds it equal to the contract), so the API can describe settings, permissions and
flags without the seed directory. Values live in the database; this is the vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any

import yaml

SETTING_TYPES = frozenset({"string", "integer", "number", "boolean", "enum", "list"})


@dataclass(frozen=True)
class SettingDef:
    key: str
    type: str
    default: Any
    module: str
    values: tuple[str, ...] = ()
    note: str | None = None


def _rejoin(entry: dict[str, Any], field: str) -> str | None:
    """``field`` with the comma-split fragments YAML turned into null-valued keys (BL-31)."""
    if field not in entry:
        return None
    fragments = [str(k) for k, v in entry.items() if v is None]
    return ", ".join([str(entry[field]), *fragments])


@lru_cache(maxsize=1)
def raw() -> dict[str, Any]:
    text = files("regwatch.core").joinpath("registries.yaml").read_text(encoding="utf-8")
    doc: dict[str, Any] = yaml.safe_load(text)
    return doc


@lru_cache(maxsize=1)
def settings() -> dict[str, SettingDef]:
    out: dict[str, SettingDef] = {}
    for key, entry in raw()["settings"].items():
        out[key] = SettingDef(
            key=key,
            type=entry["type"],
            default=entry["default"],
            module=entry["module"],
            values=tuple(entry.get("values") or ()),
            note=_rejoin(entry, "note"),
        )
    return out


@lru_cache(maxsize=1)
def permission_keys() -> frozenset[str]:
    return frozenset(raw()["permissions"])
