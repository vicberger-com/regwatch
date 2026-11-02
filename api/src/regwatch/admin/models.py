"""SQLAlchemy models. Tables come from docs/contracts/schema.sql (migration 0001, #28).

Only the columns the seed loader writes are mapped so far; M1 maps the rest.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from regwatch.core.db import Base


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)


class FeatureFlag(Base):
    __tablename__ = "feature_flag"

    key: Mapped[str] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(server_default=text("false"))
    description: Mapped[str]
