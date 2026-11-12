"""Route metadata shared by every module router.

``spec()`` builds the keyword arguments for an ``APIRouter`` decorator from the contract:
response model, status code, documented error responses, and the ``x-permission`` key that
``core.permissions.require`` enforces once a route is implemented (``stub=False``).
``not_implemented()`` is the body of every stub handler until its module lands.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any, NoReturn

from fastapi import Depends, Query
from fastapi.responses import Response

from regwatch.core.errors import PROBLEM_MEDIA_TYPE, NotImplementedProblem
from regwatch.core.permissions import require

PROBLEM_REF = {"$ref": "#/components/schemas/Problem"}
PERMISSION_KEY = "x-permission"
Tags = list[str | Enum]


def problem(description: str = "Error") -> dict[str, Any]:
    return {"description": description, "content": {PROBLEM_MEDIA_TYPE: {"schema": PROBLEM_REF}}}


def spec(
    model: Any = None,
    *,
    status: int = 200,
    desc: str = "OK",
    perm: str | None = None,
    errors: Iterable[int] = (),
    error_desc: dict[int, str] | None = None,
    content: str | None = None,
    body: dict[str, Any] | None = None,
    public: bool = False,
    stub: bool = True,
) -> dict[str, Any]:
    """Keyword arguments for ``router.<method>(path, **spec(...))``.

    ``content`` names a non-JSON response media type (its schema is a string); ``body`` is a
    non-JSON request body documented as-is (the handler reads ``Request`` itself).
    """
    responses: dict[int | str, dict[str, Any]] = {
        code: problem((error_desc or {}).get(code, "Error")) for code in errors
    }
    if stub:
        responses[501] = problem("Not implemented yet")
    kwargs: dict[str, Any] = {
        "status_code": status,
        "response_description": desc,
        "response_model": model,
        "response_model_exclude_unset": True,
    }
    if model is None:
        kwargs["response_class"] = Response
    if content is not None:
        responses[status] = {"content": {content: {"schema": {"type": "string"}}}}
    extra: dict[str, Any] = {}
    if perm:
        extra[PERMISSION_KEY] = perm
        if not stub:
            kwargs["dependencies"] = [Depends(require(perm))]
    if public:
        extra["security"] = []
    if body is not None:
        extra["requestBody"] = body
    kwargs["responses"] = responses
    if extra:
        kwargs["openapi_extra"] = extra
    return kwargs


def raw_body(media_type: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {"required": True, "content": {media_type: {"schema": schema}}}


def not_implemented() -> NoReturn:
    raise NotImplementedProblem()


@dataclass
class PageParams:
    """``components.parameters.page`` and ``page_size``."""

    page: Annotated[int, Query(ge=1)] = 1
    page_size: Annotated[int, Query(ge=1, le=200)] = 50


Paging = Annotated[PageParams, Depends()]
