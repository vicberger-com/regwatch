"""SQLAlchemy models. Tables come from docs/contracts/schema.sql (migration 0001, #28)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from regwatch.core.db import Base


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class FeatureFlag(Base):
    __tablename__ = "feature_flag"

    key: Mapped[str] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(server_default=text("false"))
    description: Mapped[str]
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
