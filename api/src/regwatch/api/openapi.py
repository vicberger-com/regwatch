"""Shape FastAPI's generated document like openapi/regwatch.v1.yaml.

Paths are listed relative to the ``/api/v1`` server URL, the session cookie scheme is the
default security, request validation errors are documented as problem details, and the
shared ``Problem`` and ``Page`` schemas are always present.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import TypeAdapter

from regwatch.core.errors import Problem
from regwatch.core.routing import problem
from regwatch.core.schemas import Page

TAGS = ["system", "auth", "admin", "taxonomy", "capture", "items", "search", "reports",
        "outputs", "me"]  # fmt: skip
_FASTAPI_SCHEMAS = ("HTTPValidationError", "ValidationError")
_REF = "#/components/schemas/{model}"


def _component(model: Any, schemas: dict[str, Any], name: str) -> None:
    schema = TypeAdapter(model).json_schema(ref_template=_REF)
    schemas.update(schema.pop("$defs", {}))
    schemas[name] = schema


def build_openapi(app: FastAPI, prefix: str) -> dict[str, Any]:
    doc = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        routes=app.routes,
        tags=[{"name": t} for t in TAGS],
        servers=[{"url": prefix}],
    )
    doc["paths"] = {
        path.removeprefix(prefix) or "/": item for path, item in doc.get("paths", {}).items()
    }
    for item in doc["paths"].values():
        for op in item.values():
            if "422" in op.get("responses", {}):
                op["responses"]["422"] = problem("Validation error")
    components = doc.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    for name in _FASTAPI_SCHEMAS:
        schemas.pop(name, None)
    _component(Problem, schemas, "Problem")
    _component(Page[Any], schemas, "Page")
    components["securitySchemes"] = {
        "session": {"type": "apiKey", "in": "cookie", "name": "rw_session"}
    }
    doc["security"] = [{"session": []}]
    return doc


def install_openapi(app: FastAPI, prefix: str) -> None:
    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = build_openapi(app, prefix)
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
