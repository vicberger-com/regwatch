"""Pydantic schemas matching openapi/regwatch.v1.yaml (queries, map activity, saved views)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from regwatch.core.schemas import UNSET, Page
from regwatch.processing.schemas import ItemStatus, ItemSummary, Severity

ColorScheme = Literal["recency", "count", "severity"]
Credibility = Literal["official", "secondary", "news"]


class DateRange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: datetime = Field(default=UNSET, alias="from")
    to: datetime = UNSET


class QueryFilters(BaseModel):
    # 300: every jurisdiction, so interests in regions can be sent as one any-of list (CP-24).
    jurisdictions: list[str] = Field(default=UNSET, max_length=300)
    regions: list[str] = Field(default=UNSET, max_length=20)
    terms: dict[str, Annotated[list[str], Field(max_length=20)]] = UNSET
    sources: list[UUID] = Field(default=UNSET, max_length=50)
    status: list[ItemStatus] = UNSET
    severity: list[Severity] = UNSET
    languages: list[str] = UNSET
    credibility: list[Credibility] = UNSET
    published: DateRange = UNSET
    changed: DateRange = UNSET
    needs_review: bool = UNSET


class Query(BaseModel):
    q: str = Field(default=UNSET, max_length=500)
    filters: QueryFilters = UNSET
    sort: Literal[
        "relevance", "last_changed_desc", "last_changed_asc", "published_desc", "published_asc",
        "title_asc",
    ] = "relevance"  # fmt: skip
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    highlight: bool = True
    facet_counts: bool = True
    columns: list[str] = UNSET


class FacetCount(BaseModel):
    key: str = UNSET
    label: str = UNSET
    count: int = UNSET


class SearchResult(Page[ItemSummary]):
    facets: dict[str, list[FacetCount]] = UNSET
    took_ms: int = UNSET


class MapRow(BaseModel):
    code: str
    count: int
    last_changed_at: datetime | None = None
    max_severity: Literal["none", "info", "notable", "major"]
    breakdown: dict[str, int] = UNSET


class MapActivity(BaseModel):
    period_start: datetime
    period_end: datetime
    view_by: str
    generated_at: datetime = UNSET
    stale: bool = UNSET
    rows: list[MapRow]


class SavedView(BaseModel):
    id: UUID
    user_id: UUID | None = None
    name: str
    view_by: str
    filters: QueryFilters
    q: str | None = None
    period_days: int
    color_scheme: ColorScheme
    is_default: bool = UNSET
    shared: bool
    updated_at: datetime = UNSET


class SavedViewWrite(BaseModel):
    name: str = Field(default=UNSET, max_length=120)
    view_by: str = UNSET
    filters: QueryFilters = UNSET
    q: str = UNSET
    period_days: int = Field(default=UNSET, ge=1, le=3660)
    color_scheme: ColorScheme = UNSET
    is_default: bool = UNSET
    shared: bool = UNSET
