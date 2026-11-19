"""SQLAlchemy models. Tables come from docs/contracts/schema.sql (migration 0001, #28)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from regwatch.core.db import Base


class SavedView(Base):
    __tablename__ = "saved_view"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    name: Mapped[str]
    view_by: Mapped[str] = mapped_column(server_default=text("'country'"))
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    period_days: Mapped[int] = mapped_column(server_default=text("30"))
    color_scheme: Mapped[str] = mapped_column(server_default=text("'recency'"))
    is_default: Mapped[bool] = mapped_column(server_default=text("false"))
    shared: Mapped[bool] = mapped_column(server_default=text("false"))
