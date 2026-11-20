"""Pydantic schemas matching openapi/regwatch.v1.yaml (report templates and layouts)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from regwatch.core.schemas import UNSET
from regwatch.search.schemas import Query

PageSize = Literal["A4", "Letter"]
Orientation = Literal["portrait", "landscape"]


class ReportParameterDef(BaseModel):
    key: str = UNSET
    label: str = UNSET
    type: Literal["jurisdiction", "period_days", "date_range", "facet_terms", "saved_view"] = UNSET
    required: bool = UNSET
    default: int | None = None  # CP-31: a default value (period_days)


class TemplateParameter(BaseModel):
    """A stock report's parameter as stored (M7.3): its definition and an optional default."""

    model_config = ConfigDict(extra="forbid")

    key: Literal["jurisdiction", "period_days", "facet_terms"]
    label: str = Field(max_length=120)
    type: Literal["jurisdiction", "period_days", "facet_terms"]
    required: bool = False
    default: int | None = Field(default=None, ge=1, le=3660)


class ReportParams(BaseModel):
    """Values for ReportParameterDef keys, for example jurisdiction DE and period_days 30."""

    model_config = ConfigDict(extra="allow")


class ReportTemplate(BaseModel):
    key: str = UNSET
    label: str = UNSET
    description: str = UNSET
    thumbnail_url: str | None = None
    version: int = UNSET
    parameters: list[ReportParameterDef] = UNSET


class ReportField(BaseModel):
    key: str = UNSET
    label: str = UNSET
    type: str = UNSET
    sortable: bool = UNSET
    group: str = UNSET


class ReportDataSource(BaseModel):
    saved_view_id: UUID | None = None
    query: Query = UNSET
    limit: int = Field(default=500, ge=1, le=5000)


class ReportLayout(BaseModel):
    id: UUID
    user_id: UUID = UNSET
    name: str
    based_on_template_key: str | None = None
    layout: dict[str, Any]
    data_source: ReportDataSource = UNSET
    page_size: PageSize
    orientation: Orientation
    shared: bool
    version: int
    updated_at: datetime = UNSET


class ReportLayoutWrite(BaseModel):
    name: str = Field(default=UNSET, max_length=120)
    layout: dict[str, Any] = UNSET
    data_source: ReportDataSource = UNSET
    page_size: PageSize = UNSET
    orientation: Orientation = UNSET
    shared: bool = UNSET
