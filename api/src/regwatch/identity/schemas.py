"""Pydantic schemas matching openapi/regwatch.v1.yaml (auth, users, roles, me)."""

from __future__ import annotations

import re
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


Code = Annotated[str, Field(min_length=2, max_length=16, pattern=r"^[A-Za-z0-9_-]+$")]
Key = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")]


_FACET_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _facet_keys(terms: dict[str, list[str]]) -> dict[str, list[str]]:
    if bad := next((k for k in terms if not _FACET_KEY.fullmatch(k)), None):
        raise ValueError(f"facet key {bad[:64]!r} is not a key")
    return terms


class Interests(BaseModel):
    """A user's interests (M11, ADR-0012): default filters on the map, items and search, never
    a limit on what they may see. The same shapes as ``QueryFilters``."""

    jurisdictions: list[Code] = Field(default_factory=list, max_length=50)
    regions: list[Code] = Field(default_factory=list, max_length=20)
    # Facet keys get the term-key pattern by a validator (a typed dict key would change the
    # contract's JSON schema); they are also checked against the offered facets when saved.
    terms: Annotated[
        dict[str, Annotated[list[Key], Field(max_length=20)]],
        AfterValidator(_facet_keys),
    ] = Field(default_factory=dict, max_length=20)


class InterestOption(BaseModel):
    key: str
    label: str


class InterestRegion(BaseModel):
    """A region, with the jurisdictions it covers (sub-regions of a continent, and bodies such
    as the EU for Europe), so interests in places combine as one "any of" list (M11.1 review)."""

    key: str
    label: str
    members: list[str]


class InterestFacet(BaseModel):
    key: str
    label: str
    terms: list[InterestOption]


class InterestJurisdiction(BaseModel):
    code: str
    name: str
    region_code: str | None = None


class InterestOptions(BaseModel):
    """What a user may pick as interests: facets shown in filters with their active terms,
    active jurisdictions, and regions. Open to every signed-in user (BL-125 for M11)."""

    facets: list[InterestFacet]
    jurisdictions: list[InterestJurisdiction]
    regions: list[InterestRegion]


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
    interests: Interests = UNSET


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


class Group(BaseModel):
    """CP-27: a group of users. Its roles apply to its members alongside their own."""

    id: UUID
    key: str
    name: str
    description: str | None = None
    roles: list[str]
    members: list[UUID]
    interests: Interests = UNSET  # the members' default interests (M11.4b)


class MyGroup(BaseModel):
    """CP-27: a group the signed-in user is in, with its interests (live)."""

    id: UUID
    key: str
    name: str
    interests: Interests


class GroupWrite(BaseModel):
    key: str = Field(default=UNSET, pattern=r"^[a-z][a-z0-9_-]{1,40}$")
    name: Annotated[str, AfterValidator(single_line(120))] = Field(default=UNSET, max_length=120)
    description: Annotated[str, AfterValidator(single_line(500))] | None = Field(
        default=UNSET, max_length=500
    )
    roles: RoleKeys = UNSET
    interests: Interests = UNSET


class SsoStatus(BaseModel):
    """CP-37 ``GET /auth/sso``: whether the login page offers the organisation's sign-in."""

    enabled: bool
