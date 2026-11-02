"""Semantic comparison of the live OpenAPI document with openapi/regwatch.v1.yaml.

FastAPI cannot reproduce the hand-written contract byte for byte, so both documents are
normalised before comparison: ``$ref`` targets are inlined (recursive references stay as
``{"$ref": name}``), ``allOf`` is merged, ``anyOf [X, null]`` and ``nullable: true`` become one
``nullable`` flag, and annotations (title, description, summary, operationId) are dropped.
What remains is compared per operation: tags, security, ``x-permission``, parameters,
request body and responses.

The live document may add two kinds of response the contract does not list: ``422`` for
request validation and ``501`` for stubs; both must be problem details. Anything else that
differs is reported, unless it is listed in ``ACCEPTED`` with its reason.

Usage (from ``api/``): ``python -m tests.openapi_semantic CONTRACT.yaml [--live FILE]
[--write FILE]``; exits 1 when an unaccepted difference remains. ``make openapi`` runs it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

METHODS = ("get", "put", "post", "patch", "delete")
_ANNOTATIONS = {"title", "description", "summary", "examples", "example", "operationId"}
FRAMEWORK_CODES = {"422", "501"}
PROBLEM = {"application/problem+json"}

# Differences that are understood and tracked; each value says why it is accepted.
_CP02 = "live is stricter than the contract; CP-02 (#41) proposes tightening the contract"
ACCEPTED: dict[str, str] = {
    'GET /health.responses.200.application/json.properties.db.enum: only in live: ["ok", "unavailable"]': _CP02,  # noqa: E501
    'GET /health.responses.200.application/json.properties.queue.enum: only in live: ["ok", "unavailable"]': _CP02,  # noqa: E501
    'GET /health.responses.200.application/json.required: only in live: ["checked_at", "db", "queue", "status", "version"]': _CP02,  # noqa: E501
    'GET /version.responses.200.application/json.required: only in live: ["commit", "version"]': _CP02,  # noqa: E501
}


# Contract paths whose stubs arrive in part 2 of #30 (one module group per pull request).
# compare() reports nothing for them while they are not routed; empty this tuple when they are.
PENDING_PREFIXES: tuple[str, ...] = (
    "/taxonomy", "/jurisdictions", "/sources", "/capture-", "/items", "/search", "/map",
    "/views", "/reports", "/outputs", "/admin/printers",
)  # fmt: skip


def _component(doc: dict[str, Any], ref: str) -> tuple[str, Any]:
    parts = ref.removeprefix("#/").split("/")
    node: Any = doc
    for part in parts:
        node = node[part]
    return parts[-1], node


def _merge(target: dict[str, Any], extra: dict[str, Any]) -> None:
    for key, value in extra.items():
        if key == "properties":
            target.setdefault("properties", {}).update(value)
        elif key == "required":
            target["required"] = sorted(set(target.get("required", [])) | set(value))
        else:
            target[key] = value


def norm(doc: dict[str, Any], schema: Any, stack: tuple[str, ...] = ()) -> Any:
    """Return a canonical form of ``schema`` with references inlined."""
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        name, target = _component(doc, schema["$ref"])
        if name in stack:
            return {"$ref": name}
        siblings = {k: v for k, v in schema.items() if k != "$ref"}
        return norm(doc, {**target, **siblings}, (*stack, name))
    s = {k: v for k, v in schema.items() if k not in _ANNOTATIONS}
    nullable = bool(s.pop("nullable", False))
    if "default" in s and s["default"] is None:
        del s["default"]
    if isinstance(s.get("type"), list) and "null" in s["type"]:
        rest = [t for t in s["type"] if t != "null"]
        s["type"], nullable = (rest[0] if len(rest) == 1 else rest), True
    for key in ("anyOf", "oneOf"):
        if key in s:
            branches = [b for b in s[key] if b != {"type": "null"}]
            nullable = nullable or len(branches) < len(s[key])
            if len(branches) == 1:
                del s[key]
                s = {**norm(doc, branches[0], stack), **s}
            else:
                s[key] = [norm(doc, b, stack) for b in branches]
    if "allOf" in s:
        merged: dict[str, Any] = {}
        for branch in s.pop("allOf"):
            _merge(merged, norm(doc, branch, stack))
        _merge(merged, s)
        s = merged
    if "properties" in s:
        s["properties"] = {k: norm(doc, v, stack) for k, v in s["properties"].items()}
    if "items" in s:
        s["items"] = norm(doc, s["items"], stack)
    if s.get("additionalProperties") is True:
        del s["additionalProperties"]
    elif isinstance(s.get("additionalProperties"), dict):
        s["additionalProperties"] = norm(doc, s["additionalProperties"], stack)
    if "required" in s:
        s["required"] = sorted(s["required"])
        if not s["required"]:
            del s["required"]
    if s.get("type") == "object" and not s.get("properties") and not s.get("required"):
        s.pop("properties", None)
    if nullable and s:
        s["nullable"] = True
    return s


def _strip_null(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {k: v for k, v in schema.items() if k != "nullable"}
    return schema


def _deref(doc: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    return _component(doc, node["$ref"])[1] if "$ref" in node else node


def operation(doc: dict[str, Any], path: str, method: str) -> dict[str, Any]:
    """Canonical view of one operation."""
    item = doc["paths"][path]
    op = item[method]
    params = {}
    for raw in [*item.get("parameters", []), *op.get("parameters", [])]:
        p = _deref(doc, raw)
        params[f"{p['in']}:{p['name']}"] = {
            "required": bool(p.get("required", False)),
            "schema": _strip_null(norm(doc, p.get("schema", {}))),
        }
    body = None
    if "requestBody" in op:
        rb = _deref(doc, op["requestBody"])
        required = bool(rb.get("required", False))
        body = {
            "required": required,
            "content": {
                mt: norm(doc, c.get("schema", {}))
                if required
                else _strip_null(norm(doc, c.get("schema", {})))
                for mt, c in rb.get("content", {}).items()
            },
        }
    responses = {}
    for code, raw in op.get("responses", {}).items():
        r = _deref(doc, raw)
        responses[str(code)] = {
            mt: norm(doc, c.get("schema", {})) for mt, c in r.get("content", {}).items()
        }
    return {
        "tags": sorted(op.get("tags", [])),
        "security": op.get("security", doc.get("security", [])),
        "x-permission": op.get("x-permission"),
        "parameters": params,
        "requestBody": body,
        "responses": responses,
    }


def operations(doc: dict[str, Any]) -> set[tuple[str, str]]:
    return {(p, m) for p, item in doc.get("paths", {}).items() for m in item if m in METHODS}


def _diff(where: str, a: Any, b: Any, out: list[str]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            if key not in b:
                out.append(f"{where}.{key}: only in contract: {json.dumps(a[key])[:200]}")
            elif key not in a:
                out.append(f"{where}.{key}: only in live: {json.dumps(b[key])[:200]}")
            else:
                _diff(f"{where}.{key}", a[key], b[key], out)
    elif a != b:
        out.append(f"{where}: contract={json.dumps(a)[:200]} live={json.dumps(b)[:200]}")


def compare(
    contract: dict[str, Any], live: dict[str, Any], accepted: Mapping[str, str] = ACCEPTED
) -> list[str]:
    """All semantic differences, one line each; empty when the documents agree."""
    out: list[str] = []
    want, have = operations(contract), operations(live)
    want -= {(p, m) for p, m in want - have if p.startswith(PENDING_PREFIXES)}
    out += [f"{m.upper()} {p}: not routed" for p, m in sorted(want - have)]
    out += [f"{m.upper()} {p}: not in the contract" for p, m in sorted(have - want)]
    for path, method in sorted(want & have):
        a, b = operation(contract, path, method), operation(live, path, method)
        for code in FRAMEWORK_CODES - set(a["responses"]):
            extra = b["responses"].pop(code, None)
            if extra is not None and set(extra) != PROBLEM:
                out.append(f"{method.upper()} {path}: {code} is not problem details")
        _diff(f"{method.upper()} {path}", a, b, out)
    return [line for line in out if line not in accepted]


class _Yaml12Loader(yaml.SafeLoader):
    """PyYAML follows YAML 1.1, where ``on``/``off``/``yes``/``no`` are booleans. OpenAPI
    tooling (and openapi-typescript) reads YAML 1.2, where only ``true``/``false`` are."""


_Yaml12Loader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Yaml12Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        loaded: dict[str, Any] = yaml.load(fh, Loader=_Yaml12Loader)  # noqa: S506 - safe subclass
    return loaded


def live_document() -> dict[str, Any]:
    """The document the app serves at /api/v1/openapi.json, built without network access."""
    from regwatch.api.app import create_app
    from regwatch.core.settings import Settings

    placeholder = Settings(
        secret_key="0" * 64,
        database_url="postgresql://export@127.0.0.1:1/export",
        queue_url="valkey://127.0.0.1:1/0",
        base_url="http://localhost",
    )
    return create_app(placeholder).openapi()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.openapi_semantic")
    parser.add_argument("contract", type=Path)
    parser.add_argument("--live", type=Path, help="compare this file instead of the app")
    parser.add_argument("--write", type=Path, help="also write the live document (JSON) here")
    args = parser.parse_args(argv)
    contract = load(args.contract)
    live = load(args.live) if args.live else live_document()
    if args.write:
        args.write.write_text(json.dumps(live, indent=2) + "\n", encoding="utf-8")
    differences = compare(contract, live)
    for line in differences:
        print(line)
    for line, reason in ACCEPTED.items():
        print(f"accepted: {line}  ({reason})")
    n = len(operations(contract))
    print(f"{len(differences)} difference(s) across {n} contract operations")
    return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
