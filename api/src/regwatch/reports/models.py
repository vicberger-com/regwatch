"""SQLAlchemy models. Tables come from docs/contracts/schema.sql (migration 0001)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from regwatch.core.db import Base


class ReportTemplate(Base):
    __tablename__ = "report_template"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    key: Mapped[str] = mapped_column(unique=True)
    label: Mapped[str]
    description: Mapped[str | None]
    layout: Mapped[dict[str, Any]] = mapped_column(JSONB)
    query: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    version: Mapped[int] = mapped_column(server_default=text("1"))


class ReportLayout(Base):
    __tablename__ = "report_layout"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    name: Mapped[str]
    based_on_template_key: Mapped[str | None] = mapped_column(ForeignKey("report_template.key"))
    layout: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # The data source (ReportDataSource) lives in the contract's ``query`` column.
    query: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    page_size: Mapped[str] = mapped_column(server_default=text("'A4'"))
    orientation: Mapped[str] = mapped_column(server_default=text("'portrait'"))
    shared: Mapped[bool] = mapped_column(server_default=text("false"))
    version: Mapped[int] = mapped_column(server_default=text("1"))
