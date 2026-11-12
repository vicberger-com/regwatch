"""Pydantic schemas matching openapi/regwatch.v1.yaml (facets, terms, jurisdictions)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, StrictBool, StrictFloat, StrictInt

from regwatch.core.schemas import UNSET

ValueType = Literal["term", "text", "number", "date", "boolean"]
JurisdictionKind = Literal["country", "subdivision", "supranational"]
KEY_PATTERN = r"^[a-z][a-z0-9_]{1,40}$"


class MatchRules(BaseModel):
    keywords: list[str] = UNSET
    regex: list[str] = UNSET
    languages: list[str] = UNSET
    min_hits: StrictInt = 1
    weight: StrictFloat = 1.0


class Term(BaseModel):
    id: UUID
    facet_key: str
    key: str
    label: str
    parent_id: UUID | None = None
    synonyms: list[str] = UNSET
    match_rules: MatchRules = UNSET
    color_token: str | None = None
    active: bool
    item_count: int = UNSET
    children: list[Term] = UNSET


class TermWrite(BaseModel):
    key: str = UNSET
    label: str = UNSET
    parent_id: UUID | None = None
    synonyms: list[str] = UNSET
    match_rules: MatchRules = UNSET
    color_token: str | None = None
    active: StrictBool = UNSET


class Facet(BaseModel):
    id: UUID
    key: str
    label: str
    value_type: ValueType
    multi: bool
    required: bool
    show_in_view_selector: bool
    show_in_filters: bool
    sort_order: int
    system: bool
    hidden: bool
    terms: list[Term] = UNSET


class FacetWrite(BaseModel):
    key: str = Field(default=UNSET, pattern=KEY_PATTERN)
    label: str = UNSET
    value_type: ValueType = UNSET
    multi: StrictBool = UNSET
    required: StrictBool = UNSET
    show_in_view_selector: StrictBool = UNSET
    show_in_filters: StrictBool = UNSET
    sort_order: StrictInt = UNSET
    hidden: StrictBool = UNSET


class TermMerge(BaseModel):
    into_term_id: UUID


class MergeResult(BaseModel):
    items_moved: int = UNSET


class RuleTest(BaseModel):
    text: str = Field(max_length=50000)
    language: str = UNSET


class RuleTestResult(BaseModel):
    matched: bool = UNSET
    confidence: float = UNSET
    evidence: list[str] = UNSET


class ViewDimension(BaseModel):
    key: str = UNSET
    label: str = UNSET
    kind: Literal["builtin", "facet"] = UNSET


class ImportSummary(BaseModel):
    facets_created: int = UNSET
    facets_updated: int = UNSET
    terms_created: int = UNSET
    terms_updated: int = UNSET


class Jurisdiction(BaseModel):
    id: UUID
    code: str
    name: str
    kind: JurisdictionKind
    parent_code: str | None = None
    region_code: str | None = None
    geometry_ref: str | None = None
    active: bool


class JurisdictionWrite(BaseModel):
    code: str = UNSET
    name: str = UNSET
    kind: JurisdictionKind = UNSET
    parent_code: str | None = None
    region_code: str | None = None
    geometry_ref: str | None = None
    active: StrictBool = UNSET


class Region(BaseModel):
    code: str = UNSET
    name: str = UNSET
    jurisdiction_codes: list[str] = UNSET
