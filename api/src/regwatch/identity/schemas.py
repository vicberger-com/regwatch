"""Pydantic schemas matching openapi/regwatch.v1.yaml (auth, users, roles, me)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field

from regwatch.core.schemas import UNSET, Email, EmailIn, max_items, max_len, single_line

Secret = Annotated[str, AfterValidator(max_len(1024))]
RoleKeys = Annotated[list[str], AfterValidator(max_items(50))]


class UserStatus(StrEnum):
    active = "active"
    disabled = "disabled"
    locked = "locked"


class Preferences(BaseModel):
    theme: Literal["light", "dark", "high-contrast", "system"] = "system"
    accessibility_preset: bool = False
    font_scale: Literal[100, 112, 125, 150, 175, 200] = 100
    density: Literal["compact", "default", "comfortable"] = "default"
    reduced_motion: Literal["system", "on", "off"] = "system"
    toolbar_labels: Literal["hover", "always"] = "hover"
    locale: str = "en"
    timezone: str = "UTC"
    landing_view_id: UUID | None = None
    session_idle_timeout_minutes: int = Field(default=UNSET, ge=15)
    remember_me_default: bool = False


class User(BaseModel):
    id: UUID
    email: Email
    display_name: str
    status: UserStatus
    roles: list[str]
    must_change_password: bool = UNSET
    last_login_at: datetime | None = None
    created_at: datetime = UNSET


class UserWithPassword(User):
    temporary_password: str = UNSET


class Me(User):
    permissions: list[str] = UNSET
    preferences: Preferences = UNSET


class UserCreate(BaseModel):
    email: EmailIn
    display_name: Annotated[str, AfterValidator(single_line(120))] = Field(max_length=120)
    roles: RoleKeys


class UserUpdate(BaseModel):
    display_name: Annotated[str, AfterValidator(single_line(120))] = UNSET
    roles: RoleKeys = UNSET
    status: UserStatus = UNSET


class TemporaryPassword(BaseModel):
    temporary_password: str = UNSET


class Login(BaseModel):
    email: EmailIn
    password: Secret
    remember_me: bool = False


class PasswordChange(BaseModel):
    current_password: Secret
    new_password: str = Field(min_length=12)


class Role(BaseModel):
    id: UUID
    key: str
    label: str
    permissions: list[str]
    system: bool


class RoleWrite(BaseModel):
    key: str = Field(default=UNSET, pattern=r"^[a-z][a-z0-9_]{1,40}$")
    label: Annotated[str, AfterValidator(single_line(120))] = UNSET
    permissions: Annotated[list[str], AfterValidator(max_items(200))] = UNSET


class Permission(BaseModel):
    key: str = UNSET
    description: str = UNSET
    module: str = UNSET


class SessionInfo(BaseModel):
    id: UUID = UNSET
    created_at: datetime = UNSET
    last_seen_at: datetime = UNSET
    expires_at: datetime = UNSET
    ip: str | None = None
    user_agent: str | None = None
    current: bool = UNSET
