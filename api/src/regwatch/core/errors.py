"""RFC 9457 problem details for every API error.

Handlers turn ``ProblemError``, Starlette/FastAPI ``HTTPException`` and request validation
errors into ``application/problem+json`` bodies matching ``components.schemas.Problem``.
Unexpected exceptions become a generic 500 that never echoes internal detail.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import BaseRoute, Route, compile_path

from regwatch.core.schemas import UNSET

PROBLEM_MEDIA_TYPE = "application/problem+json"
ERROR_TYPE_BASE = "https://regwatch/errors/"

_log = structlog.get_logger("regwatch.errors")


class ProblemFieldError(BaseModel):
    field: str = UNSET
    message: str = UNSET


class Problem(BaseModel):
    """``components.schemas.Problem``."""

    type: str
    title: str
    status: int
    detail: str = UNSET
    instance: str = UNSET
    request_id: str = UNSET
    errors: list[ProblemFieldError] = UNSET


def error_type(slug: str) -> str:
    return f"{ERROR_TYPE_BASE}{slug}"


class ProblemError(Exception):
    """Raise from a handler or dependency to answer with a problem-details body."""

    def __init__(
        self,
        status: int,
        slug: str,
        detail: str | None = None,
        *,
        title: str | None = None,
        errors: list[ProblemFieldError] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or slug)
        self.status = status
        self.slug = slug
        self.title = title or HTTPStatus(status).phrase
        self.detail = detail
        self.errors = errors
        self.headers = headers


class NotImplementedProblem(ProblemError):  # noqa: N818 - a problem type, not a Python error
    def __init__(self) -> None:
        super().__init__(
            501, "not-implemented", "This endpoint is in the contract but not implemented yet."
        )


_SLUGS = {400: "bad-request", 401: "unauthenticated", 403: "forbidden", 404: "not-found",
          405: "method-not-allowed", 409: "conflict", 415: "unsupported-media-type",
          422: "validation", 429: "rate-limited", 501: "not-implemented"}  # fmt: skip


def problem_response(
    request: Request,
    status: int,
    slug: str,
    *,
    title: str | None = None,
    detail: str | None = None,
    errors: list[ProblemFieldError] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": error_type(slug),
        "title": title or HTTPStatus(status).phrase,
        "status": status,
        "instance": request.url.path,
    }
    if detail:
        body["detail"] = detail
    rid = structlog.contextvars.get_contextvars().get("request_id")
    if rid:
        body["request_id"] = rid
    if errors:
        body["errors"] = [e.model_dump(exclude_unset=True) for e in errors]
    return JSONResponse(body, status_code=status, headers=headers, media_type=PROBLEM_MEDIA_TYPE)


async def _problem_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProblemError)  # noqa: S101 - registered for this type only
    return problem_response(
        request, exc.status, exc.slug, title=exc.title, detail=exc.detail,
        errors=exc.errors, headers=exc.headers,
    )  # fmt: skip


# FastAPI answers 400 with this detail when a JSON body cannot be decoded at all; the contract
# documents malformed input as 422 validation problems, so it is reported as one.
BODY_PARSE_DETAIL = "There was an error parsing the body"


def _allowed_methods(request: Request) -> str:
    """Every method routed for the request path.

    Starlette's ``Allow`` header names only the first route that matched the path, and routes
    of included routers are not reachable through public attributes of ``app.routes``, so the
    app's own routes plus the (full path, route) pairs given to ``install_problem_handlers``
    are indexed on the first 405.
    """
    state = request.app.state
    if getattr(state, "allowed_methods", None) is None:
        own = [(r.path, r) for r in request.app.router.routes if isinstance(r, Route)]
        index: dict[str, tuple[re.Pattern[str], set[str]]] = {}
        for path, route in [*own, *state.problem_routes]:
            if isinstance(route, Route) and route.methods:
                index.setdefault(path, (compile_path(path)[0], set()))[1].update(route.methods)
        state.allowed_methods = list(index.values())
    path = request.scope.get("path", "")
    # The first matching template wins, as in routing: /jurisdictions/regions is not {code}.
    no_match: set[str] = set()
    methods = next((ms for rx, ms in state.allowed_methods if rx.match(path)), no_match)
    return ", ".join(sorted(methods))


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    status, headers = exc.status_code, dict(exc.headers or {})
    if status == 400 and exc.detail == BODY_PARSE_DETAIL:
        return problem_response(
            request, 422, "validation", detail="The request body is not valid JSON."
        )
    if status == 405:
        headers["Allow"] = _allowed_methods(request)
    phrase = HTTPStatus(status).phrase
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail != phrase else None
    return problem_response(
        request, status, _SLUGS.get(status, "http-error"), detail=detail, headers=headers or None
    )


def _field(loc: tuple[Any, ...] | list[Any]) -> str:
    parts = [str(p) for p in loc]
    if parts and parts[0] in {"body", "query", "path", "header", "cookie"}:
        parts = parts[1:] or parts
    return ".".join(parts)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    errors = [
        ProblemFieldError(field=_field(e.get("loc", ())), message=str(e.get("msg", "invalid")))
        for e in exc.errors()
    ]
    return problem_response(
        request, 422, "validation", detail="The request failed validation.", errors=errors
    )


# Database errors caused by the request's data rather than by the server (review finding 7).
# 22021 character_not_in_repertoire and 22P05 untranslatable_character (NUL in text);
# 23505 unique_violation (a concurrent insert won).
_NUL = (422, "validation", "Text must not contain NUL characters.")
_SQLSTATE = {
    "22021": _NUL,
    "22P05": _NUL,
    "23505": (409, "conflict", "The record already exists."),
    "40P01": (409, "conflict", "A concurrent change conflicted; try again."),
}


async def _database_error(request: Request, exc: Exception) -> JSONResponse:
    from sqlalchemy.exc import DBAPIError

    assert isinstance(exc, DBAPIError)  # noqa: S101
    known = _SQLSTATE.get(str(getattr(exc.orig, "sqlstate", "")))
    if known is None:
        return await _unhandled(request, exc)
    status, slug, detail = known
    _log.info("database_input_error", sqlstate=getattr(exc.orig, "sqlstate", None))
    return problem_response(request, status, slug, detail=detail)


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    _log.exception("unhandled_error", exc_type=type(exc).__name__)
    return problem_response(request, 500, "internal")


def install_problem_handlers(app: FastAPI, routes: Iterable[tuple[str, BaseRoute]] = ()) -> None:
    """Register the handlers; ``routes`` are (full path, route) pairs for the 405 index."""
    app.state.problem_routes = list(routes)  # (full path, route), in mount order
    app.state.allowed_methods = None
    app.add_exception_handler(ProblemError, _problem_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    from sqlalchemy.exc import DBAPIError

    app.add_exception_handler(DBAPIError, _database_error)
    app.add_exception_handler(Exception, _unhandled)
