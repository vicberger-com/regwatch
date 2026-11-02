"""Shared Pydantic building blocks matching openapi/regwatch.v1.yaml.

``UNSET`` marks a property the contract lists as optional but not nullable: the field may be
absent, and an explicit ``null`` is rejected. Serialise such models with ``exclude_unset``.
"""

from __future__ import annotations

from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, Field

UNSET: Any = None

T = TypeVar("T")

Email = Annotated[str, Field(json_schema_extra={"format": "email"})]


class Page(BaseModel, Generic[T]):  # noqa: UP046 - Pydantic generic model
    """``components.schemas.Page``: the envelope of every paginated list."""

    items: list[T]
    total: int
    page: int
    page_size: int
