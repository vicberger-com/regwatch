"""SQLAlchemy models. Tables come from docs/contracts/schema.sql (migration 0001, #28).

Only the columns the seed loader writes are mapped so far; M1 maps the rest.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, text
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
