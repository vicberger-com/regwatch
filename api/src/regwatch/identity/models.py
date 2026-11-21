"""SQLAlchemy models. Tables come from docs/contracts/schema.sql (migration 0001, #28)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from regwatch.core.db import Base


class Permission(Base):
    __tablename__ = "permission"

    key: Mapped[str] = mapped_column(primary_key=True)
    description: Mapped[str]
    module: Mapped[str]


class Role(Base):
    __tablename__ = "role"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    key: Mapped[str] = mapped_column(unique=True)
    label: Mapped[str]
    system: Mapped[bool] = mapped_column(server_default=text("false"))


class RolePermission(Base):
    __tablename__ = "role_permission"

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("role.id", ondelete="CASCADE"), primary_key=True
    )
    permission_key: Mapped[str] = mapped_column(
        ForeignKey("permission.key", ondelete="CASCADE"), primary_key=True
    )


class User(Base):
    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    display_name: Mapped[str]
    password_hash: Mapped[str | None]
    external_subject: Mapped[str | None] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(server_default=text("'active'"))
    must_change_password: Mapped[bool] = mapped_column(server_default=text("false"))
    last_login_at: Mapped[datetime | None]
    failed_logins: Mapped[int] = mapped_column(server_default=text("0"))
    locked_until: Mapped[datetime | None]
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))


class UserRole(Base):
    __tablename__ = "user_role"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("role.id", ondelete="CASCADE"), primary_key=True
    )


class UserSession(Base):
    __tablename__ = "session"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(unique=True)
    expires_at: Mapped[datetime]
    last_seen_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None]
    revoked_at: Mapped[datetime | None]
    method: Mapped[str] = mapped_column(server_default=text("'password'"))  # CP-40, 0013


class UserGroup(Base):
    """A group of users with roles and an interest profile (CP-27, migration 0010)."""

    __tablename__ = "user_group"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    key: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    description: Mapped[str | None]
    interests: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class GroupMember(Base):
    __tablename__ = "group_member"

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_group.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )


class GroupRole(Base):
    __tablename__ = "group_role"

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_group.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("role.id", ondelete="CASCADE"), primary_key=True
    )


class UserMfa(Base):
    """A user's TOTP authenticator (BL-148; migration 0012)."""

    __tablename__ = "user_mfa"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    secret_enc: Mapped[str]
    confirmed_at: Mapped[datetime | None]
    last_step: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    recovery_hashes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
