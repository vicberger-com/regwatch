"""Shared Pydantic building blocks matching openapi/regwatch.v1.yaml.

``UNSET`` marks a property the contract lists as optional but not nullable: the field may be
absent, and an explicit ``null`` is rejected. Serialise such models with ``exclude_unset``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Annotated, Any, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, Field

UNSET: Any = None

T = TypeVar("T")

Email = Annotated[str, Field(json_schema_extra={"format": "email"})]

# Input checks that leave the published JSON Schema unchanged (AfterValidator adds nothing to
# it), so the live document stays equal to the contract (review finding 10).
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL = 254
# C0, DEL and C1 controls (re-review N3b); bidirectional overrides and isolates that make
# displayed text read differently from what is stored (final review L3); line and paragraph
# separators; zero-width space and byte-order mark; and lone surrogates, which PostgreSQL cannot
# store (M2 review finding 9). Allowed: zero-width joiners (Persian, Indic scripts, emoji) and
# the right-to-left, left-to-right and Arabic letter marks (U+200F, U+200E, U+061C), which
# Arabic, Hebrew and Persian text carries (M2 re-verification N4).
_CONTROL = re.compile(
    "[\x00-\x1f\x7f-\x9f\u200b\u2028\u2029\u202a-\u202e\u2066-\u2069\ufeff\ud800-\udfff]"
)


def has_control(value: str, *, allow_newlines: bool = False) -> bool:
    """True if ``value`` holds C0, DEL or C1 control characters (tab and newlines optionally)."""
    if allow_newlines:
        value = value.replace("\n", "").replace("\r", "").replace("\t", "")
    return _CONTROL.search(value) is not None


def check_email(value: str) -> str:
    """A syntactic check until email-validator is registered (BL-14)."""
    value = value.strip()
    if len(value) > MAX_EMAIL or not _EMAIL.match(value) or _CONTROL.search(value):
        raise ValueError("must be an email address")
    return value


def max_len(limit: int, *, min_len: int = 0) -> Callable[[str], str]:
    def check(value: str) -> str:
        if not min_len <= len(value.strip() if min_len else value) <= limit:
            raise ValueError(f"must have {min_len} to {limit} characters")
        return value

    return check


def max_items(limit: int) -> Callable[[list[str]], list[str]]:
    def check(value: list[str]) -> list[str]:
        if len(value) > limit or any(len(v) > 200 for v in value):
            raise ValueError(f"must have at most {limit} entries of up to 200 characters")
        return value

    return check


def single_line(limit: int) -> Callable[[str], str]:
    """1 to ``limit`` characters after trimming, with no control characters (final review L2)."""
    length = max_len(limit, min_len=1)

    def check(value: str) -> str:
        if has_control(value):
            raise ValueError("must not contain control characters")
        return length(value)

    return check


EmailIn = Annotated[str, AfterValidator(check_email), Field(json_schema_extra={"format": "email"})]


class Page(BaseModel, Generic[T]):  # noqa: UP046 - Pydantic generic model
    """``components.schemas.Page``: the envelope of every paginated list."""

    items: list[T]
    total: int
    page: int
    page_size: int
