"""Pydantic schemas matching openapi/regwatch.v1.yaml (sources, capture jobs and runs)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from regwatch.core.schemas import UNSET

Credibility = Literal["official", "secondary", "news"]
RobotsPolicy = Literal["respect", "override"]


class SourceKind(StrEnum):
    rss = "rss"
    web_page = "web_page"
    web_crawl = "web_crawl"
    search_query = "search_query"
    api_feed = "api_feed"
    manual = "manual"


class CaptureJob(BaseModel):
    id: UUID
    source_id: UUID
    cron: str | None = None
    interval_seconds: int | None = None
    timezone: str = UNSET
    max_items_per_run: int = UNSET
    rate_limit_per_minute: int = UNSET
    render_js: bool = UNSET
    extraction_rules: dict[str, Any] = UNSET
    change_threshold_pct: float = UNSET
    enabled: bool
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None


class CaptureJobWrite(BaseModel):
    cron: str | None = None
    interval_seconds: int | None = Field(default=None, ge=900)
    timezone: str = UNSET
    max_items_per_run: int = Field(default=UNSET, le=2000)
    rate_limit_per_minute: int = Field(default=UNSET, ge=1, le=120)
    render_js: bool = UNSET
    extraction_rules: dict[str, Any] = UNSET
    change_threshold_pct: float = Field(default=UNSET, ge=0, le=100)
    enabled: bool = UNSET


class Source(BaseModel):
    id: UUID
    name: str
    kind: SourceKind
    url: str | None = None
    config: dict[str, Any] = UNSET
    default_jurisdiction_codes: list[str] = UNSET
    default_term_ids: list[UUID] = UNSET
    credibility: Credibility = UNSET
    robots_policy: RobotsPolicy = UNSET
    override_reason: str | None = None
    terms_url: str | None = None
    language: str | None = None
    enabled: bool
    health: Literal["unknown", "healthy", "degraded", "unhealthy"]
    consecutive_failures: int = UNSET
    job: CaptureJob = UNSET
    created_at: datetime = UNSET
    catalogue_key: str | None = None  # CP-25: a catalogue source
    summary: str | None = None
    followers: int = UNSET  # how many users follow it; never who
    captured: bool = UNSET  # fetched now: job on, and enabled or followed


class CatalogueEntry(BaseModel):
    """A catalogue source as users see it (CP-25)."""

    id: UUID
    key: str
    name: str
    summary: str
    kind: SourceKind
    url: str | None = None
    terms_url: str | None = None
    credibility: Credibility
    language: str | None = None
    jurisdictions: list[str]
    health: Literal["unknown", "healthy", "degraded", "unhealthy"]
    available: bool  # false: an administrator turned it off
    captured: bool  # someone follows it, or an administrator enabled it
    following: bool  # the signed-in user follows it


class SourceWrite(BaseModel):
    name: str = Field(default=UNSET, max_length=200)
    kind: SourceKind = UNSET
    url: str = UNSET
    config: dict[str, Any] = UNSET
    default_jurisdiction_codes: list[str] = UNSET
    default_term_ids: list[UUID] = UNSET
    credibility: Credibility = UNSET
    robots_policy: RobotsPolicy = UNSET
    override_reason: str = UNSET
    terms_url: str = UNSET
    language: str = UNSET
    enabled: bool = UNSET
    job: CaptureJobWrite = UNSET


class CaptureRun(BaseModel):
    id: UUID = UNSET
    job_id: UUID = UNSET
    started_at: datetime = UNSET
    finished_at: datetime | None = None
    status: Literal["running", "success", "partial", "failed", "skipped"] = UNSET
    items_new: int = UNSET
    items_changed: int = UNSET
    items_unchanged: int = UNSET
    http_status: int | None = None
    bytes_fetched: int = UNSET
    error_class: str | None = None
    error_message: str | None = None
    robots_decision: str | None = None


class SourceHealth(BaseModel):
    source_id: UUID = UNSET
    health: str = UNSET
    consecutive_failures: int = UNSET
    last_success_at: datetime | None = None
    success_rate_7d: float = UNSET
    runs_7d: int = UNSET
    last_error: str | None = None


class Candidate(BaseModel):
    url: str = UNSET
    title: str | None = None
    published_at: datetime | None = None
    external_id: str | None = None


class DocumentAccepted(BaseModel):
    """``POST /sources/{id}/documents`` (CP-17): the run that adds the document."""

    run_id: UUID


class SourceTestResult(BaseModel):
    candidates: list[Candidate] = Field(default=UNSET, max_length=5)
    robots_decision: str = UNSET
    warnings: list[str] = UNSET
