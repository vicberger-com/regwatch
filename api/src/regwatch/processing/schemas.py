"""Pydantic schemas matching openapi/regwatch.v1.yaml (items, versions, change events)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from regwatch.core.schemas import UNSET

Severity = Literal["info", "notable", "major"]
ItemStatus = Literal["new", "updated", "unchanged", "archived"]
Feedback = Literal["correct", "incorrect"]


class ItemJurisdiction(BaseModel):
    code: str = UNSET
    name: str = UNSET
    confidence: float = UNSET


class TermAssignment(BaseModel):
    term_id: UUID = UNSET
    facet_key: str = UNSET
    key: str = UNSET
    label: str = UNSET
    confidence: float = UNSET
    assigned_by: Literal["rule", "model", "user", "source_default"] = UNSET
    feedback: Feedback | None = None


class ItemSummary(BaseModel):
    id: UUID
    title: str
    title_en: str | None = None
    summary: str | None = None
    summary_en: str | None = None
    canonical_url: str = UNSET
    source_id: UUID
    source_name: str = UNSET
    language: str | None = None
    published_at: datetime | None = None
    last_changed_at: datetime
    status: ItemStatus
    severity: Severity | None = None
    jurisdictions: list[ItemJurisdiction]
    terms: list[TermAssignment] = UNSET
    attributes: dict[str, Any] = UNSET
    highlights: dict[str, list[str]] = UNSET


class ChangeEvent(BaseModel):
    id: UUID = UNSET
    item_id: UUID = UNSET
    jurisdiction_code: str = UNSET
    kind: Literal["new_item", "content_changed", "status_changed", "effective_date_reached"] = UNSET
    occurred_at: datetime = UNSET
    severity: Severity = UNSET
    summary: str | None = None
    acknowledged_by: UUID | None = None


class Regulation(BaseModel):
    id: UUID = UNSET
    title: str = UNSET
    status: str = UNSET


class ItemDetail(ItemSummary):
    content_text: str = UNSET
    content_text_en: str | None = None
    content_html_url: str | None = None
    current_version_no: int = UNSET
    needs_review: bool = UNSET
    translation_pending: bool = UNSET
    regulation: Regulation | None = None
    change_events: list[ChangeEvent] = UNSET


class ItemVersion(BaseModel):
    version_no: int = UNSET
    created_at: datetime = UNSET
    run_id: UUID | None = None
    content_hash: str = UNSET
    changed_pct: float | None = None
    translations: dict[str, Any] = UNSET


class ItemDiff(BaseModel):
    from_version: int = UNSET
    to_version: int = UNSET
    changed_pct: float = UNSET
    unified_diff: str = UNSET


class TermFeedback(BaseModel):
    term_id: UUID = UNSET
    feedback: Feedback = UNSET


class TagsUpdate(BaseModel):
    add_term_ids: list[UUID] = UNSET
    remove_term_ids: list[UUID] = UNSET
    add_jurisdiction_codes: list[str] = UNSET
    remove_jurisdiction_codes: list[str] = UNSET
    feedback: list[TermFeedback] = UNSET
