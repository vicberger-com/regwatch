"""SQLAlchemy models. Tables come from docs/contracts/schema.sql (migration 0001, #28)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from regwatch.core.db import Base


class AuditLog(Base):
    """Append-only: the application role has INSERT and SELECT only (schema.sql)."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    occurred_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    actor_user_id: Mapped[uuid.UUID | None]
    action: Mapped[str]
    entity_type: Mapped[str]
    entity_id: Mapped[str | None]
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)
    request_id: Mapped[str | None]
