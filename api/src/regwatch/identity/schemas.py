"""Pydantic schemas matching openapi/regwatch.v1.yaml (auth, users, roles, me)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from regwatch.core.schemas import UNSET, Email


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
    email: Email
    display_name: str = Field(max_length=120)
    roles: list[str]


class UserUpdate(BaseModel):
    display_name: str = UNSET
    roles: list[str] = UNSET
    status: UserStatus = UNSET


class TemporaryPassword(BaseModel):
    temporary_password: str = UNSET


class Login(BaseModel):
    email: Email
    password: str
    remember_me: bool = False


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12)


class Role(BaseModel):
    id: UUID
    key: str
    label: str
    permissions: list[str]
    system: bool


class RoleWrite(BaseModel):
    key: str = Field(default=UNSET, pattern=r"^[a-z][a-z0-9_]{1,40}$")
    label: str = UNSET
    permissions: list[str] = UNSET


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
