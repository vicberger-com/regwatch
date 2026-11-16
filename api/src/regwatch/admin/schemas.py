"""Pydantic schemas matching openapi/regwatch.v1.yaml (settings, flags, branding, audit)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from regwatch.core.schemas import UNSET


class Setting(BaseModel):
    key: str
    value: Any
    type: str
    default: Any = UNSET
    values: list[str] = UNSET
    note: str = UNSET
    updated_at: datetime = UNSET
    updated_by: UUID | None = None


class SettingWrite(BaseModel):
    value: Any


class FeatureFlag(BaseModel):
    key: str
    enabled: bool
    description: str


class FeatureFlagWrite(BaseModel):
    enabled: bool


class Branding(BaseModel):
    site_title: str = UNSET
    logo_url: str | None = None
    company_name: str = UNSET
    company_short_name: str = UNSET
    company_address: str = UNSET
    primary_color: str | None = None
    required_markings: str = UNSET


class BrandingPublic(BaseModel):
    """What the sign-in page may show before sign-in (CP-08)."""

    site_title: str
    logo_url: str | None = None
    primary_color: str | None = None
    has_legal_page: bool


class BrandingWrite(BaseModel):
    site_title: str = Field(default=UNSET, max_length=80)
    company_name: str = Field(default=UNSET, max_length=200)
    company_short_name: str = Field(default=UNSET, max_length=40)
    company_address: str = Field(default=UNSET, max_length=500)
    primary_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class Legal(BaseModel):
    html: str = UNSET
    required_markings: str = UNSET


class LegalWrite(BaseModel):
    page_markdown: str = Field(default=UNSET, max_length=200000)
    required_markings: str = Field(default=UNSET, max_length=2000)


class AuditEntry(BaseModel):
    id: UUID = UNSET
    occurred_at: datetime = UNSET
    actor_user_id: UUID | None = None
    actor_email: str | None = None
    action: str = UNSET
    entity_type: str = UNSET
    entity_id: str | None = None
    before: Any = None
    after: Any = None
    ip: str | None = None
    request_id: str | None = None
